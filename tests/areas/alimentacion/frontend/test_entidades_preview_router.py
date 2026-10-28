"""Tests del router Flask ``POST /api/v1/entidades/preview``.

El router ya no bloquea: encola el trabajo en el OB1 y responde 202
con el ``job_id``. El resultado llega al HMI por push (SSE ``fb_state``
y el slot ``preview_disp`` del AppCache que publica el FB al terminar).

Cubre:
  - body sin plc_name            -> 400
  - sin engine inyectado         -> 500
  - FB no registrado en el engine -> 500
  - FB con trabajo en curso       -> 409
  - fallo al encolar              -> 500
  - happy path                    -> 202 con job_id
"""
from __future__ import annotations

from unittest.mock import MagicMock

from flask import Flask

from areas.alimentacion.frontend.entidades_preview_router import bp
from core.composition.plc_engine import FBBusyError


def _make_app(engine: MagicMock | None = None) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(bp)
    if engine is not None:
        app.config["ENGINE"] = engine
    return app


def _make_engine(*, fb: object = "fb", submit: object = None) -> MagicMock:
    engine = MagicMock()
    engine.get_fb.return_value = fb if fb != "fb" else MagicMock()
    engine.submit.return_value = submit if submit is not None else "job-abc123"
    return engine


# ---------------------------------------------------------------------------
# 400
# ---------------------------------------------------------------------------


def test_post_sin_plc_name_devuelve_400() -> None:
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = client.post("/api/v1/entidades/preview", json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert "plc_name" in body["error"]


def test_post_sin_body_devuelve_400() -> None:
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = client.post("/api/v1/entidades/preview")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 500
# ---------------------------------------------------------------------------


def test_post_sin_engine_devuelve_500() -> None:
    """Sin ENGINE en el config -> KeyError -> 500."""
    app = Flask(__name__)
    app.register_blueprint(bp)
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/preview", json={"plc_name": "P"},
        )
    assert resp.status_code == 500


def test_post_fb_no_registrado_devuelve_500() -> None:
    app = _make_app(_make_engine(fb=None))
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/preview", json={"plc_name": "ZC_PLC_STD"},
        )
    assert resp.status_code == 500
    body = resp.get_json()
    assert "no registrado" in body["error"]


def test_post_si_submit_falla_devuelve_500() -> None:
    engine = _make_engine()
    engine.submit.side_effect = RuntimeError("boom")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/preview", json={"plc_name": "ZC_PLC_STD"},
        )
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "boom" in body["error"]


# ---------------------------------------------------------------------------
# 409
# ---------------------------------------------------------------------------


def test_post_con_fb_ocupado_devuelve_409() -> None:
    engine = _make_engine()
    engine.submit.side_effect = FBBusyError("FB ocupado: ya tiene trabajo")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/preview", json={"plc_name": "ZC_PLC_STD"},
        )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["ok"] is False
    assert "trabajo en curso" in body["error"]


# ---------------------------------------------------------------------------
# 202
# ---------------------------------------------------------------------------


def test_post_happy_path_devuelve_202_con_job_id() -> None:
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/preview", json={"plc_name": "ZC_PLC_STD"},
        )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["ok"] is True
    assert body["job_id"] == "job-abc123"
    # El trabajo se encola para el FB correcto, con el plc_name del body.
    engine.submit.assert_called_once_with(
        "entidades_generar_preview", plc_name="ZC_PLC_STD",
    )


def test_post_no_devuelve_el_result_del_fb() -> None:
    """El router no bloquea: no hay result en la respuesta, solo el job_id."""
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/entidades/preview", json={"plc_name": "ZC_PLC_STD"},
        )
    body = resp.get_json()
    assert "result" not in body
    assert "precondiciones_ok" not in body


def test_get_preview_status_sigue_siendo_placeholder() -> None:
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = client.get("/api/v1/entidades/preview/status")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
