"""Tests de la resolucion de objetos dentro del portal."""

from __future__ import annotations

import pytest

from zc_suite.errores import OperacionError
from zc_suite.nucleo.tia.errores import SinProyectoError
from zc_suite.tia_ops import _resolver as resolver

# ── dobles de test ─────────────────────────────────────────────────────────


class TablaFalsa:
    def __init__(self, nombre: str | None) -> None:
        self._nombre = nombre

    def get_name(self) -> str | None:
        if isinstance(self._nombre, Exception):
            raise self._nombre
        return self._nombre


class PlcFalso:
    def __init__(self, nombre: str | None, tablas: list[TablaFalsa] | None = None) -> None:
        self._nombre = nombre
        self.tablas = tablas or []

    def get_name(self) -> str | None:
        if isinstance(self._nombre, Exception):
            raise self._nombre
        return self._nombre

    def get_plc_tag_tables(self) -> list[TablaFalsa]:
        return self.tablas


class ProyectoFalso:
    def __init__(self, plcs: list[PlcFalso] | None = None) -> None:
        self.plcs = plcs or []

    def get_plcs(self) -> list[PlcFalso]:
        return self.plcs


class PortalFalso:
    def __init__(self, proyecto: ProyectoFalso | None = None) -> None:
        self.proyecto = proyecto

    def get_project(self) -> ProyectoFalso | None:
        return self.proyecto


# ── PLC ────────────────────────────────────────────────────────────────────


def test_buscar_plc_por_nombre() -> None:
    plc = PlcFalso("PLC_1")
    portal = PortalFalso(ProyectoFalso([PlcFalso("OTRO"), plc]))

    assert resolver.buscar_plc(portal, "PLC_1") is plc


def test_buscar_plc_falla_si_no_existe() -> None:
    portal = PortalFalso(ProyectoFalso([PlcFalso("PLC_1")]))

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        resolver.buscar_plc(portal, "PLC_9")


def test_buscar_plc_falla_sin_nombre() -> None:
    portal = PortalFalso(ProyectoFalso())

    with pytest.raises(OperacionError, match="nombre del PLC"):
        resolver.buscar_plc(portal, "")


def test_buscar_plc_tolera_un_nombre_ilegible() -> None:
    """Un PLC con el nombre corrupto no tumba la busqueda."""
    ilegible = PlcFalso(UnicodeDecodeError("utf-8", b"\x80", 0, 1, "invalido"))
    bueno = PlcFalso("PLC_1")
    portal = PortalFalso(ProyectoFalso([ilegible, bueno]))

    assert resolver.buscar_plc(portal, "PLC_1") is bueno


def test_buscar_plc_sin_proyecto_lanza_sin_proyecto() -> None:
    portal = PortalFalso()

    with pytest.raises(SinProyectoError, match="No hay ningun proyecto abierto"):
        resolver.buscar_plc(portal, "PLC_1")


# ── tablas de tags ─────────────────────────────────────────────────────────


def test_buscar_tabla_tags_por_nombre() -> None:
    tabla = TablaFalsa("2000_Disp_ED")
    plc = PlcFalso("PLC_1", [TablaFalsa("otra"), tabla])

    assert resolver.buscar_tabla_tags(plc, "2000_Disp_ED") is tabla


def test_buscar_tabla_tags_falla_si_no_existe() -> None:
    plc = PlcFalso("PLC_1", [TablaFalsa("otra")])

    with pytest.raises(OperacionError, match="no encontrada en el PLC"):
        resolver.buscar_tabla_tags(plc, "2000_Disp_ED")


def test_buscar_tabla_tags_falla_sin_nombre() -> None:
    with pytest.raises(OperacionError, match="nombre de la tabla"):
        resolver.buscar_tabla_tags(PlcFalso("PLC_1"), "")


def test_buscar_tabla_tags_tolera_un_nombre_ilegible() -> None:
    ilegible = TablaFalsa(UnicodeDecodeError("utf-8", b"\x80", 0, 1, "invalido"))
    buena = TablaFalsa("2000_Disp_ED")
    plc = PlcFalso("PLC_1", [ilegible, buena])

    assert resolver.buscar_tabla_tags(plc, "2000_Disp_ED") is buena
