"""Tests del indicador de estado del worker OT (sept-2026).

Cubre los 3 niveles del indicador ``worker_alive``:

  1. ``core.infrastructure.gateway.TIAProcessGateway.is_worker_alive()``
     retorna ``True`` si el subproceso del worker persistente esta
     vivo (``_worker_proc is not None and returncode is None``),
     ``False`` en cualquier otro caso (incluido modo 1-shot / MCP).
  2. El router ``GET /api/v1/tia/connection`` expone el campo
     ``worker_alive`` en la respuesta (con ``getattr`` defensivo:
     si el gateway no tiene el metodo, retorna ``False``).
  3. El componente ``WorkerStatusIndicator.js`` lee reactivamente
     ``store.tiaConnection.worker_alive`` y renderiza un circulo
     verde (vivo) o gris (muerto).

Por que es ortogonal al ``TiaConnectionIndicator``: el subproceso
del worker puede estar VIVO pero DESCONECTADO de TIA (3 fallos
del heartbeat). El operario necesita ver ambos estados por
separado: "el worker esta en marcha?" vs "estoy conectado a TIA?".
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


# ── 1. Gateway: is_worker_alive() ──────────────────────────────────


class TestGatewayIsWorkerAlive:
    """``is_worker_alive()`` retorna ``True`` solo si el subproceso
    del worker persistente esta vivo."""

    def test_persistent_false_retorna_false(self) -> None:
        from core.infrastructure.gateway import TIAProcessGateway

        g = TIAProcessGateway(persistent=False)
        assert g.is_worker_alive() is False, (
            "En modo 1-shot (MCP) NO hay worker persistente, asi que "
            "is_worker_alive() siempre debe ser False."
        )

    def test_persistent_true_sin_proc_retorna_false(self) -> None:
        from core.infrastructure.gateway import TIAProcessGateway

        g = TIAProcessGateway(persistent=True)
        # Estado inicial: _worker_proc es None (no se ha hecho lazy start).
        assert g.is_worker_alive() is False

    def test_persistent_true_proc_vivo_retorna_true(self) -> None:
        from core.infrastructure.gateway import TIAProcessGateway

        g = TIAProcessGateway(persistent=True)
        # Simulamos un subproceso vivo: ``returncode is None``.
        fake_proc = MagicMock()
        fake_proc.returncode = None
        g._worker_proc = fake_proc
        assert g.is_worker_alive() is True

    def test_persistent_true_proc_muerto_retorna_false(self) -> None:
        from core.infrastructure.gateway import TIAProcessGateway

        g = TIAProcessGateway(persistent=True)
        # ``returncode != None`` significa que el subproceso termino.
        fake_proc = MagicMock()
        fake_proc.returncode = 1  # cualquier valor != None cuenta como muerto
        g._worker_proc = fake_proc
        assert g.is_worker_alive() is False

    def test_no_explotar_si_proc_es_none(self) -> None:
        """Defensa: aunque el atributo ``_worker_proc`` no exista
        (gateway muy viejo o modo 1-shot), no debe explotar."""
        from core.infrastructure.gateway import TIAProcessGateway

        g = TIAProcessGateway(persistent=True)
        # Borramos el atributo para simular un gateway legacy.
        del g._worker_proc
        assert g.is_worker_alive() is False


# ── 2. Router: GET /connection expone worker_alive ──────────────────


class TestRouterWorkerAlive:
    """El router ``GET /api/v1/tia/connection`` expone el campo
    ``worker_alive`` con ``getattr`` defensivo (si el gateway no
    tiene ``is_worker_alive``, retorna ``False`` en vez de explotar)."""

    def test_get_connection_expone_worker_alive_true(
        self, client, mock_gateway: MagicMock
    ) -> None:
        """Si el gateway tiene ``is_worker_alive()`` que retorna ``True``,
        la respuesta del GET incluye ``worker_alive: true``."""
        mock_gateway._connection_state = "disconnected"
        mock_gateway._project_path = None
        mock_gateway._last_ping_ok = None
        mock_gateway._last_error = None
        mock_gateway.is_worker_alive = MagicMock(return_value=True)

        resp = client.get("/api/v1/tia/connection")
        assert resp.status_code == 200
        body = resp.json()
        assert "worker_alive" in body, (
            "El router debe exponer el campo 'worker_alive' en la respuesta."
        )
        assert body["worker_alive"] is True

    def test_get_connection_expone_worker_alive_false(
        self, client, mock_gateway: MagicMock
    ) -> None:
        """Si el gateway tiene ``is_worker_alive()`` que retorna ``False``,
        la respuesta incluye ``worker_alive: false``."""
        mock_gateway._connection_state = "connected"
        mock_gateway._project_path = r"C:\ws\proj\proj.ap17"
        mock_gateway._last_ping_ok = 1000.0
        mock_gateway._last_error = None
        mock_gateway.is_worker_alive = MagicMock(return_value=False)
        mock_gateway.get_project_info = AsyncMock(
            return_value={
                "name": "P",
                "path": r"C:\ws\proj\proj.ap17",
                "version": "18",
            }
        )
        mock_gateway.get_plcs = AsyncMock(return_value=[])

        resp = client.get("/api/v1/tia/connection")
        body = resp.json()
        assert body["worker_alive"] is False

    def test_get_connection_sin_is_worker_alive_no_explota(
        self, client, mock_gateway: MagicMock
    ) -> None:
        """Si el gateway NO tiene ``is_worker_alive`` (gateway muy viejo
        o modo 1-shot), el router usa ``getattr(..., lambda: False)()``
        y retorna ``worker_alive: false`` sin propagar AttributeError."""
        mock_gateway._connection_state = "disconnected"
        mock_gateway._project_path = None
        mock_gateway._last_ping_ok = None
        mock_gateway._last_error = None
        # Borramos el metodo para simular un gateway legacy.
        del mock_gateway.is_worker_alive

        resp = client.get("/api/v1/tia/connection")
        assert resp.status_code == 200
        body = resp.json()
        assert body["worker_alive"] is False


# ── 3. Frontend: WorkerStatusIndicator.js ───────────────────────────


WORKER_INDICATOR_JS = (
    REPO_ROOT
    / "interfaces"
    / "web_server"
    / "static"
    / "js"
    / "components"
    / "WorkerStatusIndicator.js"
)


def _read(path: Path) -> str:
    assert path.exists(), f"Missing file: {path}"
    return path.read_text(encoding="utf-8")


def test_indicator_file_exists_and_exports_default() -> None:
    """El archivo existe, exporta un default object con ``name``,
    ``setup`` y ``template`` (mismo patron que el resto de
    componentes Vue 3 ESM)."""
    text = _read(WORKER_INDICATOR_JS)
    assert "export default {" in text
    assert 'name: "WorkerStatusIndicator"' in text
    assert "setup" in text
    assert "template:" in text


def test_indicator_returns_alive_colorClass_tooltip_from_setup() -> None:
    """REGLA Vue 3 sin build step: el template solo ve lo que
    ``setup()`` retorna. El componente expone ``alive``, ``colorClass``
    y ``tooltip`` para que el template los use en ``:class`` y ``:title``."""
    text = _read(WORKER_INDICATOR_JS)
    assert (
        "return { alive, colorClass, tooltip" in text
        or "return { alive, colorClass, tooltip," in text
    ), "El setup() debe retornar alive, colorClass y tooltip."


def test_indicator_colorClass_uses_green_when_alive() -> None:
    """``alive.value === true`` → clase ``bg-green-500``."""
    text = _read(WORKER_INDICATOR_JS)
    # Buscamos el computed colorClass.
    assert 'alive.value ? "bg-green-500"' in text, (
        "Cuando alive=true, colorClass debe ser 'bg-green-500'."
    )
    assert '"bg-gray-400"' in text, (
        "Cuando alive=false, colorClass debe ser 'bg-gray-400'."
    )


def test_indicator_tooltip_changes_with_state() -> None:
    """El tooltip refleja el estado: "en marcha" si vivo, "detenido" si muerto."""
    text = _read(WORKER_INDICATOR_JS)
    assert "en marcha" in text, "Tooltip para alive=true debe decir 'en marcha'."
    assert "detenido" in text, "Tooltip para alive=false debe decir 'detenido'."


def test_indicator_has_data_testid() -> None:
    """El elemento expone ``data-testid="worker-status-indicator'``
    para facilitar QA y tests E2E."""
    text = _read(WORKER_INDICATOR_JS)
    assert 'data-testid="worker-status-indicator"' in text


def test_indicator_js_is_syntactically_valid() -> None:
    """Sanity check con ``node --check``."""
    if not WORKER_INDICATOR_JS.exists():
        pytest.skip("Componente no encontrado")
    try:
        result = subprocess.run(
            ["node", "--check", str(WORKER_INDICATOR_JS)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        pytest.skip("node no disponible")
    if result.returncode != 0:
        pytest.fail(
            f"WorkerStatusIndicator.js no parsea con node --check:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ── 4. ShellTopbar: importa y renderiza el indicador ───────────────


def test_shelltopbar_imports_worker_indicator() -> None:
    """El ``ShellTopbar.js`` importa y registra el
    ``WorkerStatusIndicator`` en ``components``, y lo renderiza
    en el bloque PLC del topbar."""
    shelltopbar = REPO_ROOT / "interfaces" / "web_server" / "static" / "js" / "components" / "ShellTopbar.js"
    text = _read(shelltopbar)
    assert (
        'import WorkerStatusIndicator from "./WorkerStatusIndicator.js"' in text
    ), "ShellTopbar debe importar WorkerStatusIndicator."
    assert (
        "WorkerStatusIndicator," in text
    ), "ShellTopbar debe registrar WorkerStatusIndicator en components."
    assert (
        "<WorkerStatusIndicator" in text
    ), "ShellTopbar debe renderizar <WorkerStatusIndicator /> en el template."
