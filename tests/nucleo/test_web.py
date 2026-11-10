"""Tests del shell HTTP: stream SSE, encolado de trabajos, Origin, Host y estaticos."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from flask import Flask, jsonify

from zc_suite.eventos import BusEventos
from zc_suite.tia import ServicioTIA
from zc_suite.web import (
    HTTPError,
    crear_app,
    exigir_host,
    exigir_origen,
    lanzar,
    origenes_permitidos,
    servir_spa,
    stream_eventos,
)

#: Origen real de la app. El cliente de test manda por defecto ``Host:
#: localhost`` sin puerto, que la app rechaza.
BASE = "http://localhost:9484"


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


def _app(desarrollo: bool = False) -> Flask:
    """App Flask con el hilo de TIA y el bus de eventos de prueba."""
    bus_eventos = BusEventos()
    servicio_tia = ServicioTIA(
        publicador=bus_eventos.publicar,
        cargador=lambda: TsFalso(),
    )
    aplicacion = crear_app(servicio_tia, bus_eventos, desarrollo=desarrollo)
    aplicacion.config["TESTING"] = True

    @aplicacion.post("/api/v1/prueba")
    def _prueba() -> Any:
        """Ruta de prueba que exige el origen de la app."""
        exigir_origen()
        return jsonify({"ok": True})

    return aplicacion


@pytest.fixture
def app() -> Flask:
    return _app()


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


def test_el_stream_termina_limpio_al_cerrarse_el_bus(app: Flask) -> None:
    bus_eventos = app.config["ZC_BUS"]
    generador = stream_eventos(bus_eventos, timeout=0.2)
    bus_eventos.cerrar()

    with pytest.raises(StopIteration):
        next(generador)


def test_la_ruta_de_eventos_responde_con_event_stream(app: Flask, cliente: Any) -> None:
    # Se publica antes de pedir el stream para que el primer trozo salga
    # enseguida: la suscripcion se abre al llegar la peticion.
    app.config["ZC_BUS"].publicar("tia", {"conectado": False})
    respuesta = cliente.get("/api/eventos", base_url=BASE, buffered=False)

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


def test_el_stream_sigue_funcionando_tras_un_job_no_serializable(app: Flask) -> None:
    """Un resultado roto no deja el stream muerto para los que se reconectan."""
    servicio = app.config["ZC_TIA"]
    bus_eventos = app.config["ZC_BUS"]

    servicio.lanzar(lambda job: Path("resultado.txt"))

    limite = time.monotonic() + 5.0
    while servicio.ocupado and time.monotonic() < limite:
        time.sleep(0.01)

    generador = stream_eventos(bus_eventos, timeout=1.0)
    lineas = [next(generador) for _ in range(3)]
    generador.close()

    cargas = [
        json.loads(linea[len("data: ") :].strip())
        for linea in lineas
        if linea.startswith("data: ")
    ]
    trabajos = [carga for carga in cargas if carga["type"] == "job"]
    assert trabajos
    assert trabajos[0]["estado"] == "error"
    assert "no es serializable" in trabajos[0]["error"]


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
    respuesta = cliente.post("/api/v1/prueba", base_url=BASE)

    assert respuesta.status_code == 403


def test_una_post_de_origen_desconocido_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/prueba",
        base_url=BASE,
        headers={"Origin": "http://otro-sitio"},
    )

    assert respuesta.status_code == 403


def test_una_post_del_propio_origen_se_acepta(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/prueba",
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 200
    assert respuesta.get_json() == {"ok": True}


def test_el_origen_de_vite_se_rechaza_en_modo_normal(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/prueba",
        base_url=BASE,
        headers={"Origin": "http://localhost:5173"},
    )

    assert respuesta.status_code == 403


def test_el_origen_de_vite_se_acepta_en_modo_desarrollo() -> None:
    cliente = _app(desarrollo=True).test_client()

    respuesta = cliente.post(
        "/api/v1/prueba",
        base_url=BASE,
        headers={"Origin": "http://localhost:5173"},
    )

    assert respuesta.status_code == 200


def test_origenes_permitidos_incluye_el_de_la_app(app: Flask) -> None:
    with app.test_request_context("/"):
        permitidos = origenes_permitidos()

    assert BASE in permitidos
    assert "http://127.0.0.1:9484" in permitidos


def test_origenes_permitidos_no_incluye_el_de_vite_en_modo_normal(app: Flask) -> None:
    with app.test_request_context("/"):
        permitidos = origenes_permitidos()

    assert "http://localhost:5173" not in permitidos


# ── cabecera Host ──────────────────────────────────────────────────────────


def test_un_post_con_host_ajeno_se_rechaza(cliente: Any) -> None:
    """DNS rebinding: el atacante manda Host y Origin del dominio suyo."""
    respuesta = cliente.post(
        "/api/v1/prueba",
        base_url="http://evil.example:9484",
        headers={"Origin": "http://evil.example:9484"},
    )

    assert respuesta.status_code == 403


def test_un_get_a_eventos_con_host_ajeno_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.get("/api/eventos", base_url="http://evil.example:9484")

    assert respuesta.status_code == 403


def test_un_get_normal_con_host_ajeno_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.get("/", base_url="http://evil.example:9484")

    assert respuesta.status_code == 403


def test_una_peticion_con_host_sin_puerto_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.get("/", base_url="http://localhost")

    assert respuesta.status_code == 403


def test_exigir_host_acepta_los_dos_loopback(app: Flask) -> None:
    for host in ("127.0.0.1:9484", "localhost:9484"):
        with app.test_request_context("/", headers={"Host": host}):
            exigir_host()


def test_exigir_host_rechaza_un_host_ajeno(app: Flask) -> None:
    with (
        app.test_request_context("/", headers={"Host": "evil.example:9484"}),
        pytest.raises(HTTPError) as fallo,
    ):
        exigir_host()

    assert fallo.value.codigo == 403


# ── estaticos ──────────────────────────────────────────────────────────────


def test_sin_frontend_compilado_responde_404(cliente: Any, tmp_path: Path) -> None:
    cliente.application.config["ZC_DIST"] = tmp_path / "no-existe"

    respuesta = cliente.get("/", base_url=BASE)

    assert respuesta.status_code == 404


def test_sirve_el_index_html_de_la_spa(cliente: Any, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>ZC</html>", encoding="utf-8")
    cliente.application.config["ZC_DIST"] = tmp_path

    respuesta = cliente.get("/", base_url=BASE)

    assert respuesta.status_code == 200
    assert b"<html>ZC</html>" in respuesta.data
    respuesta.close()


def test_sirve_un_fichero_de_la_spa(cliente: Any, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    cliente.application.config["ZC_DIST"] = tmp_path

    respuesta = cliente.get("/assets/app.js", base_url=BASE)

    assert respuesta.status_code == 200
    assert b"console.log(1)" in respuesta.data
    respuesta.close()


def test_una_ruta_de_spa_desconocida_devuelve_el_index(cliente: Any, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>ZC</html>", encoding="utf-8")
    cliente.application.config["ZC_DIST"] = tmp_path

    respuesta = cliente.get("/dispositivos", base_url=BASE)

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
