"""Tests del router Flask ``proc_process_crear_router``.

Cubre los endpoints POST:

  - ``test_crear_preview_ok_con_plantilla``:
    Body valido con plantilla dummy en tmp_path + FB mockeado que
    arranca OK y termina en n_done -> 200 con el ``fb.result``.
  - ``test_crear_preview_body_incompleto``:
    Body sin campos obligatorios -> 400 con ``ok: False`` y mensaje
    mencionando el campo que falta.
  - ``test_crear_aplicar_fb_no_arranca``:
    Body valido pero FB no registrado en el engine -> 500 con
    ``ok: False``.
  - ``test_crear_aplicar_fb_rechaza_start_409``:
    Body valido pero el FB mockeado retorna ``started=False``
    (porque ya esta activo) -> 409 con ``ok: False``.

Los FBs se mockean ENTERAMENTE (``MagicMock``): no necesitamos engine
OB1 en marcha. Para ``fb.start`` se usa ``AsyncMock`` (la firma real
es async, y el router hace ``asyncio.run(fb.start(...))``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask


# ── Helpers ──────────────────────────────────────────────────────────


def _make_app(engine: MagicMock | None = None) -> Flask:
    """Crea una app Flask minima con el ``Engine`` mockeado."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    if engine is not None:
        app.config["ENGINE"] = engine
    return app


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
    """Crea un mock del FB que el router consume.

    El router:
      - llama ``asyncio.run(fb.start(**validated))`` -> necesita
        ``AsyncMock``.
      - llama ``_poll_until_terminal(fb)`` que itera hasta que
        ``fb.is_terminal()`` retorne True.
      - accede a ``fb.nStep``, ``fb.n_error``, ``fb.error_msg``,
        ``fb.result``.
      - accede a ``fb.STEP_TIMEOUT_S`` (clase attr).
    """
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
    (p / "Variables PLC" / "003_Procesos").mkdir(parents=True)
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Document>\n"
        '  <SW.Tags.PlcTagTable ID="0">\n'
        '    <AttributeList><Name>50010_TEST</Name></AttributeList>\n'
        "    <ObjectList></ObjectList>\n"
        "  </SW.Tags.PlcTagTable>\n"
        "</Document>\n"
    )
    (p / "Variables PLC" / "003_Procesos" / "50010_TEST.xml").write_text(
        xml, encoding="utf-8",
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
    """POST /api/v1/procesos/crear/preview con body valido -> 200."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    fb_mock = _make_mock_fb(
        result={
            "success": True,
            "archivos_previstos": [
                {"rel_in": "Bloques de programa/FC50010_TEST_INTERFAZ.s7dcl",
                 "rel_out": "bloques/FC60010_EXP_INTERFAZ.s7dcl",
                 "kind": "text", "colisiona": False},
            ],
            "colisiones": [],
            "preview_dir": str(plantilla_dummy.parent / "preview"),
            "manifest_plantilla": {"base": 50010, "codigo": "TEST"},
        },
    )
    engine = MagicMock()
    engine.get_fb.return_value = fb_mock

    app = _make_app(engine)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/preview", json={
        "plantillas_path": str(plantilla_dummy.parent),
        "dir_plantilla_nombre": "TestPlantilla",
        "base_nueva": 60010,
        "codigo_nuevo": "EXP",
        "nombre_nuevo": "NuevoProceso",
        "minimos_usuario": {
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "archivos_previstos" in data
    assert len(data["archivos_previstos"]) == 1
    # El mock FB fue consultado por nombre correcto.
    engine.get_fb.assert_called_with("proc_process_crear_preview")
    # El start() fue invocado con los kwargs validados.
    fb_mock.start.assert_awaited_once()


def test_crear_preview_body_incompleto() -> None:
    """POST sin campos obligatorios -> 400."""
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    app = _make_app(MagicMock())
    app.register_blueprint(bp)
    client = app.test_client()

    # Body vacio: faltan todos los campos obligatorios.
    resp = client.post("/api/v1/procesos/crear/preview", json={})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert "falta" in data["error"]

    # Falta solo ``base_nueva``.
    resp = client.post("/api/v1/procesos/crear/preview", json={
        "plantillas_path": "C:/x",
        "dir_plantilla_nombre": "P",
        "codigo_nuevo": "X",
        "nombre_nuevo": "Y",
        "minimos_usuario": {"N_MAX_PREAL": 1},
    })
    assert resp.status_code == 400
    assert "base_nueva" in resp.get_json()["error"]

    # ``minimos_usuario`` debe ser dict no vacio.
    resp = client.post("/api/v1/procesos/crear/preview", json={
        "plantillas_path": "C:/x",
        "dir_plantilla_nombre": "P",
        "base_nueva": 1,
        "codigo_nuevo": "X",
        "nombre_nuevo": "Y",
        "minimos_usuario": [],
    })
    assert resp.status_code == 400
    assert "minimos_usuario" in resp.get_json()["error"]


def test_crear_aplicar_fb_no_registrado() -> None:
    """Si el FB ``proc_process_crear_aplicar`` NO esta en el engine
    (engine.get_fb retorna None) -> 500 con ``ok: False``.
    """
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    engine = MagicMock()
    engine.get_fb.return_value = None

    app = _make_app(engine)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/aplicar", json={
        "plantillas_path": "C:/x",
        "dir_plantilla_nombre": "P",
        "base_nueva": 60010,
        "codigo_nuevo": "EXP",
        "nombre_nuevo": "NuevoProceso",
        "minimos_usuario": {"N_MAX_PREAL": 30, "N_MAX_PINT": 30,
                            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5},
        "plc_name": "S7-1500",
    })
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["ok"] is False
    assert "proc_process_crear_aplicar" in data["error"]


def test_crear_aplicar_fb_rechaza_start_409(plantilla_dummy: Path) -> None:
    """Si el FB mockeado retorna ``started=False`` (porque ya esta
    activo o terminal) -> 409 con ``ok: False``.
    """
    from areas.alimentacion.frontend.proc_process_crear_router import bp

    fb_mock = _make_mock_fb(started=False)
    engine = MagicMock()
    engine.get_fb.return_value = fb_mock

    app = _make_app(engine)
    app.register_blueprint(bp)
    client = app.test_client()

    resp = client.post("/api/v1/procesos/crear/aplicar", json={
        "plantillas_path": str(plantilla_dummy.parent),
        "dir_plantilla_nombre": "TestPlantilla",
        "base_nueva": 60010,
        "codigo_nuevo": "EXP",
        "nombre_nuevo": "NuevoProceso",
        "minimos_usuario": {"N_MAX_PREAL": 30, "N_MAX_PINT": 30,
                            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5},
        "plc_name": "S7-1500",
    })
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["ok"] is False
    # El mensaje explica que el FB ya esta activo.
    assert "activo" in data["error"].lower() or "terminal" in data["error"].lower()
