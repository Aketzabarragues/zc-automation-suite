"""Tests del blueprint ``blocks_edit``.

Cubre:

  - ``POST /prepare`` happy path (202 + ``job_id``).
  - ``POST /prepare`` 400 si faltan ``plc_name`` o ``selected_block_paths``.
  - ``POST /prepare`` 409 si el FB ya tiene un trabajo en curso.
  - ``POST /prepare`` 500 si el FB no esta registrado en el engine.
  - ``POST /apply`` 202 + ``job_id`` en el happy path.
  - ``POST /apply`` 400/409/500 en los casos de error.
  - ``GET /<plc_name>/prepared`` (cache de preparados).

El router no bloquea: encola el trabajo en el OB1 con ``engine.submit``
y devuelve ``202`` con el ``job_id``. El resultado llega al HMI por el
evento SSE ``fb_state``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from flask import Flask

from core.composition.plc_engine import FBBusyError
from core.web_server.routers.blocks_edit import bp


# ── Helpers ─────────────────────────────────────────────────────────


def _make_flask_app(engine: MagicMock) -> Flask:
    """Crea una app Flask minima con el blueprint y el engine inyectado.

    No usamos ``create_app`` porque el blueprint todavia no esta
    en la lista ``blueprint_modules`` de ``app_flask._register_blueprints``
    (lo anadiremos junto al wiring del blueprint).
    """
    app = Flask("test_blocks_edit")
    app.config["ENGINE"] = engine
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app


# ── 1. Happy path ──────────────────────────────────────────────────


def test_prepare_endpoint_returns_ok():
    """POST /prepare con args validos encola el trabajo y devuelve 202."""
    engine = MagicMock()
    engine.get_fb.return_value = MagicMock()
    engine.submit.return_value = "job-abc123"

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
    assert resp.status_code == 202
    data = resp.get_json()
    assert data["ok"] is True
    assert data["job_id"] == "job-abc123"
    # El trabajo se encolo para el FB correcto, con sus params.
    engine.submit.assert_called_once_with(
        "block_edit_prepare",
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
    """``engine.submit`` levanta ``FBBusyError`` -> 409."""
    engine = MagicMock()
    engine.get_fb.return_value = MagicMock()
    engine.submit.side_effect = FBBusyError("ya tiene trabajo")

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
    assert "trabajo en curso" in resp.get_json()["error"]


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
# El stub 501 se sustituyo por la implementacion
# real del FB ``block_edit_apply``. Los 5 tests de abajo cubren el
# contrato nuevo (200/400/409/500/504).


# ── 6. POST /apply happy path ──────────────────────────────────────


def test_apply_endpoint_returns_ok():
    """POST /apply con args validos encola el trabajo y devuelve 202."""
    engine = MagicMock()
    engine.get_fb.return_value = MagicMock()
    engine.submit.return_value = "job-abc123"

    app = _make_flask_app(engine)
    client = app.test_client()

    resp = client.post(
        "/api/v1/blocks/edit/apply",
        json={
            "plc_name": "PLC_1",
            "edits": {
                "2000_Dispositivos/DB2000_ED": {"name": "DB_Entradas"},
                "2000_Dispositivos/DB2001_SAL": {"number": 201},
            },
        },
    )
    assert resp.status_code == 202
    data = resp.get_json()
    assert data["ok"] is True
    assert data["job_id"] == "job-abc123"
    # El trabajo se encolo para el FB correcto, con sus params.
    engine.submit.assert_called_once_with(
        "block_edit_apply",
        plc_name="PLC_1",
        edits={
            "2000_Dispositivos/DB2000_ED": {"name": "DB_Entradas"},
            "2000_Dispositivos/DB2001_SAL": {"number": 201},
        },
    )


# ── 7. 400 por args faltantes ───────────────────────────────────────


def test_apply_endpoint_returns_400_on_missing_args():
    """POST /apply sin ``plc_name`` o sin ``edits`` -> 400."""
    engine = MagicMock()
    engine.get_fb.return_value = MagicMock()
    app = _make_flask_app(engine)
    client = app.test_client()

    # Sin ``plc_name``.
    resp = client.post(
        "/api/v1/blocks/edit/apply",
        json={"edits": {"a/DB1": {"name": "X"}}},
    )
    assert resp.status_code == 400
    assert "obligatorios" in resp.get_json()["error"]

    # Sin ``edits``.
    resp = client.post(
        "/api/v1/blocks/edit/apply",
        json={"plc_name": "PLC_1"},
    )
    assert resp.status_code == 400
    assert "obligatorios" in resp.get_json()["error"]

    # Dict vacio -> tambien 400.
    resp = client.post(
        "/api/v1/blocks/edit/apply",
        json={"plc_name": "PLC_1", "edits": {}},
    )
    assert resp.status_code == 400


# ── 8. 400 si el FB raise ValueError (whitelist de keys) ──────────


def test_apply_endpoint_returns_400_on_value_error_from_fb():
    """``engine.submit`` levanta ``ValueError`` -> 400 con mensaje."""
    engine = MagicMock()
    engine.get_fb.return_value = MagicMock()
    engine.submit.side_effect = ValueError(
        "edits['a/DB1'] contiene key 'title' no permitida. "
        "Solo se admiten ['name', 'number']."
    )

    app = _make_flask_app(engine)
    client = app.test_client()

    resp = client.post(
        "/api/v1/blocks/edit/apply",
        json={
            "plc_name": "PLC_1",
            "edits": {"a/DB1": {"title": "Foo"}},
        },
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "args invalidos" in data["error"]
    assert "title" in data["error"]


# ── 9. 409 si el FB ya tiene un trabajo en curso ──────────────────────


def test_apply_endpoint_returns_409_when_fb_already_running():
    """``engine.submit`` levanta ``FBBusyError`` -> 409."""
    engine = MagicMock()
    engine.get_fb.return_value = MagicMock()
    engine.submit.side_effect = FBBusyError("ya tiene trabajo")

    app = _make_flask_app(engine)
    client = app.test_client()

    resp = client.post(
        "/api/v1/blocks/edit/apply",
        json={
            "plc_name": "PLC_1",
            "edits": {"a/DB1": {"name": "X"}},
        },
    )
    assert resp.status_code == 409
    assert "trabajo en curso" in resp.get_json()["error"]


# ── 10. 500 si el FB no esta registrado ────────────────────────────


def test_apply_endpoint_returns_500_when_fb_not_registered():
    """``engine.get_fb('block_edit_apply')`` retorna None -> 500."""
    engine = MagicMock()
    engine.get_fb.return_value = None
    app = _make_flask_app(engine)
    client = app.test_client()

    resp = client.post(
        "/api/v1/blocks/edit/apply",
        json={
            "plc_name": "PLC_1",
            "edits": {"a/DB1": {"name": "X"}},
        },
    )
    assert resp.status_code == 500
    assert "no registrado" in resp.get_json()["error"]
    engine.get_fb.assert_called_once_with("block_edit_apply")


# ─── 11. GET /<plc_name>/prepared ────────────────────────────
# Cubre:
#   - Empty cache -> 200 + ``{"ok": True, "prepared": {}, ...}``.
#   - Cache con DTOs -> 200 + ``prepared`` serializado con ``to_dict()``.
#   - Sin ``app_cache`` en config -> 503.
#   - DTO sin ``to_dict`` -> fallback al dict con 10 keys.


def _make_flask_app_with_app_cache(engine, app_cache):
    """Igual que ``_make_flask_app`` pero inyecta ``APP_CACHE``."""
    app = Flask("test_blocks_edit")
    app.config["ENGINE"] = engine
    app.config["APP_CACHE"] = app_cache
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app


def test_get_prepared_returns_empty_when_no_cache():
    """Sin ``block_edit_prepared`` en app_cache -> 200 + ``prepared: {}``."""
    from core.runtime.app_cache import AppCache

    engine = MagicMock()
    app_cache = AppCache()
    app = _make_flask_app_with_app_cache(engine, app_cache)
    client = app.test_client()

    resp = client.get("/api/v1/blocks/edit/PLC_1/prepared")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["prepared"] == {}
    assert data["plc_name"] == "PLC_1"


def test_get_prepared_serializes_dtos_via_to_dict():
    """DTOs en cache se serializan con ``DataBloquePLC.to_dict()``."""
    from core.data.data_block_plc import DataBloquePLC
    from core.runtime.app_cache import AppCache

    dto = DataBloquePLC(
        nombre="DB2000_ED",
        numero=2000,
        tipo="DB",
        ruta="2000_Dispositivos\\DB2000_ED",
        title="Entradas digitales",
        comment="Comentario DB ED",
        author="Aketza",
        version="1.0",
        programming_language="DB",
        memory_layout="Optimized",
    )

    engine = MagicMock()
    app_cache = AppCache()
    app_cache.set_block_edit_prepared(
        "PLC_1", {"2000_Dispositivos/DB2000_ED": dto},
    )
    app = _make_flask_app_with_app_cache(engine, app_cache)
    client = app.test_client()

    resp = client.get("/api/v1/blocks/edit/PLC_1/prepared")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["plc_name"] == "PLC_1"
    assert "2000_Dispositivos/DB2000_ED" in data["prepared"]
    serialized = data["prepared"]["2000_Dispositivos/DB2000_ED"]
    assert serialized["nombre"] == "DB2000_ED"
    assert serialized["numero"] == 2000
    assert serialized["title"] == "Entradas digitales"
    assert serialized["programming_language"] == "DB"


def test_get_prepared_returns_503_without_app_cache():
    """Sin ``APP_CACHE`` en config -> 503."""
    engine = MagicMock()
    app = Flask("test_blocks_edit")
    app.config["ENGINE"] = engine
    # NO inyectamos APP_CACHE.
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.get("/api/v1/blocks/edit/PLC_1/prepared")
    assert resp.status_code == 503
    assert "app_cache" in resp.get_json()["error"]


def test_get_prepared_falls_back_when_dto_lacks_to_dict():
    """DTO sin ``to_dict()`` -> fallback al dict inline con 10 keys."""
    from core.runtime.app_cache import AppCache

    class FakeDto:
        """DTO fake SIN ``to_dict`` (simula un dataclass externo)."""

        nombre = "FB1"
        numero = 1
        tipo = "FB"
        ruta = "FBs\\FB1"
        title = "T"
        comment = "C"
        author = "A"
        version = "1"
        programming_language = "SCL"
        memory_layout = "Standard"

    engine = MagicMock()
    app_cache = AppCache()
    app_cache.set_block_edit_prepared(
        "PLC_1", {"FBs/FB1": FakeDto()},
    )
    app = _make_flask_app_with_app_cache(engine, app_cache)
    client = app.test_client()

    resp = client.get("/api/v1/blocks/edit/PLC_1/prepared")
    assert resp.status_code == 200
    data = resp.get_json()
    serialized = data["prepared"]["FBs/FB1"]
    assert serialized["nombre"] == "FB1"
    assert serialized["programming_language"] == "SCL"
    assert serialized["memory_layout"] == "Standard"
