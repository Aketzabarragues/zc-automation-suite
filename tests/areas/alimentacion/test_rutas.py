"""Tests de las rutas del area de alimentacion.

Incluyen las del Excel maestro. El portal de TIA es un doble: **no hay
conexion** en ninguna de estas pruebas, que es justo lo que hay que
comprobar: el trabajo del Excel no la exige.
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.rutas import CLAVE_ALMACEN, TAMANO_MAXIMO, rutas
from zc_suite.nucleo.tia.eventos import BusEventos
from zc_suite.nucleo.tia.servicio import ServicioTIA
from zc_suite.nucleo.web.app import crear_app

BASE = "http://localhost:9484"


# ── el entorno ──────────────────────────────────────────────────────────────


@pytest.fixture
def eventos() -> list[tuple[str, dict[str, Any]]]:
    """Los eventos publicados por el hilo de TIA."""
    return []


@pytest.fixture
def almacen(modelo: ConfigArea) -> AlmacenExcel:
    """La cache del area: en memoria, sin copia guardada."""
    store = AlmacenExcel()
    store.config = modelo
    return store


@pytest.fixture
def app(
    almacen: AlmacenExcel,
    eventos: list[tuple[str, dict[str, Any]]],
) -> Any:
    """La app con las rutas del area y sin conexion con TIA."""
    bus_eventos = BusEventos()
    servicio_tia = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: None,
    )
    aplicacion = crear_app(servicio_tia, bus_eventos)
    aplicacion.config["TESTING"] = True
    aplicacion.register_blueprint(rutas)
    aplicacion.config[CLAVE_ALMACEN] = almacen
    yield aplicacion
    servicio_tia.parar()


@pytest.fixture
def cliente(app: Any) -> Any:
    return app.test_client()


def _esperar_job(eventos: list[tuple[str, dict[str, Any]]], job_id: str) -> dict[str, Any]:
    """Espera al evento de fin del trabajo indicado."""
    limite = time.monotonic() + 5.0
    while time.monotonic() < limite:
        for tipo, carga in list(eventos):
            if tipo == "job" and carga["job"] == job_id:
                return carga
        time.sleep(0.005)
    raise AssertionError(f"El trabajo {job_id} no termino.")


def _pasos(eventos: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """Los identificadores de los pasos del ultimo trabajo."""
    for tipo, carga in reversed(eventos):
        if tipo == "progress":
            return [etapa["id"] for etapa in carga["stages"]]
    return []


def _detalle_de(eventos: list[tuple[str, dict[str, Any]]], paso: str) -> str:
    """El detalle de un paso del ultimo trabajo."""
    for tipo, carga in reversed(eventos):
        if tipo != "progress":
            continue
        for etapa in carga["stages"]:
            if etapa["id"] == paso:
                return etapa.get("detail") or ""
    return ""


# ── ver el Excel ────────────────────────────────────────────────────────────


def test_sin_excel_cargado_da_el_vacio(cliente: Any) -> None:
    respuesta = cliente.get("/api/v1/areas/alimentacion/excel", base_url=BASE)

    assert respuesta.status_code == 200
    cuerpo = respuesta.get_json()
    assert cuerpo["cargado"] is False
    assert cuerpo["archivo"] is None
    assert cuerpo["plcs"] == []
    assert cuerpo["dispositivos"] == []


# ── subir un Excel ──────────────────────────────────────────────────────────


def test_subir_un_xlsx_responde_202_con_el_job_id(
    cliente: Any,
    excel_maestro: Path,
) -> None:
    with excel_maestro.open("rb") as fichero:
        respuesta = cliente.post(
            "/api/v1/areas/alimentacion/excel",
            data={"fichero": (fichero, "maestro.xlsx")},
            base_url=BASE,
            headers={"Origin": BASE},
        )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"]


def test_subir_un_xlsm_responde_202_con_el_job_id(
    cliente: Any,
    excel_maestro: Path,
) -> None:
    """El Excel maestro del operario es ``.xlsm``."""
    with excel_maestro.open("rb") as fichero:
        respuesta = cliente.post(
            "/api/v1/areas/alimentacion/excel",
            data={"fichero": (fichero, "Maestro_ZC_PLC_STD.xlsm")},
            base_url=BASE,
            headers={"Origin": BASE},
        )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"]


def test_el_trabajo_parsea_un_xlsm(
    cliente: Any,
    almacen: AlmacenExcel,
    eventos: list[tuple[str, dict[str, Any]]],
    excel_maestro: Path,
) -> None:
    with excel_maestro.open("rb") as fichero:
        respuesta = cliente.post(
            "/api/v1/areas/alimentacion/excel",
            data={"fichero": (fichero, "Maestro_ZC_PLC_STD.xlsm")},
            base_url=BASE,
            headers={"Origin": BASE},
        )
    job_id = respuesta.get_json()["job_id"]

    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert almacen.archivo == "Maestro_ZC_PLC_STD.xlsm"
    assert almacen.estado()["dispositivos"][0]["filas"][0]["tag"] == "V_ED_001"


def test_el_trabajo_del_excel_no_exige_conexion_con_tia(
    cliente: Any,
    almacen: AlmacenExcel,
    eventos: list[tuple[str, dict[str, Any]]],
    excel_maestro: Path,
) -> None:
    with excel_maestro.open("rb") as fichero:
        respuesta = cliente.post(
            "/api/v1/areas/alimentacion/excel",
            data={"fichero": (fichero, "maestro.xlsx")},
            base_url=BASE,
            headers={"Origin": BASE},
        )
    job_id = respuesta.get_json()["job_id"]

    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert evento["resultado"]["archivo"] == "maestro.xlsx"
    assert almacen.cargado is True
    filas = almacen.estado()["dispositivos"][0]["filas"]
    assert filas[0]["tag"] == "V_ED_001"


def test_subir_un_excel_sin_origin_se_rechaza(cliente: Any, excel_maestro: Path) -> None:
    with excel_maestro.open("rb") as fichero:
        respuesta = cliente.post(
            "/api/v1/areas/alimentacion/excel",
            data={"fichero": (fichero, "maestro.xlsx")},
            base_url=BASE,
        )

    assert respuesta.status_code == 403


def test_subir_sin_fichero_responde_400(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/areas/alimentacion/excel",
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400
    assert "fichero" in respuesta.get_json()["error"]


def test_subir_una_extension_no_admitida_responde_400(cliente: Any, tmp_path: Path) -> None:
    ruta = tmp_path / "maestro.xls"
    ruta.write_bytes(b"esto no es un Excel")

    with ruta.open("rb") as fichero:
        respuesta = cliente.post(
            "/api/v1/areas/alimentacion/excel",
            data={"fichero": (fichero, "maestro.xls")},
            base_url=BASE,
            headers={"Origin": BASE},
        )

    assert respuesta.status_code == 400
    assert ".xlsx" in respuesta.get_json()["error"]
    assert ".xlsm" in respuesta.get_json()["error"]


def test_subir_un_fichero_grande_responde_400(
    cliente: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modulo = importlib.import_module("zc_suite.areas.alimentacion.rutas")
    monkeypatch.setattr(modulo, "TAMANO_MAXIMO", 10)
    ruta = tmp_path / "maestro.xlsx"
    ruta.write_bytes(b"0123456789ABCDEF")

    with ruta.open("rb") as fichero:
        respuesta = cliente.post(
            "/api/v1/areas/alimentacion/excel",
            data={"fichero": (fichero, "maestro.xlsx")},
            base_url=BASE,
            headers={"Origin": BASE},
        )

    assert respuesta.status_code == 400
    assert "grande" in respuesta.get_json()["error"]


def test_el_trabajo_avisa_de_los_dominios_sin_tabla(
    cliente: Any,
    eventos: list[tuple[str, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    """Un Excel sin tablas avisa, pero el trabajo termina bien."""
    ruta = tmp_path / "sin_tablas.xlsx"
    libro = Workbook()
    libro.save(ruta)

    with ruta.open("rb") as fichero:
        respuesta = cliente.post(
            "/api/v1/areas/alimentacion/excel",
            data={"fichero": (fichero, "sin_tablas.xlsx")},
            base_url=BASE,
            headers={"Origin": BASE},
        )
    job_id = respuesta.get_json()["job_id"]

    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    avisos = evento["resultado"]["avisos"]
    assert any("DISP_ED" in aviso for aviso in avisos)
    assert "avisos" in _pasos(eventos)
    assert "DISP_ED" in _detalle_de(eventos, "avisos")


class _ServicioConectado:
    """Un hilo de TIA que dice que esta conectado y anota el trabajo."""

    def __init__(self) -> None:
        self.funcion: Any = None
        self.params: dict[str, Any] = {}

    @property
    def conectado(self) -> bool:
        return True

    def lanzar(self, funcion: Any, **params: Any) -> str:
        self.funcion = funcion
        self.params = params
        return "job-de-prueba"


# ── sincronizar los dispositivos ────────────────────────────────────────────


def test_sincronizar_sin_plc_responde_400(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/areas/alimentacion/dispositivos/sincronizar",
        json={},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400
    assert "PLC" in respuesta.get_json()["error"]


def test_sincronizar_sin_excel_responde_400(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/areas/alimentacion/dispositivos/sincronizar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400
    assert "Excel" in respuesta.get_json()["error"]


def test_sincronizar_sin_conexion_con_tia_responde_400(
    cliente: Any,
    almacen: AlmacenExcel,
    excel_maestro: Path,
) -> None:
    almacen.volcar(excel_maestro)

    respuesta = cliente.post(
        "/api/v1/areas/alimentacion/dispositivos/sincronizar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400
    assert "TIA" in respuesta.get_json()["error"]


def test_sincronizar_responde_202_y_encola_el_trabajo(
    cliente: Any,
    almacen: AlmacenExcel,
    excel_maestro: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    almacen.volcar(excel_maestro)
    modulo = importlib.import_module("zc_suite.areas.alimentacion.rutas")
    nucleo = importlib.import_module("zc_suite.nucleo.web.app")
    servicio = _ServicioConectado()
    monkeypatch.setattr(modulo, "servicio", lambda: servicio)
    monkeypatch.setattr(nucleo, "servicio", lambda: servicio)

    respuesta = cliente.post(
        "/api/v1/areas/alimentacion/dispositivos/sincronizar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"] == "job-de-prueba"
    assert servicio.params["plc"] == "ZC_PLC_STD"
    assert servicio.params["almacen"] is almacen
    assert servicio.params["config"] is almacen.config


def test_sincronizar_sin_origin_se_rechaza(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/areas/alimentacion/dispositivos/sincronizar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
    )

    assert respuesta.status_code == 403


def test_el_tamano_maximo_por_defecto_es_de_20_mb() -> None:
    assert TAMANO_MAXIMO == 20 * 1024 * 1024


def test_subir_otro_excel_borra_la_prevision_guardada(
    app: Any,
    cliente: Any,
    eventos: list[tuple[str, dict[str, Any]]],
    excel_maestro: Path,
) -> None:
    """La prevision guardada era del Excel anterior: deja de valer."""
    from zc_suite.areas.alimentacion.dispositivos import CLAVE_PREVISION
    from zc_suite.nucleo.sesion import CLAVE_SESION, Sesion

    sesion = Sesion()
    sesion.guardar_dato_area("alimentacion", CLAVE_PREVISION, {"plc": "ZC_PLC_STD"})
    app.config[CLAVE_SESION] = sesion

    with excel_maestro.open("rb") as fichero:
        respuesta = cliente.post(
            "/api/v1/areas/alimentacion/excel",
            data={"fichero": (fichero, "Maestro_ZC_PLC_STD.xlsx")},
            base_url=BASE,
            headers={"Origin": BASE},
        )
    evento = _esperar_job(eventos, respuesta.get_json()["job_id"])

    assert evento["estado"] == "ok"
    assert CLAVE_PREVISION not in sesion.datos_area("alimentacion")
