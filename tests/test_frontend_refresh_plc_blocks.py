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
# Tras el rediseño "Modern Corporate" v1, el chrome del shell
# (selección PLC + ProgressIndicator dark + back) se extrajo al
# componente genérico ``ShellSidebar`` en ``/js/components/``. En
# la v2, la selección PLC migró al nuevo ``ShellTopbar``
# cross-cutting; el ``ShellSidebar`` solo conserva nav +
# ProgressIndicator dark + back. Los tests apuntan al
# ``ShellTopbar`` para verificar el wiring de la selección PLC
# (que es lo que sigue siendo responsabilidad de la topbar).
SHELL_SIDEBAR_JS = (
    REPO_ROOT
    / "interfaces"
    / "web_server"
    / "static"
    / "js"
    / "components"
    / "ShellSidebar.js"
)
SHELL_TOPBAR_JS = (
    REPO_ROOT
    / "interfaces"
    / "web_server"
    / "static"
    / "js"
    / "components"
    / "ShellTopbar.js"
)
# Tras la migración v3.0 (sept-2026), la selección PLC y el
# ``handleRefreshPlcs`` con la detección de TIAConnectionError
# migraron de la ShellTopbar al primer card de
# ``BloquesCacheView``. Los tests positivos apuntan a este
# nuevo sujeto.
BLOQUES_CACHE_VIEW_JS = (
    REPO_ROOT
    / "areas" / "alimentacion" / "frontend" / "components"
    / "BloquesCacheView.js"
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


def test_bloques_cache_view_wires_change_handler_to_load_and_apply() -> None:
    """Tras la migración v3.0 (sept-2026), el ``<select>`` de PLC
    vive en el primer card de ``BloquesCacheView`` (no en la
    ShellTopbar). Une el ``@change`` con ``loadAndApplyPlcBlocks``
    via ``onPlcSelected`` (mismo wiring que tenía el topbar antes).
    """
    text = _read(BLOQUES_CACHE_VIEW_JS)
    # Wiring del select → scan via el helper unificado del store.
    assert "@change=\"onPlcSelected\"" in text, (
        "BloquesCacheView debe tener un <select> con "
        "@change=\"onPlcSelected\" en su template."
    )
    assert "loadAndApplyPlcBlocks" in text, (
        "BloquesCacheView debe importar y usar loadAndApplyPlcBlocks "
        "para que el @change del select dispare el scan de bloques."
    )
    # El handler ya no encadena dos llamadas (refactor: una sola).
    assert "refreshPlcBlocks" not in text
    assert "loadPlcBlocksCache" not in text
    # NO reintroducimos el badge custom ni el ↻ propio.
    assert "plc-blocks-cache-badge" not in text
    assert "plc-blocks-cache-refresh" not in text
    assert "Forzar re-scan" not in text
    assert "Escaneando" not in text


def test_shell_topbar_does_not_render_progress_indicator() -> None:
    """Asertos negativos: tras la v3.0, la ShellTopbar ya no monta
    ``<ProgressIndicator>`` ni el variant ``dark``. Migró al
    primer card de ``BloquesCacheView``. La topbar es solo chrome
    pasivo (breadcrumb + texto del PLC)."""
    text = _read(SHELL_TOPBAR_JS)
    # El topbar NO monta el ProgressIndicator.
    assert "<ProgressIndicator" not in text, (
        "ShellTopbar no debe montar <ProgressIndicator>: ese vive en el "
        "ShellSidebar (variant dark sobre fondo navy)."
    )
    assert "dark" not in text, (
        "ShellTopbar no debe incluir el variant 'dark' del ProgressIndicator."
    )


def test_bloques_cache_view_button_text_is_buscar_plcs() -> None:
    """Tras la v3.0, el botón "Buscar PLCs" vive en el primer card
    de ``BloquesCacheView`` (migrado desde la ShellTopbar)."""
    text = _read(BLOQUES_CACHE_VIEW_JS)
    assert "Buscar PLCs" in text, (
        "El botón de BloquesCacheView debe decir 'Buscar PLCs'. "
        "Si quieres otra variante, edita BloquesCacheView.js y este test juntos."
    )
    assert "Refrescar lista" not in text, (
        "Texto legacy 'Refrescar lista' encontrado en BloquesCacheView.js. "
        "Debe estar completamente sustituido por 'Buscar PLCs'."
    )


def test_bloques_cache_view_calls_api_fetch_project_info() -> None:
    """``handleRefreshPlcs`` (ahora en ``BloquesCacheView``) invoca
    ``apiFetchProjectInfo`` en paralelo con ``apiFetchPlcs``
    (mismo click del operario, v3.0)."""
    text = _read(BLOQUES_CACHE_VIEW_JS)
    # Importa la nueva función.
    assert "apiFetchProjectInfo" in text
    # La usa dentro del handler (no solo el import).
    assert "apiFetchProjectInfo()" in text
    # Y la combina en paralelo con apiFetchPlcs.
    assert "Promise.all" in text


def test_bloques_cache_view_renders_project_name_caption() -> None:
    """El primer card de ``BloquesCacheView`` pinta el caption del
    nombre del proyecto cuando ``tiaProjectName`` (computed
    derivado de ``store.tiaConnection.project.name`` con
    fallback a ``store.projectInfo.name``) está disponible."""
    text = _read(BLOQUES_CACHE_VIEW_JS)
    # El template pinta el caption.
    assert "Proyecto:" in text, (
        "BloquesCacheView debe pintar el caption 'Proyecto:' en su template."
    )
    # Computed que combina las 2 fuentes (tiaConnection.project + projectInfo).
    assert "tiaProjectName" in text
    # Fallback a store.projectInfo.name (compat con v2.2).
    assert "store.projectInfo" in text
    assert "projectInfo.name" in text


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
