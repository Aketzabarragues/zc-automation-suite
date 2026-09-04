"""Tests del router ``/api/v1/tia/connection``, ``/tia/connect`` y ``/tia/disconnect``.

Patrón TestClient + ``MagicMock(spec=TIAProcessGateway)`` (mismo que
``tests/test_project_info_endpoint.py``). Los 3 endpoints exponen
el estado del worker OT persistente del design doc
``_plan/12_worker_persistent_design.md`` §4.1:

  - GET  /api/v1/tia/connection  -> estado actual.
  - POST /api/v1/tia/connect     -> fuerza reconexion (PR 6 implementa
                                     ``gateway.reconnect()``; este PR solo
                                     conecta el endpoint).
  - POST /api/v1/tia/disconnect  -> desconecta (idem con ``disconnect()``).

Shape del GET (contrato con la SPA)::

    {
      "state": "connected" | "connecting" | "disconnected" | "error",
      "project": {"name", "path", "version"} | None,
      "plcs": [str, ...],
      "last_ping_ok_unix": float | None,
      "last_error": str | None
    }

Notas:
  * ``gateway.reconnect`` y ``gateway.disconnect`` NO existen todavía
    en la clase (los añade PR 6). Los tests que necesitan llamarlos
    los monkey-patchean como ``AsyncMock`` sobre el mock.
  * ``getattr(gateway, "_connection_state", "disconnected")`` en el
    router es defensivo: los atributos de estado del worker
    persistente solo se inicializan si el gateway se construyo con
    ``persistent=True`` (ver ``core/infrastructure/gateway.py``).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.application.progress_buffer import ProgressTracker
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.app import create_app


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_gateway() -> MagicMock:
    """Gateway ``MagicMock(spec=TIAProcessGateway)`` con defaults neutros.

    Los tests especificos sobreescriben lo que necesiten. Los metodos
    que el router invoca (``get_project_info``, ``get_plcs``,
    ``reconnect``, ``disconnect``) se anaden caso por caso.
    """
    g = MagicMock(spec=TIAProcessGateway)
    # Defaults sensatos: estado inicial ``disconnected`` y atributos
    # del worker persistente presentes. Asi el router nunca ve
    # ``AttributeError`` al hacer ``getattr``.
    g._connection_state = "disconnected"
    g._project_path = None
    g._last_ping_ok = None
    g._last_error = None
    return g


@pytest.fixture
def client(mock_gateway: MagicMock) -> TestClient:
    """TestClient con la app FastAPI montada y el gateway mockeado."""
    app = create_app(gateway=mock_gateway)
    app.state.progress_tracker = ProgressTracker()
    return TestClient(app)


# ── Test 1: GET /connection con state=connected → shape completo ────


def test_get_connection_connected_devuelve_shape_completo(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET /connection con state=connected expone todos los campos.

    El router enriquece con ``get_project_info`` y ``get_plcs`` solo
    si el state es ``"connected"``. Verifica el shape exacto del
    design doc §4.1.
    """
    mock_gateway._connection_state = "connected"
    mock_gateway._project_path = r"C:\ws\proj\proj.ap17"
    mock_gateway._last_ping_ok = 1234.5
    mock_gateway._last_error = None
    mock_gateway.get_project_info = AsyncMock(
        return_value={
            "name": "MiProyecto",
            "path": r"C:\ws\proj\proj.ap17",
            "version": "18.0",
        }
    )
    mock_gateway.get_plcs = AsyncMock(return_value=["PLC1", "PLC2"])

    resp = client.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    body = resp.json()

    # Shape exacto (sin campos extra)
    assert set(body.keys()) == {
        "state",
        "project",
        "plcs",
        "last_ping_ok_unix",
        "last_error",
    }
    assert body["state"] == "connected"
    assert body["project"] == {
        "name": "MiProyecto",
        "path": r"C:\ws\proj\proj.ap17",
        "version": "18.0",
    }
    assert body["plcs"] == ["PLC1", "PLC2"]
    assert body["last_ping_ok_unix"] == 1234.5
    assert body["last_error"] is None

    # El router consulta project_info y plcs porque el state es "connected"
    mock_gateway.get_project_info.assert_awaited_once()
    mock_gateway.get_plcs.assert_awaited_once()


# ── Test 2: POST /connect llama a gateway.reconnect() ───────────────


def test_post_connect_llama_gateway_reconnect(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /connect con reconnect mockeado responde ok=True y llama al metodo.

    ``reconnect()`` no existe en la clase todavia (PR 6 lo anade), asi
    que el test lo monkey-patchea como ``AsyncMock`` sobre el mock.
    """
    mock_gateway._connection_state = "connected"
    mock_gateway.reconnect = AsyncMock()  # PR 6 lo define en la clase

    resp = client.post("/api/v1/tia/connect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["state"] == "connected"
    mock_gateway.reconnect.assert_awaited_once()


# ── Test 3: POST /disconnect llama a gateway.disconnect() ────────────


def test_post_disconnect_llama_gateway_disconnect(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /disconnect con disconnect mockeado responde ok=True, state=disconnected.

    Idem que ``/connect``: ``disconnect()`` no existe en la clase
    todavia (PR 6 lo anade).
    """
    mock_gateway._connection_state = "disconnected"
    mock_gateway.disconnect = AsyncMock()  # PR 6 lo define en la clase

    resp = client.post("/api/v1/tia/disconnect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["state"] == "disconnected"
    mock_gateway.disconnect.assert_awaited_once()


# ── Test 4: GET /connection con state=disconnected → project=null ───


def test_get_connection_disconnected_no_consulta_gateway(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET /connection con state=disconnected NO llama a ``get_project_info`` ni ``get_plcs``.

    En estado no-conectado la cache del gateway puede estar stale
    (TIA cerrado, proyecto distinto) y forzar la lectura empeoraria
    la experiencia. El router devuelve ``project=None`` y ``plcs=[]``
    sin tocar el OT.
    """
    mock_gateway._connection_state = "disconnected"
    mock_gateway._project_path = None
    mock_gateway._last_ping_ok = None
    mock_gateway._last_error = "Last ping failed: TIA cerrado"
    # Anadimos los AsyncMock para poder verificar que NO se llaman
    mock_gateway.get_project_info = AsyncMock()
    mock_gateway.get_plcs = AsyncMock()

    resp = client.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    body = resp.json()

    assert body["state"] == "disconnected"
    assert body["project"] is None
    assert body["plcs"] == []
    assert body["last_ping_ok_unix"] is None
    assert body["last_error"] == "Last ping failed: TIA cerrado"

    # Red de seguridad: si el router llamara a estos metodos en estado
    # disconnected, el frontend sufriria latencia innecesaria y posibles
    # excepciones COM/RPC.
    mock_gateway.get_project_info.assert_not_called()
    mock_gateway.get_plcs.assert_not_called()


# ── Test 5: POST /connect con NotImplementedError → error legible ────


def test_post_connect_not_implemented_devuelve_error_legible(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /connect con reconnect que lanza ``NotImplementedError`` → 200 con ok=False.

    El router NO propaga la excepcion (eso daria 500 inutil al
    frontend). Devuelve un error legible indicando que la logica
    vive en PR 6.
    """
    mock_gateway._connection_state = "disconnected"
    mock_gateway.reconnect = AsyncMock(
        side_effect=NotImplementedError("reconnect() pendiente (PR 6)")
    )

    resp = client.post("/api/v1/tia/connect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["state"] == "disconnected"
    assert body["error"] == "reconnect() pendiente (PR 6)"
    mock_gateway.reconnect.assert_awaited_once()


# ── Test 6: GET /connection con get_project_info que lanza → degrada ──


def test_get_connection_get_project_info_falla_degrada_a_vacio(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET /connection con ``get_project_info`` que lanza excepcion → state preservado, project=null, plcs=[].

    El estado de conexion (``state``) es la verdad: si el router
    enriquece y falla, NO debe tumbar la respuesta. El frontend ve
    el state real y campos vacios hasta el siguiente polling.
    """
    mock_gateway._connection_state = "connected"
    mock_gateway._project_path = r"C:\ws\proj\proj.ap17"
    mock_gateway._last_ping_ok = 1234.5
    mock_gateway._last_error = None
    mock_gateway.get_project_info = AsyncMock(
        side_effect=RuntimeError("attach perdido durante la lectura")
    )
    mock_gateway.get_plcs = AsyncMock(
        side_effect=RuntimeError("attach perdido durante la lectura")
    )

    resp = client.get("/api/v1/tia/connection")
    # Estado 200: el router degrada en vez de explotar.
    assert resp.status_code == 200
    body = resp.json()
    # El state se preserva: NO bajamos a "disconnected" porque
    # ``get_project_info`` fallara — el state es la verdad y los
    # siguientes pings lo actualizaran si aplica.
    assert body["state"] == "connected"
    assert body["project"] is None
    assert body["plcs"] == []
    assert body["last_ping_ok_unix"] == 1234.5
    assert body["last_error"] is None
    # El router intento enriquecer y la excepcion se absorbio.
    mock_gateway.get_project_info.assert_awaited_once()
    mock_gateway.get_plcs.assert_awaited_once()
