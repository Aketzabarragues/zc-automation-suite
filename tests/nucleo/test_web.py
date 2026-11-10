"""Tests del shell HTTP: stream SSE, encolado de trabajos, Origin y estaticos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from flask import Flask, jsonify

from zc_suite.eventos import BusEventos
from zc_suite.tia import ServicioTIA
from zc_suite.web import (
    HTTPError,
    crear_app,
    exigir_origen,
    lanzar,
    origenes_permitidos,
    servir_spa,
    stream_eventos,
)

# ── dobles ─────────────────────────────────────────────────────────────────


class TsFalso:
    """Doble minimo del modulo ``siemens_tia_scripting``."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def set_logging(self, path: str, console: bool) -> None:
        pass


@pytest.fixture
def app() -> Flask:
    """App Flask con el hilo de TIA y el bus de eventos de prueba."""
    bus_eventos = BusEventos()
    servicio_tia = ServicioTIA(cargador=lambda: TsFalso())
    aplicacion = crear_app(servicio_tia, bus_eventos)
    aplicacion.config["TESTING"] = True

    @aplicacion.post("/api/v1/prueba")
    def _prueba() -> Any:
        """Ruta de prueba que exige el origen de la app."""
        exigir_origen()
        return jsonify({"ok": True})

    return aplicacion


@pytest.fixture
def cliente(app: Flask) -> Any:
    return app.test_client()


# ── stream SSE ─────────────────────────────────────────────────────────────


def test_el_stream_emite_los_eventos_como_data(app: Flask) -> None:
    bus_eventos = app.config["ZC_BUS"]
    generador = stream_eventos(bus_eventos, timeout=1.0)
    bus_eventos.publicar("log", {"nivel": "info", "mensaje": "hola"})

    linea = next(generador)
    generador.close()

    assert linea.startswith("data: ")
    carga = json.loads(linea[len("data: ") :].strip())
    assert carga["type"] == "log"
    assert carga["mensaje"] == "hola"


def test_la_suscripcion_se_abre_al_crear_el_stream(app: Flask) -> None:
    """No se pierde ningun evento publicado entre la peticion y el primer next."""
    bus_eventos = app.config["ZC_BUS"]
    generador = stream_eventos(bus_eventos, timeout=1.0)
    bus_eventos.publicar("log", {"nivel": "info", "mensaje": "primero"})

    linea = next(generador)
    generador.close()

    assert "primero" in linea


def test_el_stream_emite_keep_alive_cuando_no_hay_eventos(app: Flask) -> None:
    generador = stream_eventos(app.config["ZC_BUS"], timeout=0.2)

    linea = next(generador)
    generador.close()

    assert linea == ": keep-alive\n\n"


def test_la_ruta_de_eventos_responde_con_event_stream(app: Flask, cliente: Any) -> None:
    # Se publica antes de pedir el stream para que el primer trozo salga
    # enseguida: la suscripcion se abre al llegar la peticion.
    app.config["ZC_BUS"].publicar("tia", {"conectado": False})
    respuesta = cliente.get("/api/eventos", buffered=False)

    assert respuesta.status_code == 200
    assert respuesta.mimetype == "text/event-stream"
    respuesta.close()


def test_el_stream_entrega_el_ultimo_progress_al_conectarse(app: Flask) -> None:
    bus_eventos = app.config["ZC_BUS"]
    bus_eventos.publicar("progress", {"active": True, "current": 1, "total": 2})

    generador = stream_eventos(bus_eventos, timeout=1.0)
    linea = next(generador)
    generador.close()

    carga = json.loads(linea[len("data: ") :].strip())
    assert carga["type"] == "progress"
    assert carga["current"] == 1


# ── encolado de trabajos ───────────────────────────────────────────────────


def test_lanzar_responde_202_con_el_job_id(cliente: Any) -> None:
    with cliente.application.app_context():
        respuesta, codigo = lanzar(lambda job: {})

    assert codigo == 202
    assert respuesta.get_json()["job_id"]


def test_lanzar_responde_409_si_hay_un_trabajo_en_curso(cliente: Any) -> None:
    with cliente.application.app_context():
        _, codigo = lanzar(lambda job: {})
        respuesta, codigo2 = lanzar(lambda job: {})

    assert codigo == 202
    assert codigo2 == 409
    assert "error" in respuesta.get_json()


# ── cabecera Origin ────────────────────────────────────────────────────────


def test_una_post_sin_origin_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/prueba")

    assert respuesta.status_code == 403


def test_una_post_de_origen_desconocido_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/prueba", headers={"Origin": "http://otro-sitio"})

    assert respuesta.status_code == 403


def test_una_post_del_propio_origen_se_acepta(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/prueba", headers={"Origin": "http://localhost"})

    assert respuesta.status_code == 200
    assert respuesta.get_json() == {"ok": True}


def test_los_origenes_de_desarrollo_estan_permitidos(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/prueba", headers={"Origin": "http://localhost:5173"})

    assert respuesta.status_code == 200


def test_origenes_permitidos_incluye_el_de_la_app(app: Flask) -> None:
    with app.test_request_context("/"):
        permitidos = origenes_permitidos()

    assert "http://localhost" in permitidos


# ── estaticos ──────────────────────────────────────────────────────────────


def test_sin_frontend_compilado_responde_404(cliente: Any, tmp_path: Path) -> None:
    cliente.application.config["ZC_DIST"] = tmp_path / "no-existe"

    respuesta = cliente.get("/")

    assert respuesta.status_code == 404


def test_sirve_el_index_html_de_la_spa(cliente: Any, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>ZC</html>", encoding="utf-8")
    cliente.application.config["ZC_DIST"] = tmp_path

    respuesta = cliente.get("/")

    assert respuesta.status_code == 200
    assert b"<html>ZC</html>" in respuesta.data
    respuesta.close()


def test_sirve_un_fichero_de_la_spa(cliente: Any, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    cliente.application.config["ZC_DIST"] = tmp_path

    respuesta = cliente.get("/assets/app.js")

    assert respuesta.status_code == 200
    assert b"console.log(1)" in respuesta.data
    respuesta.close()


def test_una_ruta_de_spa_desconocida_devuelve_el_index(cliente: Any, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>ZC</html>", encoding="utf-8")
    cliente.application.config["ZC_DIST"] = tmp_path

    respuesta = cliente.get("/dispositivos")

    assert respuesta.status_code == 200
    assert b"<html>ZC</html>" in respuesta.data
    respuesta.close()


def test_no_sirve_ficheros_fuera_de_la_carpeta(app: Flask, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    secreto = tmp_path.parent / "secreto.txt"
    secreto.write_text("no deberias ver esto", encoding="utf-8")

    try:
        with app.test_request_context("/"), pytest.raises(HTTPError) as fallo:
            servir_spa(tmp_path, "../secreto.txt")
        assert fallo.value.codigo == 404
    finally:
        secreto.unlink(missing_ok=True)


def test_la_ruta_de_estaticos_no_sale_de_la_carpeta(cliente: Any, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>ZC</html>", encoding="utf-8")
    secreto = tmp_path.parent / "secreto2.txt"
    secreto.write_text("no deberias ver esto", encoding="utf-8")
    cliente.application.config["ZC_DIST"] = tmp_path

    try:
        respuesta = cliente.get("/../secreto2.txt")
        assert respuesta.status_code == 404
        assert b"no deberias ver esto" not in respuesta.data
    finally:
        secreto.unlink(missing_ok=True)
