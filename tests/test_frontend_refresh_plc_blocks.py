"""Smoke test del wiring SPA ↔ endpoint de cache de bloques PLC.

La SPA es Vue 3 ESM sin build step y sin infra de tests JS
(Jest/Vitest no están en el repo). En lugar de importar los
``.js`` desde pytest (que necesitaría Node + ESM + DOM mock),
este test verifica la **forma textual** del wiring: que los
símbolos públicos esperados aparezcan en los archivos correctos.

Es un contract check barato. Si en el futuro se añade infra JS,
se puede sustituir por tests unitarios de verdad sobre el helper
``refreshPlcBlocks``.

Marcado con ``@pytest.mark.frontend_smoke`` para permitir
filtrado (``pytest -m frontend_smoke``).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
API_JS = REPO_ROOT / "interfaces" / "web_server" / "static" / "js" / "api.js"
STORE_JS = REPO_ROOT / "interfaces" / "web_server" / "static" / "js" / "store.js"
SIDEBAR_JS = (
    REPO_ROOT
    / "areas"
    / "alimentacion"
    / "frontend"
    / "components"
    / "Sidebar.js"
)
STYLES_CSS = REPO_ROOT / "interfaces" / "web_server" / "static" / "styles.css"


pytestmark = pytest.mark.frontend_smoke


def _read(path: Path) -> str:
    assert path.exists(), f"Missing required SPA file: {path}"
    return path.read_text(encoding="utf-8")


def test_api_js_exposes_block_cache_endpoints() -> None:
    """``api.js`` declara ``apiScanPlcBlocks`` y ``apiRefreshPlcBlocks``."""
    text = _read(API_JS)
    assert "export function apiScanPlcBlocks" in text
    assert "export function apiRefreshPlcBlocks" in text
    assert "/api/v1/plcs/" in text  # mismo namespace que el resto de endpoints PLC


def test_api_js_exposes_project_info_endpoint() -> None:
    """``api.js`` declara ``apiFetchProjectInfo`` apuntando al endpoint nuevo."""
    text = _read(API_JS)
    assert "export const apiFetchProjectInfo" in text
    # URL correcta del endpoint nuevo.
    assert "/api/v1/portal/project-info" in text


def test_store_js_exposes_unified_helper() -> None:
    """``store.js`` expone ``loadAndApplyPlcBlocks`` (helper unificado).

    El refactor funde los antiguos ``refreshPlcBlocks`` (thin
    wrapper del progreso), ``loadPlcBlocksCache`` (versión datos) y
    ``refreshPlcBlocksCache`` (versión forzada) en una sola
    función con ``{ force = false }``. Mismo contrato observable
    (slot ``plcBlocksCache``, feedback del ``ProgressTracker``
    backend) y un solo round-trip HTTP por cambio de PLC.

    PERO el feedback de la operación larga sigue siendo 100%
    backend (``ProgressTracker``): no reintroducimos el badge
    legacy con su estado local (``scanningPlc``, ``lastScanError``,
    ``cacheSummary``).
    """
    text = _read(STORE_JS)
    # Helper unificado presente.
    assert "export async function loadAndApplyPlcBlocks" in text
    # Helpers legacy eliminados (asserts negativos: la API antigua
    # ya no existe).
    assert "export async function refreshPlcBlocks" not in text
    assert "export async function loadPlcBlocksCache" not in text
    assert "export async function refreshPlcBlocksCache" not in text
    # Slot de datos para la vista ``BloquesCacheView`` (NO es
    # feedback de progreso; lo escribe el helper unificado).
    assert "plcBlocksCache:" in text
    # NO reintroducimos el badge legacy con su estado efímero.
    assert "scanningPlc:" not in text
    assert "lastScanError:" not in text
    assert "export function cacheSummary" not in text
    assert "cacheSummary()" not in text


def test_sidebar_wires_change_handler_to_progress_indicator() -> None:
    """``Sidebar.js`` une el ``@change`` del select con ``loadAndApplyPlcBlocks``.

    El feedback se ve en el ``ProgressIndicator`` (que ya está
    anclado al fondo del sidebar), no en un badge propio. Por
    eso este test verifica que NO reintroducimos el badge custom
    con su botón ↻. Tras el refactor unificado, ``onPlcSelected``
    hace UNA sola llamada al helper del store.
    """
    text = _read(SIDEBAR_JS)
    # Wiring del select → scan via el helper unificado del store.
    assert "@change=\"onPlcSelected\"" in text
    assert "loadAndApplyPlcBlocks" in text
    # El handler ya no encadena dos llamadas (refactor: una sola).
    assert "refreshPlcBlocks" not in text
    assert "loadPlcBlocksCache" not in text
    # El ProgressIndicator del sidebar sigue montado (donde aparece
    # el task de "Cache de bloques de <plc>").
    assert "<ProgressIndicator" in text
    # NO reintroducimos el badge custom ni el ↻ propio.
    assert "plc-blocks-cache-badge" not in text
    assert "plc-blocks-cache-refresh" not in text
    assert "Forzar re-scan" not in text
    assert "Escaneando" not in text


def test_sidebar_button_text_is_buscar_plcs() -> None:
    """El botón del sidebar del área Alimentación dice ``Buscar PLCs``.

    Reemplaza el antiguo ``Refrescar lista`` (rename aprobado en
    el plan canónico). Verifica AMBOS lados: el texto nuevo
    está presente, el viejo NO (defensivo contra un rename
    parcial o un revert accidental).
    """
    text = _read(SIDEBAR_JS)
    assert "Buscar PLCs" in text, (
        "El botón del Sidebar del área Alimentación debe decir 'Buscar PLCs'. "
        "Si quieres otra variante, edita Sidebar.js y este test juntos."
    )
    assert "Refrescar lista" not in text, (
        "Texto legacy 'Refrescar lista' encontrado en Sidebar.js. "
        "Debe estar completamente sustituido por 'Buscar PLCs'."
    )


def test_sidebar_calls_api_fetch_project_info() -> None:
    """``handleRefreshPlcs`` invoca ``apiFetchProjectInfo`` en paralelo
    con ``apiFetchPlcs`` (mismo click del operario)."""
    text = _read(SIDEBAR_JS)
    # Importa la nueva función.
    assert "apiFetchProjectInfo" in text
    # La usa dentro del handler (no solo el import).
    assert "apiFetchProjectInfo()" in text
    # Y la combina en paralelo con apiFetchPlcs.
    assert "Promise.all" in text


def test_sidebar_renders_project_name_caption() -> None:
    """El template del sidebar pinta el caption ``Proyecto: <name>`` solo
    si ``store.projectInfo.name`` está disponible."""
    text = _read(SIDEBAR_JS)
    # data-testid para anclar el smoke test.
    assert "sidebar-project-name" in text
    # Texto visible esperado.
    assert "Proyecto:" in text
    # Guard v-if para no mostrar nada si aún no hay info.
    assert "store.projectInfo" in text
    assert "store.projectInfo.name" in text


def test_store_js_exposes_project_info_slot() -> None:
    """``store.js`` declara el slot ``projectInfo: null`` (estado base)."""
    text = _read(STORE_JS)
    assert "projectInfo:" in text, (
        "store.js debe declarar el slot projectInfo. Sin él, el sidebar "
        "no puede saber a qué proyecto TIA está conectado."
    )


def test_styles_css_is_nonempty_after_recompile() -> None:
    """El bundle CSS existe y tiene tamaño no trivial tras el
    recompile de Tailwind. No se valida contenido porque la
    compilación puede meter las nuevas clases en cualquier
    selector de los existentes.
    """
    assert STYLES_CSS.exists(), (
        "styles.css no se regeneró — ejecutar run_tailwind.bat "
        "antes de commit"
    )
    size = STYLES_CSS.stat().st_size
    # El output minificado de Tailwind para esta SPA suele rondar
    # los 15-25 KB. Usamos 10 KB como suelo para detectar
    # regeneraciones fallidas (p. ej. binario no encontrado o
    # input.css vacío).
    assert size > 10_000, (
        f"styles.css demasiado pequeño ({size} bytes); "
        "recompilar Tailwind antes de commit"
    )
