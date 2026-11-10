"""Tests de la exportacion del PLC a disco."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops import exportar as ops

# ── dobles de test ─────────────────────────────────────────────────────────


class BloqueFalso:
    def __init__(self, nombre: str | None, formatos: list[str] | None = None) -> None:
        self._nombre = nombre
        self.formatos = formatos
        self.exportado: dict[str, Any] | None = None

    def get_name(self) -> str | None:
        if isinstance(self._nombre, Exception):
            raise self._nombre
        return self._nombre

    def get_supported_export_format(self) -> list[str]:
        return self.formatos or []

    def export(self, **kwargs: Any) -> None:
        self.exportado = kwargs


class TablaFalsa:
    def __init__(self, nombre: str | None) -> None:
        self._nombre = nombre
        self.exportado: dict[str, Any] | None = None

    def get_name(self) -> str | None:
        if isinstance(self._nombre, Exception):
            raise self._nombre
        return self._nombre

    def export(self, **kwargs: Any) -> None:
        self.exportado = kwargs


class PlcFalso:
    def __init__(
        self,
        bloques: list[BloqueFalso] | None = None,
        tablas: list[TablaFalsa] | None = None,
        nombre: str = "PLC_1",
    ) -> None:
        self.bloques = bloques or []
        self.tablas = tablas or []
        self.nombre = nombre

    def get_name(self) -> str:
        return self.nombre

    def get_program_blocks(self) -> list[BloqueFalso]:
        return self.bloques

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


def _portal(bloques=None, tablas=None) -> tuple[PortalFalso, PlcFalso]:
    plc = PlcFalso(bloques, tablas)
    return PortalFalso(plc), plc


# ── bloques ────────────────────────────────────────────────────────────────


def test_exportar_bloques_exporta_todos(tmp_path: Path) -> None:
    portal, _plc = _portal([BloqueFalso("DB2000_ED"), BloqueFalso("FB2017")])

    resultado = ops.exportar_bloques(portal, "PLC_1", tmp_path)

    assert resultado["cantidad"] == 2
    assert resultado["nombres"] == ["DB2000_ED", "FB2017"]
    assert resultado["omitidos"] == []
    assert resultado["exportado_a"] == str(tmp_path)


def test_exportar_bloques_respeta_la_lista(tmp_path: Path) -> None:
    portal, _plc = _portal([BloqueFalso("DB2000_ED"), BloqueFalso("FB2017")])

    resultado = ops.exportar_bloques(portal, "PLC_1", tmp_path, ["DB2000_ED"])

    assert resultado["cantidad"] == 1
    assert resultado["nombres"] == ["DB2000_ED"]


def test_exportar_bloques_informa_de_los_omitidos(tmp_path: Path) -> None:
    portal, _plc = _portal([BloqueFalso("DB2000_ED")])

    resultado = ops.exportar_bloques(portal, "PLC_1", tmp_path, ["DB2000_ED", "NO_EXISTE"])

    assert resultado["omitidos"] == ["NO_EXISTE"]


def test_exportar_bloques_usa_simatic_sd(tmp_path: Path) -> None:
    portal, plc = _portal([BloqueFalso("DB2000_ED")])

    ops.exportar_bloques(portal, "PLC_1", tmp_path)

    assert plc.bloques[0].exportado is not None
    assert plc.bloques[0].exportado["export_format"] == "SimaticSD"


def test_exportar_bloques_consulta_el_formato_soportado(tmp_path: Path) -> None:
    """El formato se consulta, no se supone."""
    portal, plc = _portal([BloqueFalso("DB2000_ED", ["SimaticML", "SimaticSD"])])

    ops.exportar_bloques(portal, "PLC_1", tmp_path)

    assert plc.bloques[0].exportado is not None
    assert plc.bloques[0].exportado["export_format"] == "SimaticSD"


def test_exportar_bloques_falla_si_no_admite_simatic_sd(tmp_path: Path) -> None:
    portal, _plc = _portal([BloqueFalso("DB2000_ED", ["SimaticML"])])

    with pytest.raises(OperacionError, match="no admite exportacion SimaticSD"):
        ops.exportar_bloques(portal, "PLC_1", tmp_path)


def test_exportar_bloques_salta_un_bloque_ilegible(tmp_path: Path) -> None:
    portal, _plc = _portal(
        [
            BloqueFalso(UnicodeDecodeError("utf-8", b"\x80", 0, 1, "invalido")),
            BloqueFalso("DB2000_ED"),
        ]
    )

    resultado = ops.exportar_bloques(portal, "PLC_1", tmp_path)

    assert resultado["nombres"] == ["DB2000_ED"]


def test_exportar_bloques_crea_el_destino(tmp_path: Path) -> None:
    portal, _plc = _portal([BloqueFalso("DB2000_ED")])
    destino = tmp_path / "preview" / "bloques"

    ops.exportar_bloques(portal, "PLC_1", destino)

    assert destino.is_dir()


def test_exportar_bloques_pasa_el_layout(tmp_path: Path) -> None:
    portal, plc = _portal([BloqueFalso("DB2000_ED")])

    ops.exportar_bloques(portal, "PLC_1", tmp_path, mantener_estructura=True)

    assert plc.bloques[0].exportado is not None
    assert plc.bloques[0].exportado["keep_folder_structure"] is True


def test_exportar_bloques_falla_si_el_plc_no_existe(tmp_path: Path) -> None:
    portal, _plc = _portal()

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        ops.exportar_bloques(portal, "PLC_9", tmp_path)


# ── tablas de tags ────────────────────────────────────────────────────────


def test_exportar_tablas_exporta_todas(tmp_path: Path) -> None:
    portal, _plc = _portal(tablas=[TablaFalsa("2000_Disp_ED"), TablaFalsa("0_Sistema")])

    resultado = ops.exportar_tablas(portal, "PLC_1", tmp_path, mantener_estructura=True)

    assert resultado["cantidad"] == 2
    assert resultado["nombres"] == ["2000_Disp_ED", "0_Sistema"]


def test_exportar_tablas_respeta_la_lista(tmp_path: Path) -> None:
    portal, _plc = _portal(tablas=[TablaFalsa("2000_Disp_ED"), TablaFalsa("0_Sistema")])

    resultado = ops.exportar_tablas(
        portal, "PLC_1", tmp_path, ["2000_Disp_ED"], mantener_estructura=True
    )

    assert resultado["nombres"] == ["2000_Disp_ED"]


def test_exportar_tablas_no_pasa_el_formato(tmp_path: Path) -> None:
    """Las tablas de tags no aceptan export_format: el wrapper escribe XML."""
    portal, plc = _portal(tablas=[TablaFalsa("2000_Disp_ED")])

    ops.exportar_tablas(portal, "PLC_1", tmp_path, mantener_estructura=True)

    exportado = plc.tablas[0].exportado
    assert exportado is not None
    assert "export_format" not in exportado


def test_exportar_tablas_pasa_el_layout(tmp_path: Path) -> None:
    portal, plc = _portal(tablas=[TablaFalsa("2000_Disp_ED")])

    ops.exportar_tablas(portal, "PLC_1", tmp_path, mantener_estructura=False)

    exportado = plc.tablas[0].exportado
    assert exportado is not None
    assert exportado["keep_folder_structure"] is False


def test_el_layout_de_las_tablas_es_obligatorio(tmp_path: Path) -> None:
    """Sin el layout explicito, el XML sale plano y al reimportar se crea."""
    portal, _plc = _portal(tablas=[TablaFalsa("2000_Disp_ED")])

    with pytest.raises(TypeError):
        ops.exportar_tablas(portal, "PLC_1", tmp_path)  # type: ignore[call-arg]


def test_exportar_tablas_informa_de_los_omitidos(tmp_path: Path) -> None:
    portal, _plc = _portal(tablas=[TablaFalsa("2000_Disp_ED")])

    resultado = ops.exportar_tablas(
        portal, "PLC_1", tmp_path, ["2000_Disp_ED", "NO_EXISTE"], mantener_estructura=True
    )

    assert resultado["omitidos"] == ["NO_EXISTE"]


def test_exportar_tablas_falla_si_el_plc_no_existe(tmp_path: Path) -> None:
    portal, _plc = _portal()

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        ops.exportar_tablas(portal, "PLC_9", tmp_path, mantener_estructura=True)


def test_lo_publico_devuelve_solo_primitivos(tmp_path: Path) -> None:
    portal, _plc = _portal([BloqueFalso("DB2000_ED")], [TablaFalsa("2000_Disp_ED")])

    for resultado in (
        ops.exportar_bloques(portal, "PLC_1", tmp_path),
        ops.exportar_tablas(portal, "PLC_1", tmp_path, mantener_estructura=True),
    ):
        assert isinstance(resultado, dict)
        assert isinstance(resultado["nombres"], list)
        assert isinstance(resultado["exportado_a"], str)
