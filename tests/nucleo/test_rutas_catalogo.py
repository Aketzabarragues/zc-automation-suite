"""Tests de la ruta del catalogo de la app."""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from zc_suite.eventos import BusEventos
from zc_suite.main import AREAS, montar_app
from zc_suite.rutas import catalogo as rutas_catalogo
from zc_suite.tia import ServicioTIA


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
    """La app montada, con el catalogo de las areas."""
    bus_eventos = BusEventos()
    servicio = ServicioTIA(publicador=bus_eventos.publicar, cargador=lambda: TsFalso())
    return montar_app(servicio, bus_eventos)


def test_la_ruta_del_catalogo_esta_montada(app: Flask) -> None:
    reglas = {regla.rule for regla in app.url_map.iter_rules()}

    assert "/api/v1/catalog" in reglas


def test_el_catalogo_sirve_lo_de_cada_area(app: Flask) -> None:
    """El catalogo va indexado por area: el nucleo no conoce las areas."""
    cliente = app.test_client()

    respuesta = cliente.get("/api/v1/catalog", base_url="http://localhost:9484")

    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    for area in AREAS:
        assert area.ID in datos


def test_el_catalogo_de_un_area_tiene_sus_pestanas(app: Flask) -> None:
    """El catalogo del area lleva las pestañas y las etiquetas de N_MAX."""
    cliente = app.test_client()

    respuesta = cliente.get("/api/v1/catalog", base_url="http://localhost:9484")

    catalogo = respuesta.get_json()["alimentacion"]
    assert catalogo["device_tabs"]
    assert catalogo["nmax"]


def test_sin_catalogo_devuelve_un_diccionario_vacio() -> None:
    """Una app sin catalogo no revienta: devuelve ``{}``."""
    from zc_suite.web import crear_app

    bus_eventos = BusEventos()
    servicio = ServicioTIA(publicador=bus_eventos.publicar, cargador=lambda: TsFalso())
    app = crear_app(servicio, bus_eventos)
    rutas_catalogo.registrar(app)

    cliente: Any = app.test_client()
    respuesta = cliente.get("/api/v1/catalog", base_url="http://localhost:9484")

    assert respuesta.status_code == 200
    assert respuesta.get_json() == {}
