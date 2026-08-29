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


def test_store_js_exposes_refresh_helper_only() -> None:
    """``store.js`` solo expone el helper ``refreshPlcBlocks`` (thin wrapper).

    El estado del cache y el feedback de la operación viven en el
    backend (``ProgressTracker``), no en el store. Verificamos
    explícitamente que NO reintroducimos el badge legacy con su
    estado local (``plcBlocksCache``, ``scanningPlc``, ``cacheSummary``).
    """
    text = _read(STORE_JS)
    # Helper exportado.
    assert "export async function refreshPlcBlocks" in text
    # NO hay estado local del cache de bloques en el store.
    assert "plcBlocksCache:" not in text
    assert "scanningPlc:" not in text
    assert "lastScanError:" not in text
    # NO hay helpers del badge legacy.
    assert "export function cacheSummary" not in text
    assert "cacheSummary()" not in text


def test_sidebar_wires_change_handler_to_progress_indicator() -> None:
    """``Sidebar.js`` une el ``@change`` del select con ``refreshPlcBlocks``.

    El feedback se ve en el ``ProgressIndicator`` (que ya está
    anclado al fondo del sidebar), no en un badge propio. Por
    eso este test verifica que NO reintroducimos el badge custom
    con su botón ↻.
    """
    text = _read(SIDEBAR_JS)
    # Wiring del select → scan via el helper del store.
    assert "@change=\"onPlcSelected\"" in text
    assert "refreshPlcBlocks" in text
    # El ProgressIndicator del sidebar sigue montado (donde aparece
    # el task de "Cache de bloques de <plc>").
    assert "<ProgressIndicator" in text
    # NO reintroducimos el badge custom ni el ↻ propio.
    assert "plc-blocks-cache-badge" not in text
    assert "plc-blocks-cache-refresh" not in text
    assert "Forzar re-scan" not in text
    assert "Escaneando" not in text


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
