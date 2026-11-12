"""Tests de las tablas de tags del PLC."""

from __future__ import annotations

import pytest

from zc_suite.errores import OperacionError
from zc_suite.tia_ops import tablas as ops


class TablaFalsa:
    def __init__(self, nombre: str, ruta: str = "") -> None:
        self._nombre = nombre
        self._ruta = ruta

    def get_name(self) -> str:
        return self._nombre

    def get_path(self) -> str:
        return self._ruta


class PlcFalso:
    def __init__(self, tablas: list[TablaFalsa] | None = None) -> None:
        self.tablas = tablas or []

    def get_name(self) -> str:
        return "ZC_PLC_STD"

    def get_plc_tag_tables(self) -> list[TablaFalsa]:
        return self.tablas


class ProyectoFalso:
    def __init__(self, plc: PlcFalso) -> None:
        self.plc = plc

    def get_plcs(self) -> list[PlcFalso]:
        return [self.plc]


class PortalFalso:
    def __init__(self, plc: PlcFalso | None = None) -> None:
        self.proyecto = ProyectoFalso(plc) if plc is not None else None

    def get_project(self) -> ProyectoFalso | None:
        return self.proyecto


def test_escanear_tablas_devuelve_nombre_y_ruta() -> None:
    plc = PlcFalso([TablaFalsa("2000_Disp_ED", "0_Sistema"), TablaFalsa("0_Config")])
    portal = PortalFalso(plc)

    resultado = ops.escanear_tablas_tags(portal, "ZC_PLC_STD")

    assert resultado == [
        {"nombre": "2000_Disp_ED", "ruta": "0_Sistema"},
        {"nombre": "0_Config", "ruta": ""},
    ]


def test_escanear_tablas_de_un_plc_sin_tablas() -> None:
    portal = PortalFalso(PlcFalso([]))

    assert ops.escanear_tablas_tags(portal, "ZC_PLC_STD") == []


def test_escanear_tablas_falla_si_el_plc_no_existe() -> None:
    portal = PortalFalso(PlcFalso([]))

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        ops.escanear_tablas_tags(portal, "OTRO")


def test_lo_publico_devuelve_solo_primitivos() -> None:
    portal = PortalFalso(PlcFalso([TablaFalsa("2000_Disp_ED")]))

    resultado = ops.escanear_tablas_tags(portal, "ZC_PLC_STD")

    assert all(isinstance(valor, str) for valor in resultado[0].values())
