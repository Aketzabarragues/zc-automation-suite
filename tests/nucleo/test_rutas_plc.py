"""Tests de las rutas del PLC: listar, escanear y editar bloques."""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from zc_suite.eventos import BusEventos
from zc_suite.rutas import plc
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
    """App con el hilo de TIA, el bus y las rutas del PLC montadas."""
    bus_eventos = BusEventos()
    servicio_tia = ServicioTIA(
        publicador=bus_eventos.publicar,
        cargador=lambda: TsFalso(),
    )
    aplicacion = crear_app(servicio_tia, bus_eventos)
    aplicacion.config["TESTING"] = True
    plc.registrar(aplicacion)
    return aplicacion


@pytest.fixture
def cliente(app: Flask) -> Any:
    return app.test_client()


# ── la lista de PLCs ───────────────────────────────────────────────────────


def test_listar_plcs_responde_202_con_el_job_id(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/tia/plcs/listar", base_url=BASE, headers={"Origin": BASE})

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"]


def test_listar_plcs_sin_origin_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.post("/api/v1/tia/plcs/listar")

    assert respuesta.status_code == 403


# ── el escaneo ─────────────────────────────────────────────────────────────


def test_escanear_responde_202_con_el_job_id(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/tia/plcs/ZC_PLC_STD/escanear",
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"]


# ── preparar y editar ──────────────────────────────────────────────────────


def test_preparar_responde_202_con_el_job_id(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/tia/plcs/ZC_PLC_STD/bloques/preparar",
        json={"bloques": ["OB1_MAIN"]},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"]


def test_preparar_sin_bloques_responde_400(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/tia/plcs/ZC_PLC_STD/bloques/preparar",
        json={"bloques": []},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400


def test_editar_responde_202_con_el_job_id(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/tia/plcs/ZC_PLC_STD/bloques/editar",
        json={"cambios": {"OB1_MAIN": {"Name": "OB1_NUEVO"}}},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"]


def test_editar_sin_cambios_responde_400(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/tia/plcs/ZC_PLC_STD/bloques/editar",
        json={"cambios": {}},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400


def test_editar_con_cambios_vacios_responde_400(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/tia/plcs/ZC_PLC_STD/bloques/editar",
        json={"cambios": "esto no es un diccionario"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400
