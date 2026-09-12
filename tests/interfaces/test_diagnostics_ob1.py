"""Tests del blueprint diagnostics_ob1 (Fase 4 / paso 4.4.3).

Tests basicos con stubs (no se importan AppState / LogBuffer / etc.
reales — los mocks son suficiente para verificar el wiring).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from interfaces.web_server.app_flask import create_app


@pytest.fixture
def app_with_stubs():
    app_state = MagicMock()
    app_state.dimensiones = None
    app_state.get_devices.return_value = []
    app_state.excel_cache = None

    config_manager = MagicMock()
    config_manager.list_hw_types_active.return_value = []
    config_manager.get_excel_target_for.return_value = None

    log_buffer = MagicMock()
    log_buffer.snapshot.return_value = []
    log_buffer.clear = MagicMock()
    log_buffer.success = MagicMock()
    log_buffer.warning = MagicMock()
    log_buffer.error = MagicMock()
    log_buffer.info = MagicMock()

    progress_tracker = MagicMock()
    progress_tracker.snapshot.return_value = MagicMock(to_dict=MagicMock(return_value={}))
    progress_tracker.clear = MagicMock()

    app = create_app(
        app_state=app_state,
        config_manager=config_manager,
        log_buffer=log_buffer,
        progress_tracker=progress_tracker,
    )
    app.config["TESTING"] = True
    return app.test_client(), {
        "app_state": app_state,
        "config_manager": config_manager,
        "log_buffer": log_buffer,
        "progress_tracker": progress_tracker,
    }


def test_state_dispositivos_returns_ok_with_empty_payload(app_with_stubs):
    c, stubs = app_with_stubs
    resp = c.get("/api/v1/state/dispositivos")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["dimensiones"] == {}
    assert data["dispositivos"] == {}
    assert data["software_parsers_implemented"] is False
    assert data["procesos"] == []


def test_state_dispositivos_iterates_active_hw_types(app_with_stubs):
    c, stubs = app_with_stubs
    cm = stubs["config_manager"]
    cm.list_hw_types_active.return_value = ["ed", "ea"]
    cm.get_excel_target_for.side_effect = lambda hw: {
        "ed": {"canonical": "DispED"},
        "ea": {"canonical": "DispEA"},
    }.get(hw)

    state = stubs["app_state"]
    state.get_devices.return_value = []

    resp = c.get("/api/v1/state/dispositivos")
    data = resp.get_json()
    assert "DispED" in data["dispositivos"]
    assert "DispEA" in data["dispositivos"]


def test_state_dispositivos_skips_hw_without_canonical(app_with_stubs):
    c, stubs = app_with_stubs
    cm = stubs["config_manager"]
    cm.list_hw_types_active.return_value = ["good", "bad"]
    cm.get_excel_target_for.side_effect = lambda hw: {
        "good": {"canonical": "DispOK"},
        "bad": {"canonical": ""},
    }.get(hw)

    resp = c.get("/api/v1/state/dispositivos")
    data = resp.get_json()
    assert "DispOK" in data["dispositivos"]
    assert "" not in data["dispositivos"]


def test_get_logs_returns_buffer_snapshot(app_with_stubs):
    c, stubs = app_with_stubs
    stubs["log_buffer"].snapshot.return_value = [
        {"level": "info", "message": "test"}
    ]
    resp = c.get("/api/v1/logs")
    assert resp.status_code == 200
    assert resp.get_json() == {"logs": [{"level": "info", "message": "test"}]}


def test_post_log_clear_clears_buffer(app_with_stubs):
    c, stubs = app_with_stubs
    resp = c.post("/api/v1/logs/clear")
    assert resp.status_code == 200
    assert resp.get_json() == {"cleared": True}
    stubs["log_buffer"].clear.assert_called_once()


def test_post_log_info_calls_info_method(app_with_stubs):
    c, stubs = app_with_stubs
    resp = c.post("/api/v1/logs", json={"message": "hello", "level": "info"})
    assert resp.status_code == 201
    stubs["log_buffer"].info.assert_called_once_with("hello")


def test_post_log_warning_calls_warning_method(app_with_stubs):
    c, stubs = app_with_stubs
    resp = c.post("/api/v1/logs", json={"message": "warn", "level": "warning"})
    assert resp.status_code == 201
    stubs["log_buffer"].warning.assert_called_once_with("warn")


def test_post_log_error_calls_error_method(app_with_stubs):
    c, stubs = app_with_stubs
    resp = c.post("/api/v1/logs", json={"message": "boom", "level": "error"})
    assert resp.status_code == 201
    stubs["log_buffer"].error.assert_called_once_with("boom")


def test_post_log_success_calls_success_method(app_with_stubs):
    c, stubs = app_with_stubs
    resp = c.post("/api/v1/logs", json={"message": "ok", "level": "success"})
    assert resp.status_code == 201
    stubs["log_buffer"].success.assert_called_once_with("ok")


def test_post_log_rejects_empty_message(app_with_stubs):
    c, _ = app_with_stubs
    resp = c.post("/api/v1/logs", json={"message": ""})
    assert resp.status_code == 400


def test_post_log_rejects_oversized_message(app_with_stubs):
    c, _ = app_with_stubs
    resp = c.post("/api/v1/logs", json={"message": "x" * 2001})
    assert resp.status_code == 400


def test_post_log_rejects_invalid_level(app_with_stubs):
    c, _ = app_with_stubs
    resp = c.post("/api/v1/logs", json={"message": "hi", "level": "debug"})
    assert resp.status_code == 400


def test_get_progress_returns_snapshot(app_with_stubs):
    c, stubs = app_with_stubs
    stubs["progress_tracker"].snapshot.return_value.to_dict.return_value = {
        "active": False,
    }
    resp = c.get("/api/v1/progress/current")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "progress": {"active": False}}


def test_post_progress_clear_resets_tracker(app_with_stubs):
    c, stubs = app_with_stubs
    resp = c.post("/api/v1/progress/clear")
    assert resp.status_code == 200
    assert resp.get_json() == {"cleared": True}
    stubs["progress_tracker"].clear.assert_called_once()
