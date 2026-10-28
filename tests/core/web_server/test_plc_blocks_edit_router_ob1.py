"""Tests de los routers de core migrados al patron OB1.

``core/web_server/routers/plc.py`` y ``core/web_server/routers/blocks_edit.py``
ya no bloquean: encolan el trabajo en el OB1 y responden ``202`` con el
``job_id``. El resultado llega al HMI por el evento SSE ``fb_state``.

Cubre:
  - body incompleto              -> 400
  - sin engine / sin TIA client  -> 500
  - FB no registrado en el engine -> 500 (404 en /plc/fb/<name>/start)
  - FB con trabajo en curso       -> 409
  - fallo al encolar              -> 500
  - happy path                    -> 202 con job_id
"""
from __future__ import annotations

from unittest.mock import MagicMock

from flask import Flask

from core.composition.plc_engine import FBBusyError
from core.web_server.routers.blocks_edit import bp as bp_blocks_edit
from core.web_server.routers.plc import bp as bp_plc
from core.web_server.routers.plc import bp_blocks as bp_plc_blocks


def _make_app(engine: MagicMock | None, *, tia_client: object = "tia") -> Flask:
    app = Flask(__name__)
    app.register_blueprint(bp_plc)
    app.register_blueprint(bp_plc_blocks)
    app.register_blueprint(bp_blocks_edit)
    if engine is not None:
        app.config["ENGINE"] = engine
    if tia_client == "tia":
        tia = MagicMock()
        tia.ts = MagicMock()
        tia.wrapper = MagicMock()
        app.config["TIA_CLIENT"] = tia
    elif tia_client is not None:
        app.config["TIA_CLIENT"] = tia_client
    return app


def _make_engine(*, fb: object = "fb", submit: object = None) -> MagicMock:
    engine = MagicMock()
    engine.get_fb.return_value = fb if fb != "fb" else MagicMock()
    engine.submit.return_value = submit if submit is not None else "job-abc123"
    return engine


# ---------------------------------------------------------------------------
# POST /api/v1/plc/fb/<name>/start
# ---------------------------------------------------------------------------


def test_start_fb_happy_path_devuelve_202_con_job_id() -> None:
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/plc/fb/mi_fb/start", json={"params": {"a": 1}},
        )
    assert resp.status_code == 202
    assert resp.get_json() == {"ok": True, "job_id": "job-abc123"}
    engine.submit.assert_called_once_with("mi_fb", a=1)


def test_start_fb_no_registrado_devuelve_404() -> None:
    app = _make_app(_make_engine(fb=None))
    with app.test_client() as client:
        resp = client.post("/api/v1/plc/fb/mi_fb/start", json={})
    assert resp.status_code == 404


def test_start_fb_con_fb_ocupado_devuelve_409() -> None:
    engine = _make_engine()
    engine.submit.side_effect = FBBusyError("ocupado")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post("/api/v1/plc/fb/mi_fb/start", json={})
    assert resp.status_code == 409


def test_start_fb_si_submit_falla_devuelve_500() -> None:
    engine = _make_engine()
    engine.submit.side_effect = RuntimeError("boom")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post("/api/v1/plc/fb/mi_fb/start", json={})
    assert resp.status_code == 500
    assert "boom" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# GET/POST /api/v1/plcs/<plc_name>/blocks
# ---------------------------------------------------------------------------


def test_scan_blocks_happy_path_devuelve_202_con_job_id() -> None:
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.get("/api/v1/plcs/PLC_1/blocks")
    assert resp.status_code == 202
    assert resp.get_json() == {"ok": True, "job_id": "job-abc123"}
    engine.submit.assert_called_once_with(
        "scan_plc_blocks", plc_name="PLC_1", force_refresh=False,
    )


def test_scan_blocks_refresh_pasa_force_refresh() -> None:
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post(
            "/api/v1/plcs/PLC_1/blocks/refresh", json={"force_refresh": True},
        )
    assert resp.status_code == 202
    engine.submit.assert_called_once_with(
        "scan_plc_blocks", plc_name="PLC_1", force_refresh=True,
    )


def test_scan_blocks_sin_tia_client_devuelve_503() -> None:
    app = _make_app(_make_engine(), tia_client=None)
    with app.test_client() as client:
        resp = client.get("/api/v1/plcs/PLC_1/blocks")
    assert resp.status_code == 503
    assert resp.headers["X-Error-Type"] == "TIAConnectionError"


def test_scan_blocks_sin_engine_devuelve_500() -> None:
    app = _make_app(None)
    with app.test_client() as client:
        resp = client.get("/api/v1/plcs/PLC_1/blocks")
    assert resp.status_code == 500
    assert resp.get_json()["error"] == "engine no inicializado"


def test_scan_blocks_fb_no_registrado_devuelve_500() -> None:
    app = _make_app(_make_engine(fb=None))
    with app.test_client() as client:
        resp = client.get("/api/v1/plcs/PLC_1/blocks")
    assert resp.status_code == 500
    assert "no registrado" in resp.get_json()["error"]


def test_scan_blocks_con_fb_ocupado_devuelve_409() -> None:
    engine = _make_engine()
    engine.submit.side_effect = FBBusyError("ocupado")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.get("/api/v1/plcs/PLC_1/blocks")
    assert resp.status_code == 409


def test_scan_blocks_no_devuelve_el_snapshot() -> None:
    """El snapshot llega por SSE (cache_changed), no en el body."""
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = client.get("/api/v1/plcs/PLC_1/blocks")
    body = resp.get_json()
    assert "snapshot" not in body


# ---------------------------------------------------------------------------
# POST /api/v1/blocks/edit/prepare y /apply
# ---------------------------------------------------------------------------


def test_blocks_edit_prepare_happy_path_devuelve_202_con_job_id() -> None:
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post("/api/v1/blocks/edit/prepare", json={
            "plc_name": "PLC_1",
            "selected_block_paths": ["DB2000_ED"],
        })
    assert resp.status_code == 202
    assert resp.get_json() == {"ok": True, "job_id": "job-abc123"}
    engine.submit.assert_called_once_with(
        "block_edit_prepare",
        plc_name="PLC_1",
        selected_block_paths=["DB2000_ED"],
    )


def test_blocks_edit_prepare_sin_params_devuelve_400() -> None:
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = client.post("/api/v1/blocks/edit/prepare", json={})
    assert resp.status_code == 400


def test_blocks_edit_prepare_con_fb_ocupado_devuelve_409() -> None:
    engine = _make_engine()
    engine.submit.side_effect = FBBusyError("ocupado")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post("/api/v1/blocks/edit/prepare", json={
            "plc_name": "PLC_1",
            "selected_block_paths": ["DB2000_ED"],
        })
    assert resp.status_code == 409


def test_blocks_edit_apply_happy_path_devuelve_202_con_job_id() -> None:
    engine = _make_engine()
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post("/api/v1/blocks/edit/apply", json={
            "plc_name": "PLC_1",
            "edits": {"DB2000_ED": {"number": 2001}},
        })
    assert resp.status_code == 202
    assert resp.get_json() == {"ok": True, "job_id": "job-abc123"}
    engine.submit.assert_called_once_with(
        "block_edit_apply",
        plc_name="PLC_1",
        edits={"DB2000_ED": {"number": 2001}},
    )


def test_blocks_edit_apply_sin_params_devuelve_400() -> None:
    app = _make_app(_make_engine())
    with app.test_client() as client:
        resp = client.post("/api/v1/blocks/edit/apply", json={})
    assert resp.status_code == 400


def test_blocks_edit_apply_fb_no_registrado_devuelve_500() -> None:
    app = _make_app(_make_engine(fb=None))
    with app.test_client() as client:
        resp = client.post("/api/v1/blocks/edit/apply", json={
            "plc_name": "PLC_1",
            "edits": {"DB2000_ED": {"number": 2001}},
        })
    assert resp.status_code == 500


def test_blocks_edit_apply_con_fb_ocupado_devuelve_409() -> None:
    engine = _make_engine()
    engine.submit.side_effect = FBBusyError("ocupado")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post("/api/v1/blocks/edit/apply", json={
            "plc_name": "PLC_1",
            "edits": {"DB2000_ED": {"number": 2001}},
        })
    assert resp.status_code == 409


def test_blocks_edit_apply_si_submit_falla_devuelve_500() -> None:
    engine = _make_engine()
    engine.submit.side_effect = RuntimeError("boom")
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.post("/api/v1/blocks/edit/apply", json={
            "plc_name": "PLC_1",
            "edits": {"DB2000_ED": {"number": 2001}},
        })
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Los endpoints de lectura no se tocan
# ---------------------------------------------------------------------------


def test_get_fb_status_sigue_devolviendo_el_estado() -> None:
    fb = MagicMock()
    fb.nStep = 99
    fb.is_terminal.return_value = True
    fb.error_msg = None
    fb.result = {"ok": True}
    engine = _make_engine(fb=fb)
    app = _make_app(engine)
    with app.test_client() as client:
        resp = client.get("/api/v1/plc/fb/mi_fb/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "mi_fb"
    assert body["nStep"] == 99
    assert body["is_terminal"] is True
    assert body["result"] == {"ok": True}
