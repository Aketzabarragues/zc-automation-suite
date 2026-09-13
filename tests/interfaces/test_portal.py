"""Tests del blueprint portal (Fase 4 / paso 4.4.6)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia_loop import SyncTIAClient, register_core_commands
from interfaces.web_server.app_flask import create_app


@pytest.fixture
def client_with_mocks():
    """Fixture con tia_client VACIO (sin core commands) para que cada test
    pueda registrar handlers propios sin chocar con los ya registrados.
    """
    tia = SyncTIAClient()
    log = MagicMock()
    app = create_app(tia_client=tia, log_buffer=log)
    app.config["TESTING"] = True
    return app.test_client(), tia


@pytest.fixture
def client_with_core_commands():
    """Fixture con core commands ya registrados (real handlers)."""
    tia = SyncTIAClient()
    register_core_commands(tia)
    log = MagicMock()
    app = create_app(tia_client=tia, log_buffer=log)
    app.config["TESTING"] = True
    return app.test_client(), tia


def test_attach_dispatches_attach_portal(client_with_mocks):
    c, tia = client_with_mocks
    tia.register_command(
        "attach_portal",
        lambda args, client: {"attached": True},
    )
    resp = c.post("/api/v1/portal/attach")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["result"] == {"attached": True}


def test_attach_returns_500_when_handler_fails(client_with_mocks):
    c, tia = client_with_mocks
    def fail(args, client):
        raise RuntimeError("portal closed")
    tia.register_command("attach_portal", fail)
    resp = c.post("/api/v1/portal/attach")
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["ok"] is False
    assert "portal closed" in data["error"]


def test_open_new_requires_project_file_path(client_with_mocks):
    c, _ = client_with_mocks
    resp = c.post("/api/v1/portal/open-new", json={})
    assert resp.status_code == 400


def test_open_new_dispatches_with_args(client_with_mocks):
    c, tia = client_with_mocks
    captured = []

    def capture(args, client):
        captured.append(args)
        return {"opened": True}

    tia.register_command("open_new_portal", capture)
    resp = c.post(
        "/api/v1/portal/open-new",
        json={"project_file_path": "C:/x.apxx"},
    )
    assert resp.status_code == 200
    assert captured == [{"project_file_path": "C:/x.apxx"}]


def test_open_new_returns_500_when_handler_fails(client_with_mocks):
    c, tia = client_with_mocks
    def fail(args, client):
        raise RuntimeError("TIA closed")
    tia.register_command("open_new_portal", fail)
    resp = c.post(
        "/api/v1/portal/open-new",
        json={"project_file_path": "C:/x.apxx"},
    )
    assert resp.status_code == 500
    assert "TIA closed" in resp.get_json()["error"]


def test_listar_plcs_returns_plcs_list(client_with_mocks):
    c, tia = client_with_mocks
    tia.register_command(
        "list_plcs",
        lambda args, client: {"plcs": [{"name": "PLC_1"}, {"name": "PLC_2"}]},
    )
    resp = c.get("/api/v1/plcs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert len(data["plcs"]) == 2
    assert data["plcs"][0]["name"] == "PLC_1"


def test_listar_plcs_best_effort_on_failure(client_with_mocks):
    """Si TIA no conectado, devuelve ok=False con HTTP 200 (no 500)."""
    c, tia = client_with_mocks
    def fail(args, client):
        raise RuntimeError("OpennessAccessException: TIA not open")
    tia.register_command("list_plcs", fail)
    resp = c.get("/api/v1/plcs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is False
    assert "Attach u Open New" in data["error"]


def test_get_project_info_returns_info(client_with_mocks):
    c, tia = client_with_mocks
    tia.register_command(
        "get_project_info",
        lambda args, client: {"name": "MiProyecto", "path": "C:/x.apxx"},
    )
    resp = c.get("/api/v1/portal/project-info")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["project_info"]["name"] == "MiProyecto"


def test_get_project_info_best_effort_on_failure(client_with_mocks):
    c, tia = client_with_mocks
    def fail(args, client):
        raise RuntimeError("no portal")
    tia.register_command("get_project_info", fail)
    resp = c.get("/api/v1/portal/project-info")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is False
    assert "Attach u Open New" in data["error"]
