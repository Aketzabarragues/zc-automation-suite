"""Tests de las rutas del PLC: listar, escanear, seleccionar y editar bloques."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from flask import Flask, jsonify

from zc_suite.nucleo.sesion import CLAVE_SESION, Sesion
from zc_suite.nucleo.tia.eventos import BusEventos
from zc_suite.nucleo.tia.servicio import ServicioTIA
from zc_suite.nucleo.web.app import crear_app
from zc_suite.nucleo.web.rutas import plc

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


# ── seleccionar ────────────────────────────────────────────────────────────


class _LanzadorDoble:
    """Cuenta los trabajos que se encolan."""

    def __init__(self) -> None:
        self.trabajos: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, funcion: Any, **params: Any) -> tuple[Any, int]:
        self.trabajos.append((funcion, params))
        return jsonify({"job_id": "job-de-prueba"}), 202


@pytest.fixture
def lanzador(monkeypatch: pytest.MonkeyPatch) -> _LanzadorDoble:
    """El encolado de trabajos, sin encolar de verdad."""
    doble = _LanzadorDoble()
    monkeypatch.setattr(plc, "lanzar", doble)
    return doble


def _sesion_de(app: Flask) -> Sesion:
    """La sesion que tiene la app."""
    return app.config[CLAVE_SESION]


def test_seleccionar_sin_escaneo_encola_el_escaneo(
    app: Flask,
    cliente: Any,
    lanzador: _LanzadorDoble,
) -> None:
    """Sin escaneo, seleccionar escanea: una sola vez."""
    respuesta = cliente.post(
        "/api/v1/tia/plcs/seleccionar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 202
    assert len(lanzador.trabajos) == 1
    assert lanzador.trabajos[0][1]["plc"] == "ZC_PLC_STD"


def test_seleccionar_con_escaneo_fresco_no_escanea(
    app: Flask,
    cliente: Any,
    lanzador: _LanzadorDoble,
) -> None:
    """Con un escaneo de menos de 5 minutos no hace falta escanear otra vez."""
    _sesion_de(app).guardar_escaneo("ZC_PLC_STD", [{"nombre": "DB2000_ED"}], [], [])

    respuesta = cliente.post(
        "/api/v1/tia/plcs/seleccionar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 200
    assert lanzador.trabajos == []
    cuerpo = respuesta.get_json()
    assert cuerpo["plc"] == "ZC_PLC_STD"
    assert cuerpo["escaneo"]["bloques"] == [{"nombre": "DB2000_ED"}]


def test_seleccionar_con_escaneo_caducado_escanea_una_sola_vez(
    app: Flask,
    cliente: Any,
    lanzador: _LanzadorDoble,
) -> None:
    """Un escaneo caducado no sirve: hay que rehacerlo, pero una vez."""
    sesion = _sesion_de(app)
    sesion.guardar_escaneo("ZC_PLC_STD", [], [], [])
    escaneo = sesion.escaneo("ZC_PLC_STD")
    assert escaneo is not None
    escaneo.momento = datetime.now() - timedelta(seconds=301)

    respuesta = cliente.post(
        "/api/v1/tia/plcs/seleccionar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 202
    assert len(lanzador.trabajos) == 1


def test_seleccionar_una_sola_vez_no_escanea_dos_veces(
    app: Flask,
    cliente: Any,
    lanzador: _LanzadorDoble,
) -> None:
    """Seleccionar dos veces el mismo PLC no encadena dos escaneos.

    En la app anterior, seleccionar un PLC disparaba el escaneo dos veces:
    mantienia TIA ocupado y hacia fallar el primer commit.
    """
    sesion = _sesion_de(app)
    sesion.guardar_escaneo("ZC_PLC_STD", [], [], [])

    for _ in range(2):
        respuesta = cliente.post(
            "/api/v1/tia/plcs/seleccionar",
            json={"plc": "ZC_PLC_STD"},
            base_url=BASE,
            headers={"Origin": BASE},
        )
        assert respuesta.status_code == 200

    assert lanzador.trabajos == []


def test_seleccionar_guarda_la_seleccion_en_el_servidor(
    app: Flask,
    cliente: Any,
    lanzador: _LanzadorDoble,
) -> None:
    """La seleccion vive en el backend: un F5 no la pierde."""
    cliente.post(
        "/api/v1/tia/plcs/seleccionar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert _sesion_de(app).seleccionado == "ZC_PLC_STD"


def test_seleccionar_sin_plc_responde_400(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/tia/plcs/seleccionar",
        json={},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400


def test_seleccionar_sin_origin_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/tia/plcs/seleccionar",
        json={"plc": "ZC_PLC_STD"},
    )

    assert respuesta.status_code == 403


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
