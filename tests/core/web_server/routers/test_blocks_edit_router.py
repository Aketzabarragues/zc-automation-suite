"""Tests del blueprint ``blocks_edit``.

Cubre:

  - ``POST /prepare`` happy path (200 + ``result``).
  - ``POST /prepare`` 400 si faltan ``plc_name`` o ``selected_block_paths``.
  - ``POST /prepare`` 409 si el FB ya esta corriendo.
  - ``POST /prepare`` 500 si el FB no esta registrado en el engine.
  - ``POST /apply`` 501 placeholder (commit 7).

Mockeamos el engine con ``MagicMock`` y configuramos ``get_fb`` +
``fb.start`` (como ``AsyncMock`` para soportar ``asyncio.run``) +
``fb.is_terminal`` + ``fb.nStep`` + ``fb.n_error`` + ``fb.result`` +
``fb.error_msg``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from flask import Flask

from core.web_server.routers.blocks_edit import bp


# ── Helpers ─────────────────────────────────────────────────────────


def _make_flask_app(engine: MagicMock) -> Flask:
    """Crea una app Flask minima con el blueprint y el engine inyectado.

    No usamos ``create_app`` porque el blueprint todavia no esta
    en la lista ``blueprint_modules`` de ``app_flask._register_blueprints``
    (lo anadiremos en commit 7 o junto al wiring en commit 8).
    """
    app = Flask("test_blocks_edit")
    app.config["ENGINE"] = engine
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app


# ── 1. Happy path ──────────────────────────────────────────────────


def test_prepare_endpoint_returns_ok():
    """POST /prepare con args validos arranca el FB y devuelve 200 + result."""
    fb = MagicMock()
    fb.start = AsyncMock(return_value=True)
    fb.is_terminal.return_value = True
    fb.nStep = 99  # n_done
    fb.n_error = 98
    fb.result = {"ok": True, "plc_name": "PLC_1", "n_blocks": 3}

    engine = MagicMock()
    engine.get_fb.return_value = fb

    app = _make_flask_app(engine)
    client = app.test_client()

    resp = client.post(
        "/api/v1/blocks/edit/prepare",
        json={
            "plc_name": "PLC_1",
            "selected_block_paths": [
                "2000_Dispositivos/DB2000_ED",
                "2000_Dispositivos/DB2001_SAL",
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["result"] == {
        "ok": True, "plc_name": "PLC_1", "n_blocks": 3,
    }
    assert data["nStep"] == 99
    # El FB arranco con plc_name y selected_block_paths.
    fb.start.assert_awaited_once_with(
        plc_name="PLC_1",
        selected_block_paths=[
            "2000_Dispositivos/DB2000_ED",
            "2000_Dispositivos/DB2001_SAL",
        ],
    )


# ── 2. 400 por args faltantes ───────────────────────────────────────


def test_prepare_endpoint_returns_400_on_missing_args():
    """POST /prepare sin ``plc_name`` o sin ``selected_block_paths`` -> 400."""
    engine = MagicMock()
    engine.get_fb.return_value = MagicMock()
    app = _make_flask_app(engine)
    client = app.test_client()

    # Sin ``plc_name``.
    resp = client.post(
        "/api/v1/blocks/edit/prepare",
        json={"selected_block_paths": ["a/DB1"]},
    )
    assert resp.status_code == 400
    assert "obligatorios" in resp.get_json()["error"]

    # Sin ``selected_block_paths``.
    resp = client.post(
        "/api/v1/blocks/edit/prepare",
        json={"plc_name": "PLC_1"},
    )
    assert resp.status_code == 400
    assert "obligatorios" in resp.get_json()["error"]

    # Lista vacia -> tambien 400 (la spec dice no vacio).
    resp = client.post(
        "/api/v1/blocks/edit/prepare",
        json={"plc_name": "PLC_1", "selected_block_paths": []},
    )
    assert resp.status_code == 400


# ── 3. 409 si el FB ya esta corriendo ──────────────────────────────


def test_prepare_endpoint_returns_409_when_fb_already_running():
    """``fb.start()`` retorna False (FB ya activo/terminal) -> 409."""
    fb = MagicMock()
    fb.start = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.get_fb.return_value = fb

    app = _make_flask_app(engine)
    client = app.test_client()

    resp = client.post(
        "/api/v1/blocks/edit/prepare",
        json={
            "plc_name": "PLC_1",
            "selected_block_paths": ["a/DB1"],
        },
    )
    assert resp.status_code == 409
    assert "ya activo" in resp.get_json()["error"]


# ── 4. 500 si el FB no esta registrado ─────────────────────────────


def test_prepare_endpoint_returns_500_when_fb_not_registered():
    """``engine.get_fb('block_edit_prepare')`` retorna None -> 500."""
    engine = MagicMock()
    engine.get_fb.return_value = None
    app = _make_flask_app(engine)
    client = app.test_client()

    resp = client.post(
        "/api/v1/blocks/edit/prepare",
        json={
            "plc_name": "PLC_1",
            "selected_block_paths": ["a/DB1"],
        },
    )
    assert resp.status_code == 500
    assert "no registrado" in resp.get_json()["error"]
    engine.get_fb.assert_called_once_with("block_edit_prepare")


# ── 5. POST /apply -> 501 placeholder ──────────────────────────────


def test_apply_endpoint_returns_501_not_implemented():
    """``POST /apply`` devuelve 501 con JSON explicativo (commit 7)."""
    engine = MagicMock()
    app = _make_flask_app(engine)
    client = app.test_client()

    resp = client.post(
        "/api/v1/blocks/edit/apply",
        json={"plc_name": "PLC_1", "edits": {"a/DB1": {"name": "X"}}},
    )
    assert resp.status_code == 501
    data = resp.get_json()
    assert "pendiente commit 7" in data["error"]
