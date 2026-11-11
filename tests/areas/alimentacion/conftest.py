"""Ficheros de prueba del area de alimentacion.

El Excel maestro del operario tiene **tablas nombradas**. Aqui se construye
uno pequeno, con las mismas hojas y tablas, para probar el parser sin ficheros
reales.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

#: La seccion del area en el ``config.json``, en version minima.
SECCION: dict[str, Any] = {
    "global_config_table_name": "0_Config_Dispositivos",
    "n_max_catalog": [
        {"name": "N_MAX_DISP_EA", "excel_column": "N_Max_EA"},
        {"name": "N_MAX_DISP_ED", "excel_column": "N_Max_ED"},
    ],
    "Dispositivos": {
        "ed": {
            "excel_target": {
                "sheet": "DISP_ED",
                "table": "Tabla_Disp_ED",
                "canonical": "DispED",
            }
        }
    },
    "disp_catalog": {
        "display_order": {
            "DispED": ["plc_name", "numero", "tag", "descripcion", "e_byte", "e_bit"],
        }
    },
    "proc_catalog": {
        "display_order": {
            "procesos": ["plc_name", "codigo", "nombre"],
            "parametros_int": ["plc_name", "numero", "codigo", "num_db", "descripcion"],
            "parametros_real": ["plc_name", "numero", "codigo", "num_db", "descripcion"],
            "alarmas": [
                "plc_name",
                "numero",
                "proceso",
                "num_db",
                "descripcion",
                "comentario_db",
            ],
        }
    },
    "entidades_catalog": {
        "display_order": {
            "entidades": ["plc_name", "numero", "descripcion", "plc_tag"],
        }
    },
}


def _anadir_tabla(
    hoja: Any,
    nombre: str,
    cabeceras: list[str],
    filas: list[list[Any]],
) -> None:
    """Escribe una tabla nombrada en la hoja.

    La tabla empieza en la primera fila libre: en una hoja pueden convivir
    varias tablas, cada una con su rango.
    """
    hoja.append(list(cabeceras))
    inicio = hoja.max_row
    for fila in filas:
        hoja.append(list(fila))
    ref = f"A{inicio}:{get_column_letter(len(cabeceras))}{hoja.max_row}"
    tabla = Table(displayName=nombre, ref=ref)
    tabla.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showRowStripes=True)
    hoja.add_table(tabla)


def escribir_excel(ruta: Path, filas_disp_ed: list[list[Any]] | None = None) -> Path:
    """Escribe un Excel maestro de prueba y devuelve su ruta.

    Args:
        ruta: donde se escribe.
        filas_disp_ed: filas de la tabla de entradas digitales. Por defecto,
            una fila buena.
    """
    filas_ed = (
        filas_disp_ed
        if filas_disp_ed is not None
        else [["PLC1", 1, "V_ED_001", "Entrada digital", 3, 2]]
    )
    libro = Workbook()

    config = libro.active
    config.title = "CONFIG"
    _anadir_tabla(
        config,
        "Tabla_Dimensiones",
        ["PLC", "N_Max_EA", "N_Max_ED"],
        [["PLC1", 10, 20]],
    )
    _anadir_tabla(config, "Tabla_PLC", ["PLC"], [["PLC1"]])
    _anadir_tabla(
        config,
        "Tabla_Procesos",
        ["PLC", "Codigo", "Nombre"],
        [["PLC1", "PR1", "Proceso uno"]],
    )

    disp_ed = libro.create_sheet("DISP_ED")
    _anadir_tabla(
        disp_ed,
        "Tabla_Disp_ED",
        ["PLC", "Numero", "Tag", "Descripcion", "E.Byte", "E.Bit"],
        filas_ed,
    )

    p_int = libro.create_sheet("P_INT")
    _anadir_tabla(
        p_int,
        "Tabla_PInt",
        ["PLC", "Numero", "Codigo", "Num.DB", "Descripcion"],
        [["PLC1", 1, "PI1", 500, "Parametro entero"]],
    )

    p_real = libro.create_sheet("P_REAL")
    _anadir_tabla(
        p_real,
        "Tabla_PReal",
        ["PLC", "Numero", "Codigo", "Num.DB", "Descripcion"],
        [["PLC1", 1, "PR1", 501, "Parametro real"]],
    )

    alarmas = libro.create_sheet("ALARMAS")
    _anadir_tabla(
        alarmas,
        "Tabla_Alarmas",
        ["PLC", "Numero", "Proceso", "Num.DB", "Descripcion", "ComentarioDB"],
        [["PLC1", 1, "PR1", 502, "Alarma de prueba", "Comentario"]],
    )

    entidades = libro.create_sheet("ENTIDADES")
    _anadir_tabla(
        entidades,
        "Tabla_Entidades",
        ["PLC", "Numero", "Descripcion", "PLC.Tag"],
        [["PLC1", 7, "Entidad de prueba", "DB7"]],
    )

    libro.save(ruta)
    return ruta


@pytest.fixture
def seccion() -> dict[str, Any]:
    """La seccion del area en el ``config.json``."""
    return dict(SECCION)


@pytest.fixture
def crear_excel() -> Callable[..., Path]:
    """Escribe un Excel maestro de prueba."""

    def _crear(ruta: Path, filas_disp_ed: list[list[Any]] | None = None) -> Path:
        return escribir_excel(ruta, filas_disp_ed)

    return _crear


@pytest.fixture
def excel_maestro(tmp_path: Path) -> Path:
    """Un Excel maestro de prueba, con las tablas del operario."""
    return escribir_excel(tmp_path / "maestro.xlsx")
