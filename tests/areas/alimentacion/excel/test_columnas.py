"""Las columnas que se ensenan: las del ``display_order`` y sus etiquetas.

Ningun test toca TIA: el Excel se construye aqui mismo.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.excel import parser


def test_las_columnas_son_las_del_display_order(
    excel_completo: Path,
    seccion: dict[str, Any],
    tabla: Callable[..., dict[str, Any]],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    assert tabla(datos, "ed")["columnas"] == seccion["disp_catalog"]["display_order"][
        "DispED"
    ]
    assert datos["entidades"]["columnas"] == seccion["entidades_catalog"]["display_order"][
        "entidades"
    ]


def test_las_etiquetas_salen_del_col_labels(
    excel_completo: Path,
    seccion: dict[str, Any],
    tabla: Callable[..., dict[str, Any]],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    etiquetas = tabla(datos, "ed")["etiquetas"]
    assert etiquetas["numero"] == seccion["disp_catalog"]["col_labels"]["numero"]
    assert "plc_name" not in etiquetas or etiquetas["plc_name"] == "PLC"
    assert datos["procesos"]["Procesos"]["etiquetas"]["alm_hmi"] == "Alarmas HMI"
    assert datos["entidades"]["etiquetas"]["plc_tag"] == "PLC.Tag"
