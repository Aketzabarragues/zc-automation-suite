"""Tests de las operaciones de proyecto."""

from __future__ import annotations

from pathlib import Path

import pytest

from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops import proyecto as ops

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
        self.guardado = False

    def get_plcs(self) -> list[PlcFalso]:
        return self.plcs

    def save(self) -> None:
        self.guardado = True


class PortalFalso:
    def __init__(self, proyecto: ProyectoFalso | None = None) -> None:
        self.proyecto = proyecto
        self.abiertos: list[str] = []

    def get_project(self) -> ProyectoFalso | None:
        return self.proyecto

    def open_project(self, project_file_path: str) -> None:
        self.abiertos.append(project_file_path)
        self.proyecto = ProyectoFalso()


# ── abrir y guardar ────────────────────────────────────────────────────────


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


def test_guardar_proyecto_guarda() -> None:
    proyecto = ProyectoFalso()
    portal = PortalFalso(proyecto)

    resultado = ops.guardar_proyecto(portal)

    assert resultado == {"guardado": True}
    assert proyecto.guardado is True


def test_guardar_proyecto_falla_sin_proyecto() -> None:
    portal = PortalFalso()

    with pytest.raises(OperacionError, match="No hay ningun proyecto abierto"):
        ops.guardar_proyecto(portal)


# ── resolucion del PLC y sus tablas ────────────────────────────────────────


def test_buscar_plc_por_nombre() -> None:
    plc = PlcFalso("PLC_1")
    portal = PortalFalso(ProyectoFalso([PlcFalso("OTRO"), plc]))

    assert ops._buscar_plc(portal, "PLC_1") is plc


def test_buscar_plc_falla_si_no_existe() -> None:
    portal = PortalFalso(ProyectoFalso([PlcFalso("PLC_1")]))

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        ops._buscar_plc(portal, "PLC_9")


def test_buscar_plc_falla_sin_nombre() -> None:
    portal = PortalFalso(ProyectoFalso())

    with pytest.raises(OperacionError, match="nombre del PLC"):
        ops._buscar_plc(portal, "")


def test_buscar_plc_tolera_un_nombre_ilegible() -> None:
    """Un PLC con el nombre corrupto no tumba la busqueda."""
    ilegible = PlcFalso(UnicodeDecodeError("utf-8", b"\x80", 0, 1, "invalido"))
    bueno = PlcFalso("PLC_1")
    portal = PortalFalso(ProyectoFalso([ilegible, bueno]))

    assert ops._buscar_plc(portal, "PLC_1") is bueno


def test_buscar_plc_falla_sin_proyecto() -> None:
    portal = PortalFalso()

    with pytest.raises(OperacionError, match="No hay ningun proyecto abierto"):
        ops._buscar_plc(portal, "PLC_1")


def test_buscar_tabla_tags_por_nombre() -> None:
    tabla = TablaFalsa("2000_Disp_ED")
    plc = PlcFalso("PLC_1", [TablaFalsa("otra"), tabla])

    assert ops._buscar_tabla_tags(plc, "2000_Disp_ED") is tabla


def test_buscar_tabla_tags_falla_si_no_existe() -> None:
    plc = PlcFalso("PLC_1", [TablaFalsa("otra")])

    with pytest.raises(OperacionError, match="no encontrada en el PLC"):
        ops._buscar_tabla_tags(plc, "2000_Disp_ED")


def test_buscar_tabla_tags_falla_sin_nombre() -> None:
    with pytest.raises(OperacionError, match="nombre de la tabla"):
        ops._buscar_tabla_tags(PlcFalso("PLC_1"), "")


def test_buscar_tabla_tags_tolera_un_nombre_ilegible() -> None:
    ilegible = TablaFalsa(UnicodeDecodeError("utf-8", b"\x80", 0, 1, "invalido"))
    buena = TablaFalsa("2000_Disp_ED")
    plc = PlcFalso("PLC_1", [ilegible, buena])

    assert ops._buscar_tabla_tags(plc, "2000_Disp_ED") is buena


def test_lo_publico_devuelve_solo_primitivos() -> None:
    """Ningun objeto .NET sale del modulo."""
    portal = PortalFalso(ProyectoFalso([PlcFalso("PLC_1")]))

    for resultado in (
        ops.guardar_proyecto(portal),
        ops.abrir_proyecto(portal, str(Path(__file__))),
    ):
        assert isinstance(resultado, dict)
        assert all(isinstance(valor, (str, int, bool, float)) for valor in resultado.values())


def test_el_error_de_operacion_es_un_tia_error() -> None:
    """Es un fallo esperado: se registra como warning, sin traceback."""
    from zc_suite.tia import TIAError

    assert issubclass(OperacionError, TIAError)
