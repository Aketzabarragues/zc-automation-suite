"""Tests de la importacion del disco al PLC."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops import importar as ops

# ── dobles de test ─────────────────────────────────────────────────────────


class TablaFalsa:
    def __init__(self, nombre: str | None) -> None:
        self._nombre = nombre

    def get_name(self) -> str | None:
        return self._nombre


class PlcFalso:
    def __init__(self, tablas: list[TablaFalsa] | None = None) -> None:
        self.tablas = tablas or []
        self.importaciones: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def get_name(self) -> str:
        return "PLC_1"

    def get_plc_tag_tables(self) -> list[TablaFalsa]:
        return self.tablas

    def import_blocks(self, **kwargs: Any) -> None:
        self.importaciones.append(kwargs)
        if self.error is not None:
            raise self.error

    def import_plc_tags(self, **kwargs: Any) -> None:
        self.importaciones.append(kwargs)
        if self.error is not None:
            raise self.error


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


def _portal() -> tuple[PortalFalso, PlcFalso]:
    plc = PlcFalso([TablaFalsa("2000_Disp_ED")])
    return PortalFalso(plc), plc


@pytest.fixture
def origen(tmp_path: Path) -> Path:
    carpeta = tmp_path / "importar"
    (carpeta / "2000_Dispositivos").mkdir(parents=True)
    (carpeta / "2000_Dispositivos" / "2000_Disp_ED.xml").write_text("<xml/>", encoding="utf-8")
    return carpeta


# ── bloques ────────────────────────────────────────────────────────────────


def test_importar_bloques_sin_carpeta_no_manda_el_argumento(origen: Path) -> None:
    """Sin carpeta destino, NO se pasa target_folder_path (rompe el UPDATE)."""
    portal, plc = _portal()

    resultado = ops.importar_bloques(portal, "PLC_1", origen)

    assert resultado["importado_de"] == str(origen)
    assert resultado["carpeta_destino"] == ""
    assert plc.importaciones == [{"import_root_directory": str(origen)}]


def test_importar_bloques_con_carpeta_la_manda(origen: Path) -> None:
    portal, plc = _portal()

    ops.importar_bloques(portal, "PLC_1", origen, "2000_Dispositivos")

    assert plc.importaciones == [
        {
            "import_root_directory": str(origen),
            "target_folder_path": "2000_Dispositivos",
        }
    ]


def test_importar_bloques_falla_si_el_plc_no_existe(origen: Path) -> None:
    portal, _plc = _portal()

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        ops.importar_bloques(portal, "PLC_9", origen)


def test_importar_bloques_falla_si_la_carpeta_no_existe(tmp_path: Path) -> None:
    portal, _plc = _portal()

    with pytest.raises(OperacionError, match="no existe o no es accesible"):
        ops.importar_bloques(portal, "PLC_1", tmp_path / "no-existe")


def test_importar_bloques_falla_si_tia_rechaza(origen: Path) -> None:
    portal, plc = _portal()
    plc.error = RuntimeError("Import failed because an object with the name X already exists")

    with pytest.raises(OperacionError, match="No se pudo importar los bloques"):
        ops.importar_bloques(portal, "PLC_1", origen)


# ── tablas de tags ─────────────────────────────────────────────────────────


def test_importar_tablas_sin_carpeta_no_manda_el_argumento(origen: Path) -> None:
    portal, plc = _portal()

    resultado = ops.importar_tablas(portal, "PLC_1", origen)

    assert resultado["importado_de"] == str(origen)
    assert plc.importaciones == [{"import_root_directory": str(origen)}]


def test_importar_tablas_con_carpeta_la_manda(origen: Path) -> None:
    portal, plc = _portal()

    ops.importar_tablas(portal, "PLC_1", origen, "2000_Dispositivos")

    assert plc.importaciones == [
        {
            "import_root_directory": str(origen),
            "target_folder_path": "2000_Dispositivos",
        }
    ]


def test_importar_tablas_falla_si_el_plc_no_existe(origen: Path) -> None:
    portal, _plc = _portal()

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        ops.importar_tablas(portal, "PLC_9", origen)


def test_importar_tablas_falla_si_tia_rechaza(origen: Path) -> None:
    portal, plc = _portal()
    plc.error = RuntimeError("TIA dice que no")

    with pytest.raises(OperacionError, match="No se pudo importar las tablas"):
        ops.importar_tablas(portal, "PLC_1", origen)


def test_lo_publico_devuelve_solo_primitivos(origen: Path) -> None:
    portal, _plc = _portal()

    for resultado in (
        ops.importar_bloques(portal, "PLC_1", origen),
        ops.importar_tablas(portal, "PLC_1", origen),
    ):
        assert isinstance(resultado, dict)
        assert isinstance(resultado["importado_de"], str)
        assert isinstance(resultado["carpeta_destino"], str)
        assert isinstance(resultado["num_ficheros"], int)
        assert isinstance(resultado["ficheros"], list)


def test_el_resultado_dice_los_ficheros_del_origen(origen: Path) -> None:
    portal, _plc = _portal()

    resultado = ops.importar_tablas(portal, "PLC_1", origen)

    assert resultado["num_ficheros"] == 1
    assert resultado["ficheros"] == ["2000_Dispositivos/2000_Disp_ED.xml"]


def test_los_ficheros_del_origen_usan_barra_normal(origen: Path) -> None:
    portal, _plc = _portal()

    resultado = ops.importar_bloques(portal, "PLC_1", origen)

    assert all("\\" not in ruta for ruta in resultado["ficheros"])


def test_un_origen_vacio_no_tiene_ficheros(origen: Path) -> None:
    vacio = origen / "vacio"
    vacio.mkdir()
    portal, _plc = _portal()

    resultado = ops.importar_tablas(portal, "PLC_1", vacio)

    assert resultado["num_ficheros"] == 0
    assert resultado["ficheros"] == []
