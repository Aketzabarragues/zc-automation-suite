"""Tests de la apertura del proyecto de TIA Portal y de sus PLCs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from zc_suite.nucleo.tia.errores import SinProyectoError
from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops import proyecto as ops


class PortalFalso:
    """Doble minimo del portal de TIA."""

    def __init__(self, proyecto: Any = None) -> None:
        self.abiertos: list[str] = []
        self._proyecto = proyecto

    def open_project(self, project_file_path: str) -> None:
        self.abiertos.append(project_file_path)

    def get_project(self) -> Any:
        return self._proyecto


class ProyectoFalso:
    """Proyecto de TIA con sus PLCs."""

    def __init__(self, plcs: list[Any] | None = None) -> None:
        self.plcs = plcs or []
        self.propiedades = {
            "Name": "ZC_PLC_STD",
            "Path": "D:\\Proyectos\\ZC_PLC_STD.ap21",
        }

    def get_plcs(self) -> list[Any]:
        return self.plcs

    def get_property(self, name: str) -> Any:
        return self.propiedades.get(name)


class PlcFalso:
    def __init__(self, nombre: str, designacion: str = "") -> None:
        self._nombre = nombre
        self._designacion = designacion

    def get_name(self) -> str:
        return self._nombre

    def get_property(self, name: str) -> Any:
        if name == "ShortDesignation":
            return self._designacion
        return None


def test_abrir_proyecto_devuelve_la_ruta(tmp_path: Path) -> None:
    proyecto = tmp_path / "PRUEBA.ap18"
    proyecto.write_text("x", encoding="utf-8")
    portal = PortalFalso()

    resultado = ops.abrir_proyecto(portal, str(proyecto))

    assert resultado == {"abierto": True, "ruta": str(proyecto)}
    assert portal.abiertos == [str(proyecto)]


def test_abrir_proyecto_falla_si_el_fichero_no_existe(tmp_path: Path) -> None:
    portal = PortalFalso()

    with pytest.raises(OperacionError, match="no existe"):
        ops.abrir_proyecto(portal, str(tmp_path / "NO_EXISTE.ap18"))


def test_abrir_proyecto_falla_sin_ruta() -> None:
    portal = PortalFalso()

    with pytest.raises(OperacionError, match="ruta del proyecto"):
        ops.abrir_proyecto(portal, "")


def test_lo_publico_devuelve_solo_primitivos(tmp_path: Path) -> None:
    """Ningun objeto .NET sale del modulo."""
    proyecto = tmp_path / "PRUEBA.ap18"
    proyecto.write_text("x", encoding="utf-8")
    portal = PortalFalso()

    resultado = ops.abrir_proyecto(portal, str(proyecto))

    assert isinstance(resultado, dict)
    assert all(isinstance(valor, (str, int, bool, float)) for valor in resultado.values())


def test_no_hay_guardar_proyecto() -> None:
    """La politica es que el operario guarda a mano."""
    assert not hasattr(ops, "guardar_proyecto")


# ── listar los PLCs ────────────────────────────────────────────────────────


def test_listar_plcs_devuelve_nombre_y_designacion() -> None:
    proyecto = ProyectoFalso([PlcFalso("ZC_PLC_STD", "CPU 1516-3"), PlcFalso("OTRO")])
    portal = PortalFalso(proyecto)

    resultado = ops.listar_plcs(portal)

    assert resultado == [
        {"nombre": "ZC_PLC_STD", "designacion": "CPU 1516-3"},
        {"nombre": "OTRO", "designacion": ""},
    ]


def test_listar_plcs_normaliza_el_no_value() -> None:
    """El SDK devuelve 'no value' cuando la designacion no existe."""
    proyecto = ProyectoFalso([PlcFalso("ZC_PLC_STD", "no value")])
    portal = PortalFalso(proyecto)

    assert ops.listar_plcs(portal)[0]["designacion"] == ""


def test_listar_plcs_falla_si_no_hay_proyecto() -> None:
    portal = PortalFalso(None)

    with pytest.raises(SinProyectoError, match="No hay ningun proyecto abierto"):
        ops.listar_plcs(portal)


# ── los datos del proyecto ─────────────────────────────────────────────────


def test_info_proyecto_devuelve_el_nombre_y_la_ruta() -> None:
    portal = PortalFalso(ProyectoFalso())

    resultado = ops.info_proyecto(portal)

    assert resultado == {
        "nombre": "ZC_PLC_STD",
        "ruta": "D:\\Proyectos\\ZC_PLC_STD.ap21",
    }


def test_info_proyecto_falla_si_no_hay_proyecto() -> None:
    portal = PortalFalso(None)

    with pytest.raises(SinProyectoError):
        ops.info_proyecto(portal)
