"""Tests del blueprint tia_connection (Fase 4 / paso 4.4.2)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia.tia_loop import (
    SyncTIAClient)
from core.infrastructure.tia.tia_commands_catalog import register_all_commands
from core.composition.plc_engine import Engine
from core.runtime.sse.sse_event_bus_sync import EventBusSync
from interfaces.web_server.app_flask import create_app


@pytest.fixture
def client():
    tia = SyncTIAClient()
    register_all_commands(tia)  # necesario para dispatch('get_project_info') etc.
    engine = Engine()
    bus = EventBusSync()
    app = create_app(tia_client=tia, engine=engine, event_bus=bus)
    app.config["TESTING"] = True
    return app.test_client(), tia


def test_get_connection_disconnected_when_no_wrapper(client):
    c, _ = client
    resp = c.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["state"] == "disconnected"
    assert data["project"] is None
    assert data["plcs"] == []
    assert data["worker_alive"] is True
    assert data["pid"] is None


def test_get_connection_connected_with_plcs(client):
    c, tia = client
    portal = MagicMock()
    plc1 = MagicMock(); plc1.get_name.return_value = "PLC_1"
    plc1.get_property.return_value = "CPU 1518"
    plc2 = MagicMock(); plc2.get_name.return_value = "PLC_2"
    plc2.get_property.return_value = None
    project = MagicMock()
    project.get_plcs.return_value = [plc1, plc2]
    project.get_property.side_effect = lambda **kw: {
        "Name": "MiProyecto", "Path": "C:/x.apxx", "Version": "V18",
    }.get(kw.get("name"))
    portal.get_project.return_value = project
    tia.attach_wrapper(portal)

    resp = c.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["state"] == "connected"
    assert data["project"]["name"] == "MiProyecto"
    assert data["project"]["path"] == "C:/x.apxx"
    assert data["project"]["version"] == "V18"
    assert data["plcs"] == ["PLC_1", "PLC_2"]


def test_get_connection_handles_project_info_failure_gracefully(client):
    """Si TIA falla al leer get_project_info, state se preserva como 'connected'."""
    c, tia = client
    portal = MagicMock()
    project = MagicMock()
    project.get_plcs.return_value = []
    # get_project_info dispara excepcion.
    project.get_property.side_effect = RuntimeError("TIA closed")
    portal.get_project.return_value = project
    tia.attach_wrapper(portal)

    resp = c.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["state"] == "connected"
    assert data["project"] is None  # best-effort


def test_get_connection_handles_list_plcs_failure_gracefully(client):
    """Si TIA falla al listar PLCs, plcs=[] y state se preserva."""
    c, tia = client
    portal = MagicMock()
    project = MagicMock()
    # get_plcs lanza excepcion.
    project.get_plcs.side_effect = RuntimeError("COM transient")
    project.get_property.return_value = "MiProyecto"
    portal.get_project.return_value = project
    tia.attach_wrapper(portal)

    resp = c.get("/api/v1/tia/connection")
    data = resp.get_json()
    assert data["state"] == "connected"
    assert data["plcs"] == []


def test_post_connect_without_ts_returns_503(client):
    """Sin modulo siemens_tia_scripting attached, /connect retorna 503."""
    c, _ = client
    resp = c.post("/api/v1/tia/connect")
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["ok"] is False
    assert "siemens_tia_scripting" in data["error"]
    assert data["state"] == "disconnected"


def test_post_disconnect_clears_wrapper(client):
    """POST /disconnect hace attach_wrapper(None) -> wrapper cleared."""
    c, tia = client
    portal = MagicMock()
    tia.attach_wrapper(portal)
    assert tia.wrapper is portal

    resp = c.post("/api/v1/tia/disconnect")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["state"] == "disconnected"
    assert tia.wrapper is None


def test_endpoint_paths_use_api_v1_prefix():
    """Los endpoints viven bajo /api/v1/tia (Blueprint url_prefix).

    Sin prefix: cae a SPA fallback (``/tia/connection`` no es estático
    ni empieza por ``api/``, sin extension → devuelve ``index.html``
    para que Vue Router resuelva la ruta). Rutas ``/api/...`` que no
    existen devuelven 404.
    """
    tia = SyncTIAClient()
    register_all_commands(tia)
    app = create_app(tia_client=tia, engine=Engine(), event_bus=EventBusSync())
    client = app.test_client()
    resp = client.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    # Rutas /api/... inexistentes -> 404.
    resp2 = client.get("/api/v1/inexistente")
    assert resp2.status_code == 404
