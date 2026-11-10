"""Tests de las rutas de conexion con TIA Portal."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from flask import Flask

from zc_suite.eventos import BusEventos
from zc_suite.rutas import conexion
from zc_suite.tia import ServicioTIA
from zc_suite.web import crear_app

BASE = "http://localhost:9484"


class PortalFalso:
    """Doble minimo del portal de TIA."""

    def get_process_id(self) -> int:
        return 4242

    def get_project(self) -> Any:
        return None

    def detach(self) -> None:
        pass


class TsFalso:
    """Doble minimo del modulo ``siemens_tia_scripting``."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def __init__(self) -> None:
        self.portal = PortalFalso()

    def attach_portal(self, portal_mode: str | None = None) -> PortalFalso:
        return self.portal

    def open_portal(self, portal_mode: str | None = None) -> PortalFalso:
        return self.portal

    def set_logging(self, path: str, console: bool) -> None:
        pass


@pytest.fixture
def app() -> Flask:
    """App con el hilo de TIA, el bus y las rutas de conexion montadas."""
    bus_eventos = BusEventos()
    servicio_tia = ServicioTIA(
        publicador=bus_eventos.publicar,
        cargador=lambda: TsFalso(),
    )
    aplicacion = crear_app(servicio_tia, bus_eventos)
    aplicacion.config["TESTING"] = True
    conexion.registrar(aplicacion)
    return aplicacion


@pytest.fixture
def cliente(app: Flask) -> Any:
    cliente = app.test_client()

    @app.post("/api/v1/prueba")
    def _prueba() -> Any:
        """Ruta nueva sin ninguna comprobacion propia: el shell la protege."""
        return {"ok": True}

    return cliente


# ── conectar y desconectar ─────────────────────────────────────────────────


def test_conectar_responde_202_con_el_job_id(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/tia/conectar", base_url=BASE, headers={"Origin": BASE})

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"]


def test_desconectar_responde_202_con_el_job_id(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/tia/desconectar", base_url=BASE, headers={"Origin": BASE})

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"]


def test_conectar_sin_origin_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/tia/conectar", base_url=BASE)

    assert respuesta.status_code == 403


def test_desconectar_sin_origin_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/tia/desconectar", base_url=BASE)

    assert respuesta.status_code == 403


def test_conectar_con_un_trabajo_en_curso_responde_409(app: Flask, cliente: Any) -> None:
    """Con un trabajo en curso, la ruta responde 409."""
    servicio = app.config["ZC_TIA"]
    espera = threading.Event()

    def trabajo_lento(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo lento", ["uno"])
        with job.paso("uno"):
            espera.wait(10.0)
        return {}

    servicio.lanzar(trabajo_lento)
    try:
        respuesta = cliente.post(
            "/api/v1/tia/conectar",
            base_url=BASE,
            headers={"Origin": BASE},
        )
    finally:
        espera.set()

    assert respuesta.status_code == 409


def test_una_ruta_post_nueva_rechaza_un_origen_ajeno(cliente: Any) -> None:
    """El shell protege cualquier POST, aunque la ruta no compruebe nada."""
    respuesta = cliente.post(
        "/api/v1/prueba",
        base_url=BASE,
        headers={"Origin": "http://otro-sitio"},
    )

    assert respuesta.status_code == 403


def test_una_ruta_post_nueva_acepta_el_origen_de_la_app(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/prueba", base_url=BASE, headers={"Origin": BASE})

    assert respuesta.status_code == 200


def test_un_get_no_exige_origin(cliente: Any) -> None:
    respuesta = cliente.get("/api/v1/tia/estado", base_url=BASE)

    assert respuesta.status_code == 200


# ── estado ─────────────────────────────────────────────────────────────────


def test_el_estado_no_necesita_origin(cliente: Any) -> None:
    respuesta = cliente.get("/api/v1/tia/estado", base_url=BASE)

    assert respuesta.status_code == 200
    assert respuesta.get_json() == {
        "conectado": False,
        "trabajo_actual": None,
        "ultimo_error": None,
    }


def test_el_estado_con_host_ajeno_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.get("/api/v1/tia/estado", base_url="http://evil.example:9484")

    assert respuesta.status_code == 403
