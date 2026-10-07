"""Tests del router Flask ``POST /api/v1/entidades/preview``.

Cubre los 6 caminos del router:
  - body sin plc_name        -> 400
  - FB no registrado            -> 500
  - FB ya terminal/activo      -> 409
  - Happy path (terminal ok)   -> 200 con result
  - GET /preview/status        -> 200 ok=True
  - Timeout (>STEP_TIMEOUT_S)   -> 504
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from areas.alimentacion.frontend.entidades_preview_router import bp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_with_engine(engine: MagicMock | None = None) -> Flask:
    """Crea una Flask app con el blueprint registrado y un engine inyectado."""
    app = Flask(__name__)
    app.register_blueprint(bp)
    if engine is not None:
        app.config["ENGINE"] = engine
    return app


def _make_engine_with_fb(fb: MagicMock | None) -> MagicMock:
    """Crea un engine mock que devuelve ``fb`` para ``get_fb(...)``."""
    engine = MagicMock()
    engine.get_fb.return_value = fb
    return engine


# ---------------------------------------------------------------------------
# Tests de validacion (400)
# ---------------------------------------------------------------------------


def test_post_preview_sin_plc_name_devuelve_400() -> None:
    """Body sin ``plc_name`` -> 400."""
    app = _make_app_with_engine()
    with app.test_client() as client:
        resp = client.post("/api/v1/entidades/preview", json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert "plc_name" in body["error"]


def test_post_preview_sin_body_devuelve_400() -> None:
    """Sin body -> 400 (silent=True -> {} -> falta plc_name)."""
    app = _make_app_with_engine()
    with app.test_client() as client:
        resp = client.post("/api/v1/entidades/preview")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests del FB no registrado (500)
# ---------------------------------------------------------------------------


def test_post_preview_fb_no_registrado_devuelve_500() -> None:
    """``FB no registrado en el engine`` -> 500."""
    engine = _make_engine_with_fb(None)
    app = _make_app_with_engine(engine)

    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/preview",
            json={"plc_name": "PLC_S1500"},
        )

    assert resp.status_code == 500
    body = resp.get_json()
    assert "no registrado" in body["error"]


# ---------------------------------------------------------------------------
# Tests del GET /preview/status
# ---------------------------------------------------------------------------


def test_get_preview_status_devuelve_200() -> None:
    """GET /preview/status -> 200 ok=True (placeholder)."""
    app = _make_app_with_engine()
    with app.test_client() as client:
        resp = client.get("/api/v1/entidades/preview/status")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# ---------------------------------------------------------------------------
# Tests del happy path + 409 + 504
# ---------------------------------------------------------------------------


def _stub_fb_terminal_ok() -> dict:
    """Crea un result con shape completa (precondiciones_ok=True)."""
    return {
        "precondiciones_ok": True,
        "missing_blocks":    [],
        "db_name":           "DB6_ENT",
        "db_array_name":     "ENT",
        "tag_table":         "6_Entidades",
        "config_table":      "0_Config_Generales",
        "db_present":        True,
        "table_present":     True,
        "arrays":            {"ENT": []},
        "constants":         {"agregados": [], "eliminados": [],
                              "renombrados": [], "todos": []},
        "nmax":              {"current": {}, "desired": {}, "todos": [],
                               "summary": {"actualizar": 0, "sin_cambios": 0,
                                           "total": 0},
                               "nmax_error": None},
        "summary":           {"constants_agregados": 0,
                              "constants_eliminados": 0,
                              "constants_renombrados": 0,
                              "constants_sin_cambios": 0,
                              "comments_added": 0,
                              "comments_updated": 0,
                              "comments_unchanged": 0,
                              "total": 0},
        "warnings":          [],
    }


def test_post_preview_happy_path_devuelve_200_con_result() -> None:
    """Happy path: FB arranca, termina ok -> 200 con result."""
    from unittest.mock import AsyncMock

    fb = MagicMock()
    fb.STEP_TIMEOUT_S = 60.0
    fb.is_terminal.return_value = True
    fb.nStep = 5
    fb.n_error = 99
    fb.error_msg = None
    expected_result = _stub_fb_terminal_ok()
    fb.result = expected_result
    fb.start = AsyncMock(return_value=True)

    engine = _make_engine_with_fb(fb)
    app = _make_app_with_engine(engine)

    with app.test_client() as client, \
         patch(
             "asyncio.run",
             side_effect=lambda coro: fb.start.return_value,
         ):
        resp = client.post(
            "/api/v1/entidades/preview",
            json={"plc_name": "PLC_S1500"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["precondiciones_ok"] is True
    assert body["db_name"] == "DB6_ENT"


def test_post_preview_fb_ya_activo_devuelve_409() -> None:
    """``fb.start()`` devuelve False (FB ya terminal) -> 409."""
    from unittest.mock import AsyncMock

    fb = MagicMock()
    fb.start = AsyncMock(return_value=False)

    engine = _make_engine_with_fb(fb)
    app = _make_app_with_engine(engine)

    with app.test_client() as client, \
         patch(
             "asyncio.run",
             side_effect=lambda coro: fb.start.return_value,
         ):
        resp = client.post(
            "/api/v1/entidades/preview",
            json={"plc_name": "PLC_S1500"},
        )

    assert resp.status_code == 409
    body = resp.get_json()
    assert "ya activo o terminal" in body["error"]


def test_post_preview_fb_termina_en_error_devuelve_500() -> None:
    """``nStep == n_error`` -> 500 con mensaje."""
    from unittest.mock import AsyncMock

    fb = MagicMock()
    fb.STEP_TIMEOUT_S = 60.0
    fb.is_terminal.return_value = True
    fb.n_error = 99
    fb.nStep = 99
    fb.error_msg = "TIA no responde"
    fb.result = None
    fb.start = AsyncMock(return_value=True)

    engine = _make_engine_with_fb(fb)
    app = _make_app_with_engine(engine)

    with app.test_client() as client, \
         patch(
             "asyncio.run",
             side_effect=lambda coro: fb.start.return_value,
         ):
        resp = client.post(
            "/api/v1/entidades/preview",
            json={"plc_name": "PLC_S1500"},
        )

    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "TIA no responde"
    assert body["nStep"] == 99


def test_post_preview_timeout_devuelve_504() -> None:
    """Si el FB no termina en STEP_TIMEOUT_S -> 504."""
    from unittest.mock import AsyncMock

    fb = MagicMock()
    fb.STEP_TIMEOUT_S = 60.0
    fb.is_terminal.return_value = False
    fb.start = AsyncMock(return_value=True)

    engine = _make_engine_with_fb(fb)
    app = _make_app_with_engine(engine)

    with app.test_client() as client, \
         patch(
             "asyncio.run",
             side_effect=lambda coro: fb.start.return_value,
         ), \
         patch(
             "areas.alimentacion.frontend.entidades_preview_router.time.sleep",
         ):
        resp = client.post(
            "/api/v1/entidades/preview",
            json={"plc_name": "PLC_S1500"},
        )

    assert resp.status_code == 504
    body = resp.get_json()
    assert "timeout" in body["error"]
    fb.cancel.assert_called_once()
