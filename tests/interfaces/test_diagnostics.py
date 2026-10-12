"""Tests del blueprint diagnostics.

Tests basicos con stubs (no se importan LogBuffer / etc. reales — los
mocks son suficiente para verificar el wiring).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.web_server.app_flask import create_app


@pytest.fixture
def app_with_stubs():
    config_manager = MagicMock()

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
        config_manager=config_manager,
        log_buffer=log_buffer,
        progress_tracker=progress_tracker,
    )
    app.config["TESTING"] = True
    return app.test_client(), {
        "config_manager": config_manager,
        "log_buffer": log_buffer,
        "progress_tracker": progress_tracker,
    }


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
