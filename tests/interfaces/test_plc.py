"""Tests del blueprint plc."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.composition.plc_engine import Engine
from core.composition.plc_function_base import FunctionBase
from core.web_server.app_flask import create_app


class _CountingFB(FunctionBase):
    """FB que cuenta las ejecuciones para verificar el wiring."""

    def __init__(self, nombre: str = "test_fb"):
        super().__init__(nombre=nombre, titulo="test fb", steps=[])
        self.start_count = 0
        self.execute_count = 0

    async def start(self, **_kwargs) -> bool:
        self.start_count += 1
        self.nStep = 10  # n_idle -> 10 (activo)
        return True

    async def tick(self) -> None:
        pass

    def execute(self, **params):
        self.execute_count += 1
        self.nStep = 10
        return {"ok": True}


@pytest.fixture
def client():
    engine = Engine()
    fb = _CountingFB(nombre="subir_excel")
    engine.register_fb("subir_excel", fb)
    app = create_app(engine=engine)
    app.config["TESTING"] = True
    return app.test_client(), engine, fb


def test_get_status_returns_fb_state(client):
    c, _, _ = client
    resp = c.get("/api/v1/plc/fb/subir_excel/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "subir_excel"
    assert data["nStep"] == 0  # n_idle
    assert data["is_terminal"] is True
    assert data["error_msg"] is None


def test_get_status_404_for_unknown_fb(client):
    c, _, _ = client
    resp = c.get("/api/v1/plc/fb/no_existe/status")
    assert resp.status_code == 404
    assert "no registrado" in resp.get_json()["error"]


def test_start_fb_encola_el_trabajo(client):
    """POST /start encola el trabajo en el OB1 y devuelve 202 + job_id."""
    c, engine, fb = client
    resp = c.post(
        "/api/v1/plc/fb/subir_excel/start",
        json={"params": {"plc_name": "PLC_1", "xlsx_path": "C:/x.xlsx"}},
    )
    assert resp.status_code == 202
    data = resp.get_json()
    assert data["ok"] is True
    job_id = data["job_id"]
    assert job_id

    # El trabajo quedo encolado con sus params, para el FB correcto.
    job = engine.get_job(job_id)
    assert job is not None
    assert job.fb_name == "subir_excel"
    assert job.params == {"plc_name": "PLC_1", "xlsx_path": "C:/x.xlsx"}
    assert job.status == "queued"
    # El router no arranca el FB: eso es cosa del dispatcher.
    assert fb.start_count == 0
    assert fb.execute_count == 0


def test_start_fb_404_for_unknown_fb(client):
    c, _, _ = client
    resp = c.post(
        "/api/v1/plc/fb/no_existe/start",
        json={"params": {}},
    )
    assert resp.status_code == 404


def test_disconnect_fb_removes_from_engine(client):
    c, engine, _ = client
    assert "subir_excel" in engine.registered_fb_names()
    resp = c.post("/api/v1/plc/fb/subir_excel/disconnect")
    assert resp.status_code == 204
    assert "subir_excel" not in engine.registered_fb_names()


def test_disconnect_fb_404_for_unknown_fb(client):
    c, _, _ = client
    resp = c.post("/api/v1/plc/fb/no_existe/disconnect")
    assert resp.status_code == 404


def test_status_after_disconnect_returns_404(client):
    """Tras disconnect, el FB ya no esta; /status da 404."""
    c, _, _ = client
    c.post("/api/v1/plc/fb/subir_excel/disconnect")
    resp = c.get("/api/v1/plc/fb/subir_excel/status")
    assert resp.status_code == 404
