"""Tests del router Flask ``proc_process_crear_router``.

Tras Commit 51 (sept-2026, rediseño conceptual) el Excel del
operario es la fuente de verdad para los datos del proceso nuevo.
La SPA solo envia ``dir_plantilla_nombre + proc_uid`` y el router
los resuelve desde ``AppState.excel_cache.procesos``.

Tests:
  - ``test_crear_preview_ok_con_plantilla``:
    Body valido (minimal) + Excel con proc_uid=300 + plantillas_path OK
    + FB mockeado que arranca OK -> 200 con el ``fb.result``.
  - ``test_crear_preview_sin_excel``:
    AppState.excel_cache=None -> 400 (accionable: "Cargue el Excel").
  - ``test_crear_preview_proc_uid_inexistente``:
    proc_uid=999 que no esta en el Excel -> 400 con mensaje accionable.
  - ``test_crear_preview_body_incompleto``:
    Body sin campos obligatorios -> 400.
  - ``test_crear_aplicar_fb_no_registrado``:
    engine.get_fb(None) -> 500.
  - ``test_crear_aplicar_fb_rechaza_start_409``:
    fb.start = False -> 409.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask


# ── Helpers ──────────────────────────────────────────────────────────


def _make_app(
    engine: MagicMock | None = None,
    app_state: MagicMock | None = None,
    config_manager: MagicMock | None = None,
) -> Flask:
    """Crea una app Flask minima con el ``Engine`` y ``APP_STATE`` mockeados."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    if engine is not None:
        app.config["ENGINE"] = engine
    if app_state is not None:
        app.config["APP_STATE"] = app_state
    if config_manager is not None:
        app.config["CONFIG_MANAGER"] = config_manager
    else:
        # Default: ConfigManager con plantillas_path = tmp_path del test
        cm = MagicMock()
        cm.get_plantillas_path.return_value = ""
        app.config["CONFIG_MANAGER"] = cm
    return app


def _make_mock_proc_excel(uid: int = 300) -> MagicMock:
    """Crea un mock de ``DataProcesoPLC`` para inyectar en excel_cache."""
    proc = MagicMock()
    proc.uid = uid
    proc.nombre = "ProcesoTest300"
    proc.codigo = "EXP"
    proc.preal = 30
    proc.pint = 30
    proc.alarmas = 30
    proc.alm_hmi = 5
    return proc


def _make_mock_excel_cache(proc_uid: int = 300) -> MagicMock:
    """Crea un mock del ``excel_cache`` con un proceso del Excel."""
    cache = MagicMock()
    cache.procesos = [_make_mock_proc_excel(proc_uid)]
    return cache


def _make_mock_app_state(proc_uid: int = 300) -> MagicMock:
    """Crea un ``AppState`` mockeado con un Excel cacheado."""
    state = MagicMock()
    state.excel_cache = _make_mock_excel_cache(proc_uid)
    return state


def _make_mock_fb(
    *,
    started: bool = True,
    nStep: int = 99,
    n_error: int = 98,
    error_msg: str | None = None,
    result: dict | None = None,
    is_terminal_return: bool = True,
    step_timeout_s: float = 600.0,
) -> MagicMock:
    """Crea un mock del FB que el router consume."""
    fb = MagicMock()
    fb.start = AsyncMock(return_value=started)
    fb.is_terminal = MagicMock(return_value=is_terminal_return)
    fb.nStep = nStep
    fb.n_error = n_error
    fb.error_msg = error_msg
    fb.result = result
    fb.STEP_TIMEOUT_S = step_timeout_s
    return fb


@pytest.fixture
def plantilla_dummy(tmp_path: Path) -> Path:
    """Crea una plantilla minima en tmp_path."""
    p = tmp_path / "TestPlantilla"
    p.mkdir()
    bloques = p / "Bloques de programa"
    bloques.mkdir()
    (bloques / "FC50010_TEST_INTERFAZ.s7dcl").write_text(
        "FUNCTION_BLOCK FC50010_TEST_INTERFAZ\n", encoding="utf-8",
    )
    (bloques / "50010_TEST_COMENTARIOS.s7res").write_text(
        "BOM content", encoding="utf-8-sig",
    )
    (p / "manifest.json").write_text(
        json.dumps({
            "base": 50010, "codigo": "TEST", "nombre": "ProcesoTest",
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    return p


# ── Tests ────────────────────────────────────────────────────────────


def test_crear_preview_ok_con_plantilla(plantilla_dummy: Path) -> None:
    """Body minimal valido (dir_plantilla_nombre + proc_uid) ->
    200 con el ``fb.result``."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    fb_mock = _make_mock_fb(result={
        "success": True,
        "manifest_plantilla": {"base": 300, "codigo": "EXP"},
        "archivos_previstos": [
            {"rel_in": "Bloques de programa/FC50010.s7dcl",
             "rel_out": "bloques/FC60010_EXP.s7dcl",
             "kind": "text", "colisiona": False},
        ],
        "colisiones": [],
        "preview_dir": str(plantilla_dummy.parent / "preview"),
    })
    engine.get_fb.return_value = fb_mock

    cm = MagicMock()
    cm.get_plantillas_path.return_value = str(plantilla_dummy.parent)

    app_state = _make_mock_app_state(proc_uid=300)

    app = _make_app(engine=engine, app_state=app_state, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "TestPlantilla",
        "proc_uid": 300,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert len(data["archivos_previstos"]) == 1
    # El mock FB fue consultado por nombre correcto.
    engine.get_fb.assert_called_with("proc_process_crear_preview")
    # El start() fue invocado con los kwargs resueltos (uid=300 ->
    # base=300, codigo=EXP, minimos_usuario={...} del Excel).
    fb_mock.start.assert_awaited_once()
    kwargs = fb_mock.start.await_args.kwargs
    assert kwargs["base_nueva"] == 300
    assert kwargs["codigo_nuevo"] == "EXP"
    assert kwargs["minimos_usuario"]["N_MAX_PREAL"] == 30


def test_crear_preview_sin_excel() -> None:
    """AppState.excel_cache=None -> 400 accionable."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    state = MagicMock()
    state.excel_cache = None
    cm = MagicMock()
    cm.get_plantillas_path.return_value = "C:/plantillas"

    app = _make_app(engine=engine, app_state=state, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "P",
        "proc_uid": 300,
    })
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Excel" in data["error"] or "excel" in data["error"]


def test_crear_preview_proc_uid_inexistente() -> None:
    """proc_uid no esta en el Excel -> 400 accionable."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    cm = MagicMock()
    cm.get_plantillas_path.return_value = "C:/plantillas"
    app_state = _make_mock_app_state(proc_uid=300)  # El Excel solo tiene uid=300

    app = _make_app(engine=engine, app_state=app_state, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "P",
        "proc_uid": 999,  # No existe en el Excel
    })
    assert resp.status_code == 400
    assert "999" in resp.get_json()["error"]


def test_crear_preview_body_incompleto() -> None:
    """Body sin dir_plantilla_nombre o sin proc_uid -> 400."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    app = _make_app(engine=MagicMock())
    app.register_blueprint(bp)
    client = app.test_client()

    # Body vacio: faltan los 2 campos obligatorios.
    resp = client.post("/api/v1/procesos/crear/preview", json={})
    assert resp.status_code == 400
    assert "falta" in resp.get_json()["error"]

    # Falta solo proc_uid.
    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "P",
    })
    assert resp.status_code == 400
    assert "proc_uid" in resp.get_json()["error"]

    # proc_uid no es int.
    resp = client.post("/api/v1/procesos/crear/preview", json={
        "dir_plantilla_nombre": "P",
        "proc_uid": "300",
    })
    assert resp.status_code == 400
    assert "int" in resp.get_json()["error"]


def test_crear_aplicar_fb_no_registrado() -> None:
    """Si el FB NO esta en el engine -> 500."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = None
    cm = MagicMock()
    cm.get_plantillas_path.return_value = "C:/plantillas"
    app_state = _make_mock_app_state(proc_uid=300)

    app = _make_app(engine=engine, app_state=app_state, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/aplicar", json={
        "dir_plantilla_nombre": "P",
        "proc_uid": 300,
        "plc_name": "S7-1500",
    })
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["ok"] is False
    assert "proc_process_crear_aplicar" in data["error"]


def test_crear_aplicar_fb_rechaza_start_409(plantilla_dummy: Path) -> None:
    """Si fb.start retorna False -> 409."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    fb_mock = _make_mock_fb(started=False)
    engine.get_fb.return_value = fb_mock
    cm = MagicMock()
    cm.get_plantillas_path.return_value = str(plantilla_dummy.parent)
    app_state = _make_mock_app_state(proc_uid=300)

    app = _make_app(engine=engine, app_state=app_state, config_manager=cm)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/aplicar", json={
        "dir_plantilla_nombre": "TestPlantilla",
        "proc_uid": 300,
        "plc_name": "S7-1500",
    })
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["ok"] is False
    assert "activo" in data["error"].lower() or "terminal" in data["error"].lower()
