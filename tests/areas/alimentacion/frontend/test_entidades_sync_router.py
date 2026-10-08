"""Tests del router Flask ``POST /api/v1/entidades/sincronizar``.

Cubre los 5 caminos:
  - body sin plc_name        -> 400
  - FB no registrado            -> 500
  - FB ya terminal/activo      -> 409
  - Happy path (terminal ok)   -> 200 con result
  - Timeout (>STEP_TIMEOUT_S)   -> 504
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from flask import Flask

from areas.alimentacion.frontend.entidades_router import bp


def _make_app_with_engine(engine: MagicMock | None = None) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(bp)
    if engine is not None:
        app.config["ENGINE"] = engine
    return app


def _make_engine_with_fb(fb: MagicMock | None) -> MagicMock:
    engine = MagicMock()
    engine.get_fb.return_value = fb
    return engine


# ---------------------------------------------------------------------------
# 400 / 500 / 409
# ---------------------------------------------------------------------------


def test_post_sincronizar_sin_plc_name_devuelve_400() -> None:
    app = _make_app_with_engine()
    with app.test_client() as client:
        resp = client.post("/api/v1/entidades/sincronizar", json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert "plc_name" in body["error"]


def test_post_sincronizar_sin_body_devuelve_400() -> None:
    app = _make_app_with_engine()
    with app.test_client() as client:
        resp = client.post("/api/v1/entidades/sincronizar")
    assert resp.status_code == 400


def test_post_sincronizar_sin_engine_devuelve_500() -> None:
    """Sin engine inyectado -> KeyError -> 500."""
    app = Flask(__name__)
    app.register_blueprint(bp)
    with app.test_client() as client:
        resp = client.post("/api/v1/entidades/sincronizar", json={"plc_name": "P"})
    assert resp.status_code == 500


def test_post_sincronizar_fb_no_registrado_devuelve_500() -> None:
    app = _make_app_with_engine(_make_engine_with_fb(None))
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/sincronizar", json={"plc_name": "ZC_PLC_STD"},
        )
    assert resp.status_code == 500
    body = resp.get_json()
    assert "no registrado" in body["error"]


def test_post_sincronizar_fb_ya_terminal_devuelve_409() -> None:
    fb = MagicMock()
    fb.start = AsyncMock(return_value=False)
    app = _make_app_with_engine(_make_engine_with_fb(fb))
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/sincronizar", json={"plc_name": "ZC_PLC_STD"},
        )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_post_sincronizar_happy_path_devuelve_200() -> None:
    """FB arranca, terminal, result con shape completa -> 200."""
    fb = MagicMock()
    fb.start = AsyncMock(return_value=True)
    fb.is_terminal.return_value = True
    fb.nStep = 11
    fb.n_error = -1
    fb.result = {
        "success":            True,
        "message":            "Sincronización completada",
        "operations":         17,
        "n_max_updates":      1,
        "post_sync_preview":  {"precondiciones_ok": True, "unified": {"todos": []}},
        "compile_ok":         True,
        "compile_error":      None,
        "comments_sync":      {"added": 13, "updated": 0, "unchanged": 0},
    }

    app = _make_app_with_engine(_make_engine_with_fb(fb))
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/sincronizar", json={"plc_name": "ZC_PLC_STD"},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["operations"] == 17
    assert body["n_max_updates"] == 1
    assert body["compile_ok"] is True
    assert body["post_sync_preview"]["precondiciones_ok"] is True


def test_post_sincronizar_fb_termina_en_error_devuelve_500() -> None:
    """Si el FB termina en error (nStep == n_error), devuelve 500."""
    fb = MagicMock()
    fb.start = AsyncMock(return_value=True)
    fb.is_terminal.return_value = True
    fb.nStep = 4
    fb.n_error = 4
    fb.error_msg = "Tx A (NMAX update) fallo: worker TIA no disponible"

    app = _make_app_with_engine(_make_engine_with_fb(fb))
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/sincronizar", json={"plc_name": "ZC_PLC_STD"},
        )
    assert resp.status_code == 500
    body = resp.get_json()
    assert "Tx A" in body["error"]


def test_post_sincronizar_timeout_devuelve_504() -> None:
    """FB no termina en el timeout -> 504 + cancel."""
    fb = MagicMock()
    fb.start = AsyncMock(return_value=True)
    # is_terminal nunca True -> fuerza timeout
    fb.is_terminal.return_value = False
    fb.STEP_TIMEOUT_S = 0.1  # acortar timeout para el test

    app = _make_app_with_engine(_make_engine_with_fb(fb))
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/sincronizar", json={"plc_name": "ZC_PLC_STD"},
        )
    assert resp.status_code == 504
    fb.cancel.assert_called_once()