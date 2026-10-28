"""Tests del router Flask ``POST /api/v1/procesos/sync/{preview,commit}``.

El router ya no bloquea: encola el trabajo en el OB1 y responde 202
con el ``job_id``. El resultado llega al HMI por push (SSE ``fb_state``
y los slots del AppCache que publica el FB al terminar).

Cubre (para los 2 endpoints):
  - body sin los params requeridos -> 400
  - sin engine inyectado           -> 500
  - FB no registrado en el engine  -> 500
  - FB con trabajo en curso        -> 409
  - fallo al encolar               -> 500
  - happy path                     -> 202 con job_id
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

from areas.alimentacion.frontend.proc_sync_router import bp
from core.composition.plc_engine import FBBusyError

# (url, nombre del FB encolado, body valido)
ENDPOINTS = [
    ("/api/v1/procesos/sync/preview", "proc_db_generar_preview",
     {"plc_name": "ZC_PLC_STD", "proc_uid": 100}),
    ("/api/v1/procesos/sync/commit", "proc_db_sincronizar",
     {"plc_name": "ZC_PLC_STD", "proc_uid": 100}),
]

IDS = ["preview", "commit"]


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


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_post_sin_params_devuelve_400(url, _fb_name, body) -> None:
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = client.post(url, json={})
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "plc_name" in payload["error"]


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_post_sin_proc_uid_devuelve_400(url, _fb_name, body) -> None:
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = client.post(url, json={"plc_name": "ZC_PLC_STD"})
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "proc_uid" in payload["error"]


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_post_sin_body_devuelve_400(url, _fb_name, body) -> None:
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = client.post(url)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 500
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_post_sin_engine_devuelve_500(url, _fb_name, body) -> None:
    """Sin ENGINE en el config -> KeyError -> 500."""
    app = Flask(__name__)
    app.register_blueprint(bp)
    with app.test_client() as client:
        resp = client.post(url, json=body)
    assert resp.status_code == 500


@pytest.mark.parametrize("url,fb_name,body", ENDPOINTS, ids=IDS)
def test_post_fb_no_registrado_devuelve_500(url, fb_name, body) -> None:
    app = _make_app(_make_engine(fb=None))
    with app.test_client() as client:
        resp = client.post(url, json=body)
    assert resp.status_code == 500
    payload = resp.get_json()
    assert "no registrado" in payload["error"]
    assert fb_name in payload["error"]


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_post_si_submit_falla_devuelve_500(url, _fb_name, body) -> None:
    engine = _make_engine()
    engine.submit.side_effect = RuntimeError("boom")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post(url, json=body)
    assert resp.status_code == 500
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "boom" in payload["error"]


# ---------------------------------------------------------------------------
# 409
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_post_con_fb_ocupado_devuelve_409(url, _fb_name, body) -> None:
    engine = _make_engine()
    engine.submit.side_effect = FBBusyError("FB ocupado: ya tiene trabajo")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post(url, json=body)
    assert resp.status_code == 409
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "trabajo en curso" in payload["error"]


# ---------------------------------------------------------------------------
# 202
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url,fb_name,body", ENDPOINTS, ids=IDS)
def test_post_happy_path_devuelve_202_con_job_id(url, fb_name, body) -> None:
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post(url, json=body)
    assert resp.status_code == 202
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["job_id"] == "job-abc123"
    # El trabajo se encola para el FB correcto, con los params del body.
    engine.submit.assert_called_once_with(
        fb_name, plc_name="ZC_PLC_STD", proc_uid=100,
    )


@pytest.mark.parametrize("url,_fb_name,body", ENDPOINTS, ids=IDS)
def test_post_no_devuelve_el_result_del_fb(url, _fb_name, body) -> None:
    """El router no bloquea: no hay result en la respuesta, solo el job_id."""
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post(url, json=body)
    payload = resp.get_json()
    assert "result" not in payload
    assert "summary" not in payload
    assert "operations_executed" not in payload
    assert "post_sync_preview" not in payload
