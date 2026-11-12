"""Tests de la prevision de dispositivos: el diff y sus precondiciones.

El diff son funciones puras: se prueban con un XML exportado a mano, sin
TIA. Las precondiciones se prueban por la ruta.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from zc_suite.areas.alimentacion.dispositivos.prevision import (
    disp_calcular_diff_n_max,
    disp_calcular_diff_tabla,
)
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.rutas import rutas
from zc_suite.nucleo.tia.servicio import ServicioTIA


def _xml(constantes: list[tuple[str, str]]) -> str:
    """Un XML de tabla de tags con las constantes dadas."""
    partes = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<Document>",
        '  <SW.Tags.PlcTagTable ID="0">',
        "    <ObjectList>",
    ]
    for indice, (nombre, valor) in enumerate(constantes, start=1):
        partes.append(
            f'      <SW.Tags.PlcUserConstant ID="{indice}">\n'
            f"        <AttributeList><Name>{nombre}</Name>"
            f"<Value>{valor}</Value></AttributeList>\n"
            "      </SW.Tags.PlcUserConstant>"
        )
    partes += ["    </ObjectList>", "  </SW.Tags.PlcTagTable>", "</Document>", ""]
    return "\n".join(partes)


def _dispositivo(numero: int, plc_tag: str) -> dict[str, Any]:
    """Un dispositivo del Excel, con los campos que usa el diff."""
    return {"numero": numero, "plc_tag": plc_tag, "plc_name": "PLC1"}


# ── el diff de dispositivos ─────────────────────────────────────────────────


def test_sin_cambios_no_hay_nada_que_aplicar(tmp_path: Path) -> None:
    """Lo mismo en TIA y en el Excel: el diff esta vacio."""
    xml = tmp_path / "2000_Disp_ED.xml"
    xml.write_text(_xml([("ED_001", "1"), ("ED_002", "2")]), encoding="utf-8")

    diff = disp_calcular_diff_tabla(
        "2000_Disp_ED",
        [_dispositivo(1, "ED_001"), _dispositivo(2, "ED_002")],
        xml,
    )

    assert diff.agregados == []
    assert diff.eliminados == []
    assert diff.renombrados == {}
    assert diff.vacio is True
    assert diff.total_cambios == 0
    assert diff.xml_ausente is False


def test_un_alta_es_un_numero_que_no_esta_en_tia(tmp_path: Path) -> None:
    """El numero 3 esta en el Excel y no en TIA: es un alta."""
    xml = tmp_path / "2000_Disp_ED.xml"
    xml.write_text(_xml([("ED_001", "1"), ("ED_002", "2")]), encoding="utf-8")

    diff = disp_calcular_diff_tabla(
        "2000_Disp_ED",
        [_dispositivo(1, "ED_001"), _dispositivo(2, "ED_002"), _dispositivo(3, "ED_003")],
        xml,
    )

    assert diff.agregados == ["3"]
    assert diff.eliminados == []
    assert diff.renombrados == {}
    assert diff.total_cambios == 1


def test_una_baja_es_un_numero_que_solo_esta_en_tia(tmp_path: Path) -> None:
    """El numero 2 esta en TIA y no en el Excel: es una baja."""
    xml = tmp_path / "2000_Disp_ED.xml"
    xml.write_text(_xml([("ED_001", "1"), ("ED_002", "2")]), encoding="utf-8")

    diff = disp_calcular_diff_tabla(
        "2000_Disp_ED",
        [_dispositivo(1, "ED_001")],
        xml,
    )

    assert diff.agregados == []
    assert diff.eliminados == ["2"]
    assert diff.renombrados == {}
    assert diff.vacio is False


def test_un_renombrado_es_el_mismo_numero_con_otro_tag(tmp_path: Path) -> None:
    """El numero 1 tiene otro tag en el Excel: es un renombrado."""
    xml = tmp_path / "2000_Disp_ED.xml"
    xml.write_text(_xml([("ED_001", "1")]), encoding="utf-8")

    diff = disp_calcular_diff_tabla(
        "2000_Disp_ED",
        [_dispositivo(1, "V_ED_001")],
        xml,
    )

    assert diff.agregados == []
    assert diff.eliminados == []
    assert diff.renombrados == {"1": ("ED_001", "V_ED_001")}
    assert diff.total_cambios == 1


def test_el_xml_que_no_existe_no_rompe(tmp_path: Path) -> None:
    """Si el XML no esta, el diff lo dice en vez de inventar el estado."""
    diff = disp_calcular_diff_tabla(
        "2000_Disp_ED",
        [_dispositivo(1, "ED_001")],
        tmp_path / "no_existe.xml",
    )

    assert diff.xml_ausente is True
    assert diff.base == {}
    assert diff.agregados == ["1"]


# ── el diff de los N_MAX ────────────────────────────────────────────────────


def test_un_n_max_distinto_se_marca_para_actualizar(tmp_path: Path) -> None:
    """El N_MAX de TIA no es el del Excel: sale como ``actualizar``."""
    xml = tmp_path / "0_Config_Dispositivos.xml"
    xml.write_text(_xml([("N_MAX_DISP_ED", "10"), ("N_MAX_DISP_EA", "20")]), encoding="utf-8")

    diff = disp_calcular_diff_n_max(
        "0_Config_Dispositivos",
        {"N_MAX_DISP_ED": 10, "N_MAX_DISP_EA": 25},
        xml,
    )

    estados = {fila["name"]: fila["status"] for fila in diff.todos}
    assert estados == {
        "N_MAX_DISP_ED": "sin_cambios",
        "N_MAX_DISP_EA": "actualizar",
    }
    assert diff.resumen == {"actualizar": 1, "sin_cambios": 1, "total": 2}
    assert diff.xml_ausente is False


def test_el_n_max_que_no_cambia_no_aparece(tmp_path: Path) -> None:
    """Sin cambios, el resumen lo dice y no hay nada que actualizar."""
    xml = tmp_path / "0_Config_Dispositivos.xml"
    xml.write_text(_xml([("N_MAX_DISP_ED", "10")]), encoding="utf-8")

    diff = disp_calcular_diff_n_max("0_Config_Dispositivos", {"N_MAX_DISP_ED": 10}, xml)

    assert diff.resumen == {"actualizar": 0, "sin_cambios": 1, "total": 1}


def test_el_n_max_sin_xml_no_falla(tmp_path: Path) -> None:
    """Sin el XML de los N_MAX, todos quedan sin cambios y se avisa."""
    diff = disp_calcular_diff_n_max(
        "0_Config_Dispositivos",
        {"N_MAX_DISP_ED": 10},
        tmp_path / "no_existe.xml",
    )

    assert diff.xml_ausente is True
    assert diff.actual == {}
    assert diff.resumen == {"actualizar": 0, "sin_cambios": 1, "total": 1}


# ── las precondiciones ─────────────────────────────────────────────────────


class _ServicioFalso:
    """Un hilo de TIA sin conexion."""

    def __init__(self, conectado: bool) -> None:
        self.conectado = conectado


@pytest.fixture
def cliente() -> Any:
    """Un cliente de la app con el area montada y sin conexion con TIA."""
    from zc_suite.nucleo.tia.eventos import BusEventos
    from zc_suite.nucleo.web.app import crear_app

    bus = BusEventos()
    servicio = ServicioTIA(publicador=bus.publicar, cargador=lambda: None)
    app = crear_app(servicio, bus)
    app.config["TESTING"] = True
    app.register_blueprint(rutas)
    almacen = AlmacenExcel()
    app.config["ZC_ALMACEN_ALIMENTACION"] = almacen
    return app.test_client(), almacen


def _con_excel(almacen: AlmacenExcel, monkeypatch: pytest.MonkeyPatch) -> None:
    """Deja el almacen con un Excel cargado (sin tocar el disco)."""
    estado = {
        "cargado": True,
        "archivo": "maestro.xlsx",
        "cargado_en": "2026-11-11T10:00:00",
        "plcs": [{"uid": 1, "plc": "ZC_PLC_STD"}],
        "configuracion": {"columnas": [], "filas": []},
        "dispositivos": [],
        "procesos": {},
        "entidades": {"columnas": [], "filas": []},
        "avisos": [],
    }
    monkeypatch.setattr(almacen, "estado", lambda: dict(estado))


def test_sin_plc_no_se_lanza_el_trabajo(cliente: Any) -> None:
    """Sin PLC elegido, la respuesta es un mensaje claro y no hay trabajo."""
    cliente_app, _almacen = cliente

    respuesta = cliente_app.post(
        "/api/v1/areas/alimentacion/dispositivos/preview",
        json={},
        base_url="http://localhost:9484",
        headers={"Origin": "http://localhost:9484"},
    )

    assert respuesta.status_code == 400
    assert "PLC" in respuesta.get_json()["error"]


def test_sin_excel_no_se_lanza_el_trabajo(cliente: Any) -> None:
    """Sin Excel cargado, la respuesta es un mensaje claro y no hay trabajo."""
    cliente_app, _almacen = cliente

    respuesta = cliente_app.post(
        "/api/v1/areas/alimentacion/dispositivos/preview",
        json={"plc": "ZC_PLC_STD"},
        base_url="http://localhost:9484",
        headers={"Origin": "http://localhost:9484"},
    )

    assert respuesta.status_code == 400
    assert "Excel" in respuesta.get_json()["error"]


def test_sin_tia_conectado_no_se_lanza_el_trabajo(
    cliente: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con Excel pero sin conexion con TIA, el aviso es el de TIA."""
    cliente_app, almacen = cliente
    _con_excel(almacen, monkeypatch)
    modulo = importlib.import_module("zc_suite.areas.alimentacion.rutas")
    monkeypatch.setattr(modulo, "servicio", lambda: _ServicioFalso(conectado=False))

    respuesta = cliente_app.post(
        "/api/v1/areas/alimentacion/dispositivos/preview",
        json={"plc": "ZC_PLC_STD"},
        base_url="http://localhost:9484",
        headers={"Origin": "http://localhost:9484"},
    )

    assert respuesta.status_code == 400
    assert "TIA" in respuesta.get_json()["error"]
