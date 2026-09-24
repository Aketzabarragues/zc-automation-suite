"""Tests del blueprint tia_connection."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia.tia_loop import (
    STATE_CONNECTED,
    SyncTIAClient)
from core.infrastructure.tia.tia_commands_catalog import register_all_commands
from core.composition.plc_engine import Engine
from core.runtime.sse.sse_event_bus_sync import EventBusSync
from core.web_server.app_flask import create_app


@pytest.fixture
def client():
    tia = SyncTIAClient()
    register_all_commands(tia)  # necesario para dispatch('get_project_info') etc.
    engine = Engine()
    bus = EventBusSync()
    app = create_app(tia_client=tia, engine=engine, event_bus=bus)
    app.config["TESTING"] = True
    return app.test_client(), tia


def test_get_connection_idle_when_no_wrapper(client):
    """Sin portal attached, /connection devuelve state='idle' (modelo sept-2026)."""
    c, _ = client
    resp = c.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["state"] == "idle"
    assert data["project"] is None
    assert data["plcs"] == []
    assert data["worker_alive"] is True
    assert data["pid"] is None


def test_get_connection_connected_with_plcs(client, monkeypatch):
    """Con portal attached + state=CONNECTED, /connection expone proyecto + PLCs.

    Mockeamos ``submit_and_wait`` para invocar directamente las
    operaciones contra el portal mockeado (el tia-loop no esta
    corriendo en estos tests; solo verificamos el wiring del
    endpoint).
    """
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
    tia._set_state(STATE_CONNECTED)

    def fake_submit_and_wait(command, **_kwargs):
        if command == "get_project_info":
            try:
                project_obj = tia.wrapper.get_project()
                return {
                    "ok": True,
                    "result": {
                        "name": project_obj.get_property(name="Name"),
                        "path": project_obj.get_property(name="Path"),
                        "version": project_obj.get_property(name="Version"),
                    },
                }
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}
        if command == "list_plcs":
            try:
                plc_list = tia.wrapper.get_project().get_plcs()
                return {
                    "ok": True,
                    "result": {
                        "plcs": [{"name": p.get_name()} for p in plc_list],
                    },
                }
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": f"unknown command: {command}"}

    monkeypatch.setattr(tia, "submit_and_wait", fake_submit_and_wait)

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
    tia._set_state(STATE_CONNECTED)

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
    tia._set_state(STATE_CONNECTED)

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
    assert data["state"] == "idle"


def test_post_disconnect_clears_wrapper(client, monkeypatch):
    """POST /disconnect hace attach_wrapper(None) -> wrapper cleared.

    Mockeamos ``submit_and_wait`` para que invoque directamente
    ``detach_portal`` sin pasar por la cola del tia-loop (el loop no
    esta corriendo en estos tests, solo verificamos el wiring del
    endpoint).
    """
    c, tia = client
    portal = MagicMock()
    tia.attach_wrapper(portal)
    assert tia.wrapper is portal

    def fake_submit_and_wait(command, **_kwargs):
        if command == "detach_portal":
            tia._wrapper = None
            tia._set_state("idle")
            return {"ok": True, "result": {}}
        return {"ok": False, "error": f"unknown command: {command}"}

    monkeypatch.setattr(tia, "submit_and_wait", fake_submit_and_wait)

    resp = c.post("/api/v1/tia/disconnect")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["state"] == "idle"
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
