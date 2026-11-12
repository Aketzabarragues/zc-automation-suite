"""Las columnas que se ensenan: las del config y sus etiquetas.

Ningun test toca TIA: el Excel se construye aqui mismo.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel import parser


def test_las_columnas_son_las_del_config(
    excel_completo: Path,
    modelo: ConfigArea,
    tabla: Callable[..., dict[str, Any]],
) -> None:
    datos = parser.leer_excel(excel_completo, modelo)

    assert tabla(datos, "ed")["columnas"] == modelo.dispositivos["ed"].columnas
    assert datos["entidades"]["columnas"] == modelo.entidades.columnas
    assert datos["procesos"]["Alarmas"]["columnas"] == modelo.procesos.columnas["alarmas"]


def test_las_etiquetas_salen_de_su_seccion(
    excel_completo: Path,
    modelo: ConfigArea,
    tabla: Callable[..., dict[str, Any]],
) -> None:
    datos = parser.leer_excel(excel_completo, modelo)

    etiquetas = tabla(datos, "ed")["etiquetas"]
    assert etiquetas["numero"] == modelo.etiquetas_dispositivos["numero"]
    assert "plc_name" not in etiquetas or etiquetas["plc_name"] == "PLC"
    assert datos["procesos"]["Procesos"]["etiquetas"]["alm_hmi"] == "Alarmas HMI"
    assert datos["entidades"]["etiquetas"]["plc_tag"] == "PLC.Tag"


def test_las_etiquetas_de_cada_seccion_no_se_mezclan(
    excel_completo: Path,
    modelo: ConfigArea,
    tabla: Callable[..., dict[str, Any]],
) -> None:
    """``numero`` se titula distinto en cada seccion, y no se pisan."""
    datos = parser.leer_excel(excel_completo, modelo)

    assert tabla(datos, "ed")["etiquetas"]["numero"] == "Número"
    assert datos["procesos"]["Alarmas"]["etiquetas"]["numero"] == "No"
    assert datos["entidades"]["etiquetas"]["numero"] == "Numero"
