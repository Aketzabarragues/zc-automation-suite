"""Smoke test del wiring SPA ↔ invalidacion de cache en TIA connection loss.

Cubre el lado frontend del fix: cuando el backend responde
``X-Error-Type: TIAConnectionError`` (header que los routers emiten
al atrapar ``TIAConnectionError`` desde
``core/infrastructure/gateway.py``), la SPA debe:

  1. ``api.js._request()`` extraer el header y exponerlo en el
     campo ``errorType`` del dict de retorno.
  2. ``store.js`` exponer un helper ``resetPlcState()`` que limpia
     el state relacionado con PLCs (``selectedPlc``,
     ``plcBlocksCache``, ``plcs``, ``previewData``, ``procesosSync``).
  3. Los componentes que llaman al gateway detecten
     ``r.errorType === "TIAConnectionError"`` y reseteen el state.

Como en el resto del repo, sin infra JS (Jest/Vitest): contract
checks textuales sobre los ``.js``.

Marcado con ``@pytest.mark.frontend_smoke`` para permitir
filtrado (``pytest -m frontend_smoke``).
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
API_JS = REPO_ROOT / "interfaces" / "web_server" / "static" / "js" / "api.js"
STORE_JS = REPO_ROOT / "interfaces" / "web_server" / "static" / "js" / "store.js"
SHELL_TOPBAR_JS = (
    REPO_ROOT
    / "interfaces"
    / "web_server"
    / "static"
    / "js"
    / "components"
    / "ShellTopbar.js"
)
DISPOSITIVOS_JS = (
    REPO_ROOT
    / "areas"
    / "alimentacion"
    / "frontend"
    / "components"
    / "Dispositivos.js"
)
PROCESOS_SYNC_VIEW_JS = (
    REPO_ROOT
    / "areas"
    / "alimentacion"
    / "frontend"
    / "components"
    / "ProcesosSyncView.js"
)


pytestmark = pytest.mark.frontend_smoke


def _read(path: Path) -> str:
    assert path.exists(), f"Missing required SPA file: {path}"
    return path.read_text(encoding="utf-8")


# ── api.js: extrae X-Error-Type ──────────────────────────────────────


def test_api_js_extracts_x_error_type_header() -> None:
    """``_request`` extrae el header ``X-Error-Type`` y lo expone
    en el campo ``errorType`` del dict de retorno."""
    text = _read(API_JS)
    # La funcion debe leer el header...
    assert 'headers.get("X-Error-Type")' in text, (
        "_request debe leer el header 'X-Error-Type' para detectar "
        "errores de conexion TIA (ver core/infrastructure/gateway.py)."
    )
    # ...y exponerlo en el shape de retorno.
    assert "errorType" in text, (
        "_request debe propagar el valor del header en el dict "
        "de retorno para que los componentes lo consuman."
    )


# ── store.js: expone resetPlcState ──────────────────────────────────


def test_store_js_exposes_reset_plc_state_helper() -> None:
    """``store.js`` expone ``resetPlcState()`` que limpia el state
    relacionado con PLCs."""
    text = _read(STORE_JS)
    assert "export function resetPlcState" in text, (
        "store.js debe exportar resetPlcState() para que los "
        "componentes lo llamen cuando el backend reporta "
        "TIAConnectionError."
    )


def test_store_js_resets_all_plc_slots() -> None:
    """``resetPlcState()`` resetea ``selectedPlc``, ``plcBlocksCache``,
    ``plcs``, ``previewData`` y los slots de ``procesosSync``."""
    text = _read(STORE_JS)
    # Buscamos el cuerpo de la funcion (entre 'function resetPlcState'
    # y el cierre '}' antes de 'export default').
    start = text.find("export function resetPlcState")
    assert start != -1, "resetPlcState no encontrada en store.js"
    # Cogemos un tramo razonable (siguientes 800 chars).
    body = text[start:start + 1200]
    for slot in (
        "selectedPlc = \"\"",
        "plcBlocksCache = null",
        "plcs = []",
        "previewData = null",
        "procesosSync.preview = null",
        "procesosSync.applying = false",
    ):
        assert slot in body, (
            f"resetPlcState debe resetear el slot {slot!r}; "
            "el state stale del PLC debe quedar limpio tras TIA connection loss."
        )


def test_store_js_load_and_apply_plc_blocks_handles_tia_connection_error() -> None:
    """``loadAndApplyPlcBlocks`` (helper central del ShellTopbar +
    BloquesCacheView) detecta ``errorType === "TIAConnectionError"``
    y resetea el state."""
    text = _read(STORE_JS)
    # Localizar el cuerpo de loadAndApplyPlcBlocks
    start = text.find("export async function loadAndApplyPlcBlocks")
    assert start != -1
    body = text[start:start + 1800]
    assert 'errorType === "TIAConnectionError"' in body, (
        "loadAndApplyPlcBlocks debe detectar el errorType TIAConnectionError "
        "para resetear el state del PLC."
    )
    assert "resetPlcState()" in body, (
        "loadAndApplyPlcBlocks debe llamar a resetPlcState() cuando "
        "se detecta TIAConnectionError."
    )


# ── Componentes: importan resetPlcState y detectan errorType ────────


@pytest.mark.parametrize(
    "component_path,component_label",
    [
        (SHELL_TOPBAR_JS, "ShellTopbar"),
        (DISPOSITIVOS_JS, "Dispositivos"),
        (PROCESOS_SYNC_VIEW_JS, "ProcesosSyncView"),
    ],
)
def test_component_imports_reset_plc_state(
    component_path: Path, component_label: str
) -> None:
    """Los componentes que llaman a la API importan ``resetPlcState``."""
    text = _read(component_path)
    assert "resetPlcState" in text, (
        f"{component_label}.js debe importar resetPlcState de /js/store.js "
        "para limpiar el state cuando TIA no responde."
    )


@pytest.mark.parametrize(
    "component_path,component_label",
    [
        (SHELL_TOPBAR_JS, "ShellTopbar"),
        (DISPOSITIVOS_JS, "Dispositivos"),
        (PROCESOS_SYNC_VIEW_JS, "ProcesosSyncView"),
    ],
)
def test_component_detects_tia_connection_error(
    component_path: Path, component_label: str
) -> None:
    """Los componentes que llaman a la API detectan
    ``errorType === "TIAConnectionError"`` en la respuesta."""
    text = _read(component_path)
    assert 'errorType === "TIAConnectionError"' in text, (
        f"{component_label}.js debe comprobar r.errorType === "
        "'TIAConnectionError' para reaccionar al error de conexion TIA."
    )


def test_shell_topbar_resets_state_on_refresh_plcs_tia_down() -> None:
    """El handler ``handleRefreshPlcs`` del ShellTopbar resetea el
    state del PLC si ``apiFetchPlcs`` o ``apiFetchProjectInfo``
    reportan TIAConnectionError."""
    text = _read(SHELL_TOPBAR_JS)
    start = text.find("async function handleRefreshPlcs")
    assert start != -1
    body = text[start:start + 1500]
    assert "errorType === \"TIAConnectionError\"" in body, (
        "handleRefreshPlcs debe detectar TIAConnectionError en "
        "las respuestas de apiFetchPlcs/apiFetchProjectInfo."
    )
    assert "resetPlcState()" in body, (
        "handleRefreshPlcs debe llamar a resetPlcState() cuando "
        "TIA no responde para forzar re-seleccion del PLC."
    )
