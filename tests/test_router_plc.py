"""Tests del router PLC FBs (``/api/v1/plc/fb/...``).

Fase 2, paso 2.2.1.  Cubren:
  - Happy path POST /start: arranca el FB con los params del body,
    devuelve 200 con ``started=True`` y ``nStep=10``.
  - 404 POST /start si el FB no está registrado.
  - POST /start idempotente: si el FB ya está activo, devuelve
    ``started=False`` (la base de FunctionBase es idempotente).
  - POST /disconnect: 204 si el FB estaba registrado, 404 si no.
  - GET /status: 200 con nStep, is_terminal, error_msg, result.
  - GET /status 404 si el FB no está registrado.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.plc.engine import Engine
from core.plc.function_base import FunctionBase
from interfaces.web_server.dependencies import get_engine
from interfaces.web_server.routers.plc import router as plc_router


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_fb() -> MagicMock:
    """FB mock con ``start`` async, ``is_terminal``, ``error_msg``,
    ``result``, ``nStep``."""
    fb = MagicMock(spec=FunctionBase)
    fb.start = AsyncMock(return_value=True)
    fb.nStep = 10
    fb.is_terminal = MagicMock(return_value=False)
    fb.error_msg = None
    fb.result = None
    return fb


@pytest.fixture
def engine_with_fb(mock_fb: MagicMock) -> Engine:
    """Engine real con un FB registrado bajo ``SubirExcel``."""
    engine = Engine(tick_period_s=0.01)
    engine.register_fb("SubirExcel", mock_fb)
    return engine


@pytest.fixture
def client(engine_with_fb: Engine) -> TestClient:
    """TestClient con la app mínima y el engine inyectado."""
    app = FastAPI()
    app.state.engine = engine_with_fb
    app.include_router(plc_router)

    # Override del dependency injector para que use nuestro engine.
    # Alternativa: leer de app.state, que es lo que hace get_engine.
    # Lo dejo override para mayor claridad.
    app.dependency_overrides[get_engine] = lambda: engine_with_fb
    return TestClient(app)


# ── Tests ────────────────────────────────────────────────────────────


def test_router_plc_start_happy_path(client: TestClient, mock_fb: MagicMock) -> None:
    """POST /start con body params → arranca el FB."""
    resp = client.post(
        "/api/v1/plc/fb/SubirExcel/start",
        json={"params": {"plc_name": "S7-1500", "xlsx_path": "/fake.xlsx"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"started": True, "nStep": 10}
    mock_fb.start.assert_awaited_once_with(
        plc_name="S7-1500", xlsx_path="/fake.xlsx"
    )


def test_router_plc_start_404_if_fb_not_registered(
    client: TestClient,
) -> None:
    """POST /start con FB no registrado → 404."""
    resp = client.post(
        "/api/v1/plc/fb/NoExiste/start",
        json={"params": {}},
    )
    assert resp.status_code == 404
    assert "NoExiste" in resp.json()["detail"]


def test_router_plc_start_idempotent(
    client: TestClient, mock_fb: MagicMock
) -> None:
    """POST /start cuando el FB ya está activo → started=False."""
    mock_fb.start = AsyncMock(return_value=False)  # ya estaba activo
    resp = client.post(
        "/api/v1/plc/fb/SubirExcel/start",
        json={"params": {"xlsx_path": "/fake.xlsx"}},
    )
    assert resp.status_code == 200
    assert resp.json()["started"] is False
    mock_fb.start.assert_awaited_once()


def test_router_plc_disconnect_happy_path(
    client: TestClient, engine_with_fb: Engine
) -> None:
    """POST /disconnect → 204, el FB deja de estar en el engine."""
    assert "SubirExcel" in engine_with_fb.registered_fb_names()
    resp = client.post("/api/v1/plc/fb/SubirExcel/disconnect")
    assert resp.status_code == 204
    assert "SubirExcel" not in engine_with_fb.registered_fb_names()


def test_router_plc_disconnect_404_if_not_registered(
    client: TestClient,
) -> None:
    """POST /disconnect con FB no registrado → 404."""
    resp = client.post("/api/v1/plc/fb/NoExiste/disconnect")
    assert resp.status_code == 404
    assert "NoExiste" in resp.json()["detail"]


def test_router_plc_status_happy_path(
    client: TestClient, mock_fb: MagicMock
) -> None:
    """GET /status → 200 con la info del FB."""
    mock_fb.nStep = 20
    mock_fb.is_terminal = MagicMock(return_value=False)
    mock_fb.error_msg = None
    mock_fb.result = {"key": "value"}

    resp = client.get("/api/v1/plc/fb/SubirExcel/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "name": "SubirExcel",
        "nStep": 20,
        "is_terminal": False,
        "error_msg": None,
        "result": {"key": "value"},
    }


def test_router_plc_status_404_if_not_registered(client: TestClient) -> None:
    """GET /status con FB no registrado → 404."""
    resp = client.get("/api/v1/plc/fb/NoExiste/status")
    assert resp.status_code == 404


def test_router_plc_status_reflects_error_state(
    client: TestClient, mock_fb: MagicMock
) -> None:
    """GET /status cuando el FB está en n_error → refleja el estado."""
    mock_fb.nStep = 98  # n_error
    mock_fb.is_terminal = MagicMock(return_value=True)
    mock_fb.error_msg = "RuntimeError: TIA Portal no responde"

    resp = client.get("/api/v1/plc/fb/SubirExcel/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["nStep"] == 98
    assert body["is_terminal"] is True
    assert "TIA Portal no responde" in body["error_msg"]
