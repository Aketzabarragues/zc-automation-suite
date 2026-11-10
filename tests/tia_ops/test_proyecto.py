"""Tests de la apertura del proyecto de TIA Portal."""

from __future__ import annotations

from pathlib import Path

import pytest

from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops import proyecto as ops


class PortalFalso:
    """Doble minimo del portal de TIA."""

    def __init__(self) -> None:
        self.abiertos: list[str] = []

    def open_project(self, project_file_path: str) -> None:
        self.abiertos.append(project_file_path)


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
