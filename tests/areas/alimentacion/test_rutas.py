"""Tests de las rutas del area de alimentacion.

Incluyen las del Excel maestro. El portal de TIA es un doble: **no hay
conexion** en ninguna de estas pruebas, que es justo lo que hay que
comprobar: el trabajo del Excel no la exige.
"""

from __future__ import annotations

import importlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from zc_suite.areas import alimentacion as area_alimentacion
from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.rutas import CLAVE_ALMACEN, TAMANO_MAXIMO, rutas
from zc_suite.nucleo.app import config as config_nucleo
from zc_suite.nucleo.tia.eventos import BusEventos
from zc_suite.nucleo.tia.servicio import ServicioTIA
from zc_suite.nucleo.web.app import (
    CLAVE_CONFIG,
    CLAVE_CONFIG_EN_USO,
    CLAVE_RECARGA_CONFIG,
    crear_app,
)

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


# ── las entidades ───────────────────────────────────────────────────────────


def test_la_prevision_de_entidades_responde_202_y_encola_el_trabajo(
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
        "/api/v1/areas/alimentacion/entidades/preview",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"] == "job-de-prueba"
    assert servicio.params["plc"] == "ZC_PLC_STD"
    assert servicio.params["almacen"] is almacen
    assert servicio.params["config"] is almacen.config


def test_sincronizar_entidades_responde_202_y_encola_el_trabajo(
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
        "/api/v1/areas/alimentacion/entidades/sincronizar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"] == "job-de-prueba"
    assert servicio.params["plc"] == "ZC_PLC_STD"


def test_la_prevision_de_entidades_sin_plc_responde_400(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/areas/alimentacion/entidades/preview",
        json={},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400
    assert "PLC" in respuesta.get_json()["error"]


def test_sincronizar_entidades_sin_plc_responde_400(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/areas/alimentacion/entidades/sincronizar",
        json={},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400
    assert "PLC" in respuesta.get_json()["error"]


def test_sincronizar_entidades_sin_excel_responde_400(cliente: Any) -> None:
    respuesta = cliente.post(
        "/api/v1/areas/alimentacion/entidades/sincronizar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400
    assert "Excel" in respuesta.get_json()["error"]


def test_sincronizar_entidades_sin_conexion_con_tia_responde_400(
    cliente: Any,
    almacen: AlmacenExcel,
    excel_maestro: Path,
) -> None:
    almacen.volcar(excel_maestro)

    respuesta = cliente.post(
        "/api/v1/areas/alimentacion/entidades/sincronizar",
        json={"plc": "ZC_PLC_STD"},
        base_url=BASE,
        headers={"Origin": BASE},
    )

    assert respuesta.status_code == 400
    assert "TIA" in respuesta.get_json()["error"]


def test_las_rutas_de_entidades_sin_origin_se_rechazan(cliente: Any) -> None:
    for ruta in ("entidades/preview", "entidades/sincronizar"):
        respuesta = cliente.post(
            f"/api/v1/areas/alimentacion/{ruta}",
            json={"plc": "ZC_PLC_STD"},
            base_url=BASE,
        )

        assert respuesta.status_code == 403, ruta


def test_subir_otro_excel_borra_la_prevision_de_entidades(
    app: Any,
    cliente: Any,
    eventos: list[tuple[str, dict[str, Any]]],
    excel_maestro: Path,
) -> None:
    """La prevision de entidades era del Excel anterior: deja de valer."""
    from zc_suite.areas.alimentacion.entidades import CLAVE_PREVISION
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


# ── los procesos ────────────────────────────────────────────────────────────


def _encolar(cliente: Any, ruta: str, body: dict[str, Any]) -> Any:
    return cliente.post(
        f"/api/v1/areas/alimentacion/{ruta}",
        json=body,
        base_url=BASE,
        headers={"Origin": BASE},
    )


def test_la_prevision_de_un_proceso_responde_202_y_encola_el_trabajo(
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

    respuesta = _encolar(
        cliente, "procesos/preview", {"plc": "ZC_PLC_STD", "proc_uid": 100}
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"] == "job-de-prueba"
    assert servicio.params["proc_uid"] == 100
    assert servicio.params["plc"] == "ZC_PLC_STD"
    assert servicio.params["almacen"] is almacen
    assert servicio.params["config"] is almacen.config


def test_sincronizar_un_proceso_responde_202_y_encola_el_trabajo(
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

    respuesta = _encolar(
        cliente, "procesos/sincronizar", {"plc": "ZC_PLC_STD", "proc_uid": 100}
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"] == "job-de-prueba"
    assert servicio.params["proc_uid"] == 100
    assert servicio.params["plc"] == "ZC_PLC_STD"


@pytest.mark.parametrize("ruta", ["procesos/preview", "procesos/sincronizar"])
def test_la_prevision_y_el_sync_de_un_proceso_sin_plc_responden_400(
    cliente: Any,
    ruta: str,
) -> None:
    respuesta = _encolar(cliente, ruta, {"proc_uid": 100})

    assert respuesta.status_code == 400
    assert "PLC" in respuesta.get_json()["error"]


@pytest.mark.parametrize("proc_uid", ["abc", [1], True, 0, -5, None])
@pytest.mark.parametrize("ruta", ["procesos/preview", "procesos/sincronizar"])
def test_la_prevision_y_el_sync_de_un_proceso_con_proc_uid_invalido_responden_400(
    cliente: Any,
    almacen: AlmacenExcel,
    excel_maestro: Path,
    monkeypatch: pytest.MonkeyPatch,
    ruta: str,
    proc_uid: Any,
) -> None:
    almacen.volcar(excel_maestro)
    modulo = importlib.import_module("zc_suite.areas.alimentacion.rutas")
    nucleo = importlib.import_module("zc_suite.nucleo.web.app")
    servicio = _ServicioConectado()
    monkeypatch.setattr(modulo, "servicio", lambda: servicio)
    monkeypatch.setattr(nucleo, "servicio", lambda: servicio)

    respuesta = _encolar(cliente, ruta, {"plc": "ZC_PLC_STD", "proc_uid": proc_uid})

    assert respuesta.status_code == 400, ruta
    assert "proceso" in respuesta.get_json()["error"].lower(), ruta


def test_sincronizar_un_proceso_sin_excel_responde_400(cliente: Any) -> None:
    respuesta = _encolar(
        cliente, "procesos/sincronizar", {"plc": "ZC_PLC_STD", "proc_uid": 100}
    )

    assert respuesta.status_code == 400
    assert "Excel" in respuesta.get_json()["error"]


def test_sincronizar_un_proceso_sin_conexion_con_tia_responde_400(
    cliente: Any,
    almacen: AlmacenExcel,
    excel_maestro: Path,
) -> None:
    almacen.volcar(excel_maestro)

    respuesta = _encolar(
        cliente, "procesos/sincronizar", {"plc": "ZC_PLC_STD", "proc_uid": 100}
    )

    assert respuesta.status_code == 400
    assert "TIA" in respuesta.get_json()["error"]


def test_las_rutas_de_procesos_sin_origin_se_rechazan(cliente: Any) -> None:
    for ruta in ("procesos/preview", "procesos/sincronizar"):
        respuesta = cliente.post(
            f"/api/v1/areas/alimentacion/{ruta}",
            json={"plc": "ZC_PLC_STD", "proc_uid": 100},
            base_url=BASE,
        )

        assert respuesta.status_code == 403, ruta


def test_subir_otro_excel_borra_la_prevision_de_un_proceso(
    app: Any,
    cliente: Any,
    eventos: list[tuple[str, dict[str, Any]]],
    excel_maestro: Path,
) -> None:
    """La prevision del proceso era del Excel anterior: deja de valer."""
    from zc_suite.areas.alimentacion.procesos import (
        CLAVE_PREVISION,
        CLAVE_PREVISION_CREAR,
    )
    from zc_suite.nucleo.sesion import CLAVE_SESION, Sesion

    sesion = Sesion()
    sesion.guardar_dato_area("alimentacion", CLAVE_PREVISION, {"plc": "ZC_PLC_STD"})
    sesion.guardar_dato_area("alimentacion", CLAVE_PREVISION_CREAR, {"plc": "ZC_PLC_STD"})
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
    datos = sesion.datos_area("alimentacion")
    assert CLAVE_PREVISION not in datos
    assert CLAVE_PREVISION_CREAR not in datos


# ── crear un proceso desde una plantilla ────────────────────────────────────


def _plantilla_en(
    raiz: Path,
    nombre: str,
    manifest: dict[str, Any] | None = None,
) -> Path:
    """Una subcarpeta de plantilla con su ``manifest.json`` (o sin el)."""
    dir_plantilla = raiz / nombre
    dir_plantilla.mkdir(parents=True)
    if manifest is not None:
        (dir_plantilla / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
    return dir_plantilla


def _carpeta_plantillas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
) -> Path:
    """Una carpeta de plantillas en un temporal, configurada en el area."""
    carpeta = tmp_path / "plantillas"
    carpeta.mkdir()
    modelo.plantillas_procesos = str(carpeta)
    return carpeta


def test_listar_plantillas_responde_200_con_las_plantillas(
    cliente: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
) -> None:
    carpeta = _carpeta_plantillas(tmp_path, monkeypatch, modelo)
    _plantilla_en(
        carpeta,
        "10000_BAS",
        {"base": 10000, "codigo": "BAS", "nombre": "Basica"},
    )
    _plantilla_en(
        carpeta,
        "50500_CIP1",
        {"base": 50500, "codigo": "CIP1", "nombre": "Principal"},
    )
    (carpeta / "60000_SIN_MANIFEST").mkdir()
    (carpeta / "basura.txt").write_bytes(b"x")

    respuesta = cliente.get(
        "/api/v1/areas/alimentacion/procesos/plantillas", base_url=BASE
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.get_json()
    assert [p["carpeta"] for p in cuerpo["plantillas"]] == [
        "10000_BAS",
        "50500_CIP1",
    ]
    assert cuerpo["aviso"] is None
    assert cuerpo["plantillas_path"] == str(carpeta)


def test_listar_plantillas_sin_configurar_responde_200_con_aviso(
    cliente: Any,
    tmp_path: Path,
) -> None:
    """La ruta esta vacia en el config: "sin configurar", sin tocar el disco."""
    carpeta = tmp_path / "plantillas"
    carpeta.mkdir()
    _plantilla_en(
        carpeta,
        "10000_BAS",
        {"base": 10000, "codigo": "BAS", "nombre": "Basica"},
    )

    respuesta = cliente.get(
        "/api/v1/areas/alimentacion/procesos/plantillas", base_url=BASE
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.get_json()
    assert cuerpo["plantillas"] == []
    assert "no esta configurada" in (cuerpo["aviso"] or "")
    assert cuerpo["plantillas_path"] == ""


def test_listar_plantillas_con_config_invalido_responde_400(
    cliente: Any,
    almacen: AlmacenExcel,
) -> None:
    almacen.config = None

    respuesta = cliente.get(
        "/api/v1/areas/alimentacion/procesos/plantillas", base_url=BASE
    )

    assert respuesta.status_code == 400
    assert "config" in respuesta.get_json()["error"]


# ── guardar la ruta de plantillas ───────────────────────────────────────────


def _callback_recarga(
    app: Any,
    ruta_config: Path,
    modelo: ConfigArea,
) -> Any:
    """El callback de recarga del PUT, sin remontar la app.

    Replica ``recargar_config_app`` (``nucleo/app/main.py``) menos el
    ``_montar_areas``: la blueprint del area ya esta registrada y Flask no
    permite registrarla dos veces. El refresco del area va directo al modelo
    compartido (``al_arrancar`` haria lo mismo sobre el ``ALMACEN`` del area,
    que en la app es el mismo objeto que el fixture del almacen).
    """

    def recargar(id_area: str, clave_area: str, valor: str) -> Path:
        datos = config_nucleo.leer_datos(ruta_config)
        seccion_area = datos.get("areas", {}).get(id_area)
        if not isinstance(seccion_area, dict):
            raise config_nucleo.ConfigError(
                f"El config.json en uso no tiene la seccion del area '{id_area}': "
                "es de otra version de la app y no se toca."
            )
        seccion_area[clave_area] = valor
        config_nucleo.escribir_config(ruta_config, datos)
        config_recargado = config_nucleo.cargar_config(ruta_config)
        app.config[CLAVE_CONFIG] = config_recargado
        seccion = config_recargado.seccion_area(
            id_area,
            area_alimentacion.defaults(config_recargado.areas.get(id_area, {})),
        )
        modelo.plantillas_procesos = seccion.get("plantillas_procesos", "")
        return ruta_config

    return recargar


def _seccion_del_repo() -> dict[str, Any]:
    """La seccion del area del config del repo, con la ruta vacia."""
    seccion = json.loads(
        (Path(__file__).resolve().parents[3] / "config" / "config.json").read_text(
            encoding="utf-8"
        )
    )["areas"]["alimentacion"]
    seccion["plantillas_procesos"] = ""
    return seccion


def _poner_config_de_prueba(
    app: Any,
    tmp_path: Path,
    modelo: ConfigArea,
) -> Path:
    """Un ``config.json`` en un temporal y la recarga en memoria."""
    carpeta_config = tmp_path / "config"
    carpeta_config.mkdir()
    ruta_config = carpeta_config / "config.json"
    ruta_config.write_text(
        json.dumps(
            {
                "paths": {"data": "data"},
                "areas": {
                    "alimentacion": {
                        **_seccion_del_repo(),
                        "otra_clave": "se conserva",
                    },
                    "otra_area": {"clave": "v"},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    app.config[CLAVE_CONFIG_EN_USO] = config_nucleo.ConfigEnUso(ruta_config, "prueba")
    app.config[CLAVE_RECARGA_CONFIG] = _callback_recarga(app, ruta_config, modelo)
    return ruta_config


def _poner_ruta_plantillas(cliente: Any, ruta: str) -> Any:
    return cliente.put(
        "/api/v1/areas/alimentacion/procesos/plantillas",
        json={"plantillas_path": ruta},
        base_url=BASE,
        headers={"Origin": BASE},
    )


def test_guardar_ruta_responde_200_y_actualiza_el_config(
    cliente: Any,
    tmp_path: Path,
    modelo: ConfigArea,
    app: Any,
) -> None:
    """El PUT escribe el config atomicamente y el GET lo ve sin reiniciar."""
    _poner_config_de_prueba(app, tmp_path, modelo)
    carpeta = tmp_path / "plantillas"
    carpeta.mkdir()
    _plantilla_en(carpeta, "10000_BAS", {"base": 10000, "codigo": "BAS", "nombre": "B"})

    respuesta = _poner_ruta_plantillas(cliente, str(carpeta))

    assert respuesta.status_code == 200
    cuerpo = respuesta.get_json()
    assert cuerpo["ok"] is True
    assert cuerpo["plantillas_path"] == str(carpeta)
    datos = json.loads((tmp_path / "config" / "config.json").read_text(encoding="utf-8"))
    assert datos["areas"]["alimentacion"]["plantillas_procesos"] == str(carpeta)
    # El resto del config no se toca.
    assert datos["areas"]["alimentacion"]["otra_clave"] == "se conserva"
    assert datos["areas"]["otra_area"] == {"clave": "v"}
    assert datos["paths"] == {"data": "data"}
    # La recarga llega hasta el area: el GET siguiente ve la carpeta.
    assert modelo.plantillas_procesos == str(carpeta)
    respuesta = cliente.get(
        "/api/v1/areas/alimentacion/procesos/plantillas", base_url=BASE
    )
    cuerpo = respuesta.get_json()
    assert respuesta.status_code == 200
    assert [p["carpeta"] for p in cuerpo["plantillas"]] == ["10000_BAS"]
    assert cuerpo["plantillas_path"] == str(carpeta)
    assert cuerpo["aviso"] is None


def test_guardar_ruta_vacia_resetea_a_sin_configurar(
    cliente: Any,
    tmp_path: Path,
    modelo: ConfigArea,
    app: Any,
) -> None:
    """La cadena vacia es un valor valido: la ruta vuelve a "sin configurar"."""
    ruta_config = _poner_config_de_prueba(app, tmp_path, modelo)
    (tmp_path / "plantillas").mkdir()
    _plantilla_en(
        tmp_path / "plantillas",
        "10000_BAS",
        {"base": 10000, "codigo": "BAS", "nombre": "B"},
    )
    _poner_ruta_plantillas(cliente, str(tmp_path / "plantillas"))

    respuesta = _poner_ruta_plantillas(cliente, "")

    assert respuesta.status_code == 200
    assert respuesta.get_json()["ok"] is True
    datos = json.loads(ruta_config.read_text(encoding="utf-8"))
    assert datos["areas"]["alimentacion"]["plantillas_procesos"] == ""
    assert modelo.plantillas_procesos == ""
    cuerpo = cliente.get(
        "/api/v1/areas/alimentacion/procesos/plantillas", base_url=BASE
    ).get_json()
    assert cuerpo["plantillas"] == []
    assert cuerpo["plantillas_path"] == ""
    assert "no esta configurada" in (cuerpo["aviso"] or "")


def test_guardar_ruta_con_body_no_valido_responde_400(
    cliente: Any,
    tmp_path: Path,
    app: Any,
) -> None:
    """Ni un body que no es dict ni un ``plantillas_path`` que no es str."""
    ruta_config = _poner_config_de_prueba(
        app, tmp_path, ConfigArea.model_construct()
    )

    sin_json = cliente.put(
        "/api/v1/areas/alimentacion/procesos/plantillas",
        data="[1, 2]",
        content_type="application/json",
        base_url=BASE,
        headers={"Origin": BASE},
    )
    assert sin_json.status_code == 400
    assert "JSON" in sin_json.get_json()["error"]

    sin_clave = cliente.put(
        "/api/v1/areas/alimentacion/procesos/plantillas",
        json={"otra": "x"},
        base_url=BASE,
        headers={"Origin": BASE},
    )
    assert sin_clave.status_code == 400
    assert "plantillas_path" in sin_clave.get_json()["error"]

    no_str = cliente.put(
        "/api/v1/areas/alimentacion/procesos/plantillas",
        json={"plantillas_path": 42},
        base_url=BASE,
        headers={"Origin": BASE},
    )
    assert no_str.status_code == 400
    assert "plantillas_path" in no_str.get_json()["error"]

    datos = json.loads(ruta_config.read_text(encoding="utf-8"))
    assert datos["areas"]["alimentacion"]["plantillas_procesos"] == ""


def test_guardar_ruta_sin_origen_responde_403(
    cliente: Any,
    tmp_path: Path,
    modelo: ConfigArea,
    app: Any,
) -> None:
    """Como toda la app: sin cabecera ``Origin`` no se modifica nada."""
    _poner_config_de_prueba(app, tmp_path, modelo)
    respuesta = cliente.put(
        "/api/v1/areas/alimentacion/procesos/plantillas",
        json={"plantillas_path": "x"},
        base_url=BASE,
    )
    assert respuesta.status_code == 403
    assert "Origin" in respuesta.get_json()["error"]


def test_guardar_ruta_sin_app_montada_responde_500(cliente: Any) -> None:
    """Sin el callback de recarga no hay forma de guardar: 500."""
    respuesta = _poner_ruta_plantillas(cliente, "x")
    assert respuesta.status_code == 500
    assert "no esta montada" in respuesta.get_json()["error"]


def test_guardar_ruta_sin_seccion_del_area_responde_500(
    cliente: Any,
    tmp_path: Path,
    modelo: ConfigArea,
    app: Any,
) -> None:
    """El config no tiene la seccion del area (otra version): no se toca."""
    carpeta_config = tmp_path / "config"
    carpeta_config.mkdir()
    ruta_config = carpeta_config / "config.json"
    ruta_config.write_text(
        json.dumps({"areas": {"otra_area": {}}}), encoding="utf-8"
    )
    app.config[CLAVE_CONFIG_EN_USO] = config_nucleo.ConfigEnUso(ruta_config, "prueba")
    app.config[CLAVE_RECARGA_CONFIG] = _callback_recarga(app, ruta_config, modelo)

    respuesta = _poner_ruta_plantillas(cliente, "x")

    assert respuesta.status_code == 500
    assert "no tiene la seccion del area" in respuesta.get_json()["error"]
    datos = json.loads(ruta_config.read_text(encoding="utf-8"))
    assert datos["areas"] == {"otra_area": {}}


def test_guardar_ruta_con_config_no_legible_responde_500(
    cliente: Any,
    tmp_path: Path,
    modelo: ConfigArea,
    app: Any,
) -> None:
    """El config no se puede leer: 500 y la app sigue respondiendo.

    El config es un directorio (no un fichero): la lectura de los datos
    crudos falla y no se escribe nada.
    """
    carpeta_config = tmp_path / "config"
    carpeta_config.mkdir()
    ruta_config = carpeta_config / "config.json"
    ruta_config.mkdir()
    app.config[CLAVE_CONFIG_EN_USO] = config_nucleo.ConfigEnUso(ruta_config, "prueba")
    app.config[CLAVE_RECARGA_CONFIG] = _callback_recarga(app, ruta_config, modelo)

    respuesta = _poner_ruta_plantillas(cliente, str(tmp_path / "plantillas"))

    assert respuesta.status_code == 500
    assert "no se pudo leer" in respuesta.get_json()["error"].lower()
    # La app no queda colgada: un GET sigue respondiendo.
    assert (
        cliente.get(
            "/api/v1/areas/alimentacion/procesos/plantillas", base_url=BASE
        ).status_code
        == 200
    )


def test_guardar_ruta_con_escritura_fallida_responde_500(
    cliente: Any,
    tmp_path: Path,
    modelo: ConfigArea,
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No se puede escribir el ``config.json`` (permisos, disco lleno): 500
    con el fallo de la escritura, el config previo queda intacto y la app
    sigue respondiendo (el GET no falla)."""
    ruta_config = _poner_config_de_prueba(app, tmp_path, modelo)
    contenido_previo = ruta_config.read_bytes()

    def _falla(*args: Any, **kwargs: Any) -> None:
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr("zc_suite.nucleo.app.config.os.replace", _falla)

    respuesta = _poner_ruta_plantillas(cliente, str(tmp_path / "plantillas"))

    error = respuesta.get_json()["error"]
    assert respuesta.status_code == 500
    # El mensaje es claro para el operario: donde fallaba y por que.
    assert "No se pudo escribir el config.json" in error
    assert str(ruta_config) in error
    assert "Read-only file system" in error
    # La escritura atomica no daño el config: sigue byte a byte como antes.
    assert ruta_config.read_bytes() == contenido_previo
    # El .tmp no queda suelto.
    assert not (tmp_path / "config" / "config.json.tmp").exists()
    # La app no queda colgada: un GET sigue respondiendo.
    assert (
        cliente.get(
            "/api/v1/areas/alimentacion/procesos/plantillas", base_url=BASE
        ).status_code
        == 200
    )


def test_crear_prevision_responde_202_y_encola_el_trabajo(
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

    respuesta = _encolar(
        cliente,
        "procesos/crear/preview",
        {
            "plc": "ZC_PLC_STD",
            "proc_uid": 100,
            "dir_plantilla_nombre": "50500_CIP1",
        },
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"] == "job-de-prueba"
    assert servicio.funcion is not None
    assert servicio.funcion.__name__ == "generar_prevision_crear"
    assert servicio.params["proc_uid"] == 100
    assert servicio.params["plc"] == "ZC_PLC_STD"
    assert servicio.params["dir_plantilla_nombre"] == "50500_CIP1"
    assert servicio.params["almacen"] is almacen
    assert servicio.params["config"] is almacen.config


def test_crear_aplicar_responde_202_y_encola_el_trabajo(
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

    respuesta = _encolar(
        cliente,
        "procesos/crear/aplicar",
        {
            "plc": "ZC_PLC_STD",
            "proc_uid": 100,
            "dir_plantilla_nombre": "50500_CIP1",
        },
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["job_id"] == "job-de-prueba"
    assert servicio.funcion is not None
    assert servicio.funcion.__name__ == "crear"
    assert servicio.params["proc_uid"] == 100
    assert servicio.params["plc"] == "ZC_PLC_STD"
    assert servicio.params["dir_plantilla_nombre"] == "50500_CIP1"
    assert servicio.params["almacen"] is almacen
    assert servicio.params["config"] is almacen.config


@pytest.mark.parametrize("ruta", ["procesos/crear/preview", "procesos/crear/aplicar"])
def test_crear_un_proceso_sin_plc_responde_400(cliente: Any, ruta: str) -> None:
    respuesta = _encolar(
        cliente, ruta, {"proc_uid": 100, "dir_plantilla_nombre": "50500_CIP1"}
    )

    assert respuesta.status_code == 400
    assert "PLC" in respuesta.get_json()["error"]


def test_crear_prevision_sin_excel_responde_400(cliente: Any) -> None:
    respuesta = _encolar(
        cliente,
        "procesos/crear/preview",
        {"plc": "ZC_PLC_STD", "proc_uid": 100, "dir_plantilla_nombre": "50500_CIP1"},
    )

    assert respuesta.status_code == 400
    assert "Excel" in respuesta.get_json()["error"]


def test_crear_aplicar_sin_excel_responde_400(cliente: Any) -> None:
    respuesta = _encolar(
        cliente,
        "procesos/crear/aplicar",
        {"plc": "ZC_PLC_STD", "proc_uid": 100, "dir_plantilla_nombre": "50500_CIP1"},
    )

    assert respuesta.status_code == 400
    assert "Excel" in respuesta.get_json()["error"]


def test_crear_prevision_sin_conexion_con_tia_responde_400(
    cliente: Any,
    almacen: AlmacenExcel,
    excel_maestro: Path,
) -> None:
    almacen.volcar(excel_maestro)

    respuesta = _encolar(
        cliente,
        "procesos/crear/preview",
        {"plc": "ZC_PLC_STD", "proc_uid": 100, "dir_plantilla_nombre": "50500_CIP1"},
    )

    assert respuesta.status_code == 400
    assert "TIA" in respuesta.get_json()["error"]


def test_crear_aplicar_sin_conexion_con_tia_responde_400(
    cliente: Any,
    almacen: AlmacenExcel,
    excel_maestro: Path,
) -> None:
    almacen.volcar(excel_maestro)

    respuesta = _encolar(
        cliente,
        "procesos/crear/aplicar",
        {"plc": "ZC_PLC_STD", "proc_uid": 100, "dir_plantilla_nombre": "50500_CIP1"},
    )

    assert respuesta.status_code == 400
    assert "TIA" in respuesta.get_json()["error"]


@pytest.mark.parametrize("proc_uid", ["abc", [1], True, 0, -5, None])
@pytest.mark.parametrize("ruta", ["procesos/crear/preview", "procesos/crear/aplicar"])
def test_crear_un_proceso_con_proc_uid_invalido_responde_400(
    cliente: Any,
    almacen: AlmacenExcel,
    excel_maestro: Path,
    monkeypatch: pytest.MonkeyPatch,
    ruta: str,
    proc_uid: Any,
) -> None:
    almacen.volcar(excel_maestro)
    modulo = importlib.import_module("zc_suite.areas.alimentacion.rutas")
    nucleo = importlib.import_module("zc_suite.nucleo.web.app")
    servicio = _ServicioConectado()
    monkeypatch.setattr(modulo, "servicio", lambda: servicio)
    monkeypatch.setattr(nucleo, "servicio", lambda: servicio)

    respuesta = _encolar(
        cliente,
        ruta,
        {"plc": "ZC_PLC_STD", "proc_uid": proc_uid, "dir_plantilla_nombre": "50500_CIP1"},
    )

    assert respuesta.status_code == 400, ruta
    assert "proceso" in respuesta.get_json()["error"].lower(), ruta


@pytest.mark.parametrize(
    "valor",
    [None, "", "   ", "../otro", "otro/sub", "otro\\sub", "a..b"],
    ids=["ausente", "vacio", "espacios", "dospuntos", "barras", "barras_inv", "puntos"],
)
@pytest.mark.parametrize("ruta", ["procesos/crear/preview", "procesos/crear/aplicar"])
def test_crear_un_proceso_con_dir_plantilla_invalido_responde_400(
    cliente: Any,
    almacen: AlmacenExcel,
    excel_maestro: Path,
    monkeypatch: pytest.MonkeyPatch,
    ruta: str,
    valor: Any,
) -> None:
    almacen.volcar(excel_maestro)
    modulo = importlib.import_module("zc_suite.areas.alimentacion.rutas")
    nucleo = importlib.import_module("zc_suite.nucleo.web.app")
    servicio = _ServicioConectado()
    monkeypatch.setattr(modulo, "servicio", lambda: servicio)
    monkeypatch.setattr(nucleo, "servicio", lambda: servicio)
    body: dict[str, Any] = {"plc": "ZC_PLC_STD", "proc_uid": 100}
    if valor is not None:
        body["dir_plantilla_nombre"] = valor

    respuesta = _encolar(cliente, ruta, body)

    assert respuesta.status_code == 400, ruta
    assert "plantilla" in respuesta.get_json()["error"].lower(), ruta


class _PortalFalso:
    """Un portal de TIA minimo, para que la conexion diga que va."""

    def get_process_id(self) -> int:
        return 4242

    def detach(self) -> None:
        pass


def test_crear_un_proceso_con_un_trabajo_en_curso_responde_409(
    app: Any,
    cliente: Any,
    almacen: AlmacenExcel,
    excel_maestro: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con un trabajo en curso, la ruta responde 409 (el shell lo bloquea)."""
    from zc_suite.nucleo.sesion import CLAVE_SESION, Sesion

    almacen.volcar(excel_maestro)
    servicio = app.config["ZC_TIA"]
    espera = threading.Event()

    def trabajo_lento(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo lento", ["uno"])
        with job.paso("uno"):
            espera.wait(10.0)
        return {}

    # La ruta comprueba la conexion antes de encolar: se deja un portal
    # en el servicio (lo que haria el trabajo de conectar) para llegar al
    # 409 del shell.
    monkeypatch.setattr(servicio, "_portal", _PortalFalso())
    sesion = Sesion()
    sesion.guardar_escaneo("ZC_PLC_STD", [], [], [])
    app.config[CLAVE_SESION] = sesion

    servicio.lanzar(trabajo_lento)
    try:
        respuesta = _encolar(
            cliente,
            "procesos/crear/preview",
            {
                "plc": "ZC_PLC_STD",
                "proc_uid": 100,
                "dir_plantilla_nombre": "50500_CIP1",
            },
        )
    finally:
        espera.set()

    assert respuesta.status_code == 409
