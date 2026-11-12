"""Tests de la ruta del estado de la sesion.

La sesion vive en la memoria del backend: un F5 de la web la pide entera y
la recibe. Al reiniciar la app, se pierde.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from zc_suite.nucleo.app.config import Config
from zc_suite.nucleo.app.main import montar_app
from zc_suite.nucleo.sesion import CLAVE_SESION, Sesion
from zc_suite.nucleo.tia.eventos import BusEventos
from zc_suite.nucleo.tia.servicio import ServicioTIA


class TsFalso:
    """Doble minimo del modulo ``siemens_tia_scripting``."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier_interfaz"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def set_logging(self, path: str, console: bool) -> None:
        pass


def _app(sesion: Sesion | None = None) -> Flask:
    """La app montada, con su sesion."""
    bus_eventos = BusEventos()
    servicio = ServicioTIA(publicador=bus_eventos.publicar, cargador=lambda: TsFalso())
    config = Config.model_validate({"areas": {"alimentacion": {}}})
    return montar_app(
        servicio,
        bus_eventos,
        config=config,
        sesion=sesion,
    )


@pytest.fixture
def sesion() -> Sesion:
    """Una sesion vacia."""
    return Sesion()


@pytest.fixture
def app(sesion: Sesion) -> Flask:
    """La app con la sesion."""
    return _app(sesion)


def _estado(cliente: Any) -> dict[str, Any]:
    """El estado de la sesion que sirve la app."""
    respuesta = cliente.get("/api/v1/sesion", base_url="http://localhost:9484")
    assert respuesta.status_code == 200
    return respuesta.get_json()


def test_la_ruta_de_la_sesion_esta_montada(app: Flask) -> None:
    reglas = {regla.rule for regla in app.url_map.iter_rules()}

    assert "/api/v1/sesion" in reglas


def test_la_sesion_devuelve_el_estado_de_tia(app: Flask) -> None:
    """La SPA necesita saber si TIA esta conectado."""
    estado = _estado(app.test_client())

    assert estado["tia"]["conectado"] is False
    assert "version_tia" in estado["tia"]


def test_la_sesion_devuelve_los_plcs_y_el_seleccionado(
    app: Flask,
    sesion: Sesion,
) -> None:
    """Los PLCs y el seleccionado son parte del estado."""
    sesion.guardar_plcs([{"nombre": "ZC_PLC_STD"}], {"nombre": "Alimentacion"})
    sesion.seleccionar("ZC_PLC_STD")

    estado = _estado(app.test_client())

    assert estado["plcs"] == [{"nombre": "ZC_PLC_STD"}]
    assert estado["proyecto"] == {"nombre": "Alimentacion"}
    assert estado["plc_seleccionado"] == "ZC_PLC_STD"


def test_la_sesion_devuelve_el_escaneo_del_plc_seleccionado(
    app: Flask,
    sesion: Sesion,
) -> None:
    """El escaneo va con la sesion: por eso sobrevive a un F5."""
    sesion.seleccionar("ZC_PLC_STD")
    sesion.guardar_escaneo(
        "ZC_PLC_STD",
        [{"nombre": "DB2000_ED"}],
        [{"nombre": "2000_Disp_ED"}],
        [],
    )

    estado = _estado(app.test_client())

    assert estado["escaneo"] is not None
    assert estado["escaneo"]["plc"] == "ZC_PLC_STD"
    assert estado["escaneo"]["bloques"] == [{"nombre": "DB2000_ED"}]
    assert estado["escaneo"]["caducado"] is False


def test_la_sesion_devuelve_lo_que_tiene_cada_area(app: Flask) -> None:
    """Cada area aporta lo suyo: el area de alimentacion, su Excel."""
    estado = _estado(app.test_client())

    assert "alimentacion" in estado["areas"]
    assert "excel" in estado["areas"]["alimentacion"]


def test_reiniciar_la_app_deja_la_sesion_en_blanco(sesion: Sesion) -> None:
    """Una sesion nueva no hereda nada de la anterior."""
    sesion.guardar_plcs([{"nombre": "ZC_PLC_STD"}], {"nombre": "Alimentacion"})
    sesion.seleccionar("ZC_PLC_STD")
    sesion.guardar_escaneo("ZC_PLC_STD", [], [], [])

    estado = _estado(_app().test_client())

    assert estado["plcs"] == []
    assert estado["proyecto"] is None
    assert estado["plc_seleccionado"] == ""
    assert estado["escaneo"] is None


def test_la_app_registra_la_sesion(app: Flask, sesion: Sesion) -> None:
    """La sesion es una dependencia de la app, como el hilo de TIA."""
    assert app.config[CLAVE_SESION] is sesion
