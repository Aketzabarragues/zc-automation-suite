"""La cache del Excel maestro: el volcado que vive en memoria.

Ningun test toca TIA: el Excel se construye aqui mismo.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel


def test_el_almacen_guarda_el_volcado(
    excel_completo: Path,
    modelo: ConfigArea,
    esperado_plcs: dict[str, Any],
    tabla: Callable[..., dict[str, Any]],
) -> None:
    almacen = AlmacenExcel()
    almacen.config = modelo

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


def test_vaciar_deja_el_almacen_sin_excel(
    excel_completo: Path,
    modelo: ConfigArea,
) -> None:
    almacen = AlmacenExcel()
    almacen.config = modelo
    almacen.volcar(excel_completo)

    almacen.vaciar()

    assert almacen.cargado is False
    assert almacen.archivo is None
    assert almacen.cargado_en is None
    assert almacen.estado()["plcs"] == []
