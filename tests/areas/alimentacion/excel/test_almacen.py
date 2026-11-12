"""La cache del Excel maestro: el volcado, la copia guardada y su recarga.

Ningun test toca TIA: el Excel se construye aqui mismo.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from zc_suite.areas.alimentacion.excel import almacen as modulo_almacen
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel


def test_el_almacen_guarda_el_volcado(
    excel_completo: Path,
    seccion: dict[str, Any],
    esperado_plcs: dict[str, Any],
    tabla: Callable[..., dict[str, Any]],
) -> None:
    almacen = AlmacenExcel()
    almacen.config = seccion

    almacen.volcar(excel_completo)

    assert almacen.cargado is True
    assert almacen.archivo == "completo.xlsx"
    assert almacen.cargado_en
    estado = almacen.estado()
    assert estado["cargado"] is True
    assert estado["plcs"] == esperado_plcs
    assert tabla(estado, "ed")["filas"][0]["plc_tag"] == "V_ED_001"


def test_el_almacen_vacio_sale_vacio() -> None:
    almacen = AlmacenExcel()

    estado = almacen.estado()

    assert estado["cargado"] is False
    assert estado["archivo"] is None
    assert estado["plcs"] == []
    assert estado["dispositivos"] == []
    assert estado["avisos"] == []
    assert estado["entidades"] == {"columnas": [], "filas": []}


def test_el_almacen_persiste_y_recarga(
    excel_completo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seccion: dict[str, Any],
    tabla: Callable[..., dict[str, Any]],
) -> None:
    carpeta = tmp_path / "excel"
    monkeypatch.setattr(modulo_almacen, "carpeta_persistida", lambda: carpeta)
    almacen = AlmacenExcel()
    almacen.config = seccion

    almacen.volcar(excel_completo)
    copia = almacen.persistir(excel_completo)

    assert copia == carpeta / "completo.xlsx"
    assert copia.is_file()

    otro = AlmacenExcel()
    otro.config = seccion
    assert otro.recargar() is True
    assert otro.archivo == "completo.xlsx"
    assert tabla(otro.estado(), "ed")["filas"][0]["plc_tag"] == "V_ED_001"


def test_al_guardar_una_copia_nueva_se_borran_las_anteriores(
    excel_completo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seccion: dict[str, Any],
) -> None:
    carpeta = tmp_path / "excel"
    monkeypatch.setattr(modulo_almacen, "carpeta_persistida", lambda: carpeta)
    almacen = AlmacenExcel()
    almacen.config = seccion

    almacen.persistir(excel_completo)
    otro = excel_completo.with_name("otro.xlsx")
    otro.write_bytes(excel_completo.read_bytes())
    almacen.persistir(otro)

    assert sorted(p.name for p in carpeta.glob("*.xlsx")) == ["otro.xlsx"]


def test_recargar_sin_copia_devuelve_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        modulo_almacen,
        "carpeta_persistida",
        lambda: tmp_path / "excel",
    )
    almacen = AlmacenExcel()

    assert almacen.recargar() is False
    assert almacen.cargado is False


def test_la_carpeta_persistida_en_empaquetado_va_junto_al_ejecutable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    congelado = SimpleNamespace(frozen=True, executable=str(tmp_path / "zc.exe"))
    monkeypatch.setattr(modulo_almacen, "sys", congelado)

    ruta = modulo_almacen.carpeta_persistida()

    assert ruta == tmp_path / "excel"


def test_la_carpeta_persistida_en_desarrollo_va_en_el_repo() -> None:
    carpeta = modulo_almacen.carpeta_persistida()

    assert carpeta.name == "excel"
    assert (carpeta.parent / "backend" / "zc_suite").is_dir()
