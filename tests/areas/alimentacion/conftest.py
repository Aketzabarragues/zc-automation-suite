"""Ficheros de prueba del area de alimentacion.

El Excel maestro del operario tiene **tablas nombradas**. Aqui se construye
uno pequeno, con las mismas hojas y tablas, para probar el parser sin
ficheros reales.

El fixture completo replica el ``_build_full_xlsx`` de ``main``: una fila de
cada dominio, con los mismos valores, para comprobar la paridad del modelo.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

#: Raiz del repo.
RAIZ = Path(__file__).resolve().parents[3]


def _anadir_tabla(
    libro: Workbook,
    hoja: str,
    nombre: str,
    cabeceras: list[str],
    filas: list[list[Any]],
    con_plc: bool = True,
) -> None:
    """Escribe una tabla nombrada en la hoja.

    La tabla empieza en la primera fila libre: en una hoja pueden convivir
    varias tablas, cada una con su rango.

    Args:
        libro: el libro abierto.
        hoja: la hoja donde se escribe.
        nombre: el nombre de la tabla nombrada.
        cabeceras: las cabeceras de la tabla.
        filas: las filas de datos.
        con_plc: si se inyecta la columna ``PLC`` con ``"PLC1"``.
    """
    if con_plc and "PLC" not in cabeceras:
        cabeceras = ["PLC", *cabeceras]
        filas = [["PLC1", *fila] for fila in filas]
    if hoja not in libro.sheetnames:
        libro.create_sheet(hoja)
    hoja_obj = libro[hoja]
    hoja_obj.append(list(cabeceras))
    inicio = hoja_obj.max_row
    for fila in filas:
        hoja_obj.append(list(fila))
    ref = f"A{inicio}:{get_column_letter(len(cabeceras))}{hoja_obj.max_row}"
    tabla = Table(displayName=nombre, ref=ref)
    tabla.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showRowStripes=True)
    hoja_obj.add_table(tabla)


#: Los N_MAX del Excel de prueba: el mismo nombre canonico que el config.
N_MAX = (
    ("N_Max_EA", 20),
    ("N_Max_ED", 10),
    ("N_Max_M", 50),
    ("N_Max_M_SINA", 70),
    ("N_Max_M_VF", 60),
    ("N_Max_PID", 90),
    ("N_Max_SA", 30),
    ("N_Max_SD", 80),
    ("N_Max_TOT", 80),
    ("N_Max_TQ", 80),
    ("N_Max_TQ_AE", 80),
    ("N_Max_V", 40),
)


#: Una fila de cada tipo de dispositivo: la hoja, la tabla y los valores.
DISPOSITIVOS_PRUEBA: tuple[tuple[str, str, str, str, str, dict[str, Any]], ...] = (
    ("DISP_ED", "Tabla_Disp_ED", "ED_001", "V_ED_001", "Entrada digital 1", {}),
    (
        "DISP_EA",
        "Tabla_Disp_EA",
        "EA_001",
        "V_EA_001",
        "Entrada analogica 1",
        {"RII": 0.0, "RSI": 100.0},
    ),
    ("DISP_SA", "Tabla_Disp_SA", "SA_001", "V_SA_001", "Salida analogica 1", {}),
    ("DISP_SD", "Tabla_Disp_SD", "SD_001", "V_SD_001", "Salida digital 1", {}),
    ("DISP_V", "Tabla_Disp_V", "V_001", "V_V_001", "Variable 1", {}),
    ("DISP_M", "Tabla_Disp_M", "M_001", "V_M_001", "Motor 1", {}),
    ("DISP_M_VF", "Tabla_Disp_M_VF", "MVF_001", "V_MVF_001", "Motor VF 1", {}),
    ("DISP_M_SINA", "Tabla_Disp_M_SINA", "MSINA_001", "V_MSINA_001", "Motor Sinamics 1", {}),
    ("DISP_TQ", "Tabla_Disp_TQ", "TQ_001", "V_TQ_001", "Tanque 1", {}),
    ("DISP_TQ_AE", "Tabla_Disp_TQ_AE", "TQAE_001", "V_TQAE_001", "Tanque aire esteril 1", {}),
    ("DISP_TOT", "Tabla_Disp_TOT", "TOT_001", "V_TOT_001", "Totalizador 1", {}),
    ("DISP_PID", "Tabla_Disp_PID", "PID_001", "V_PID_001", "Controlador PID 1", {}),
)


def escribir_excel_completo(ruta: Path) -> Path:
    """Escribe un Excel con una fila de cada dominio del Excel maestro."""
    libro = Workbook()
    libro.remove(libro.active)

    for hoja, tabla, uid, tag, descripcion, extra in DISPOSITIVOS_PRUEBA:
        _anadir_tabla(
            libro,
            hoja,
            tabla,
            ["UID", "Numero", "PLC.Tag", "Descripcion", *extra],
            [[uid, 1, tag, descripcion, *extra.values()]],
        )

    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_PLC",
        ["UID", "PLC"],
        [[1, "PLC1"]],
        con_plc=False,
    )
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_Procesos",
        ["UID", "Nombre", "Codigo", "PReal", "PInt", "Alarmas"],
        [[1, "Proceso 1", "PR1", 1, 1, 16]],
    )
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_Dimensiones",
        ["PLC", *[columna for columna, _valor in N_MAX], "N_Max_ENT"],
        [["PLC1", *[valor for _columna, valor in N_MAX], 6]],
        con_plc=False,
    )

    columnas_parametro = [
        "UID",
        "Numero",
        "Proceso",
        "Codigo",
        "Num.DB",
        "Producto",
        "Tipo",
        "Descripcion",
        "ComentarioDB",
        "Visibilidad",
        "Num.Lista",
        "Txt.Lista",
    ]
    _anadir_tabla(
        libro,
        "P_REAL",
        "Tabla_PReal",
        columnas_parametro,
        [
            [
                "PR_1_001",
                "001",
                "Proceso 1",
                "PR1",
                3001,
                "Producto",
                "Setpoint",
                "PR1",
                "c",
                "Si",
                1,
                "Txt",
            ]
        ],
    )
    _anadir_tabla(
        libro,
        "P_INT",
        "Tabla_PInt",
        columnas_parametro,
        [
            [
                "PI_1_001",
                "001",
                "Proceso 1",
                "PR1",
                3002,
                "Producto",
                "Contador",
                "PI1",
                "c",
                "Si",
                0,
                "Txt",
            ]
        ],
    )
    _anadir_tabla(
        libro,
        "ALARMAS",
        "Tabla_Alarmas",
        ["UID", "Numero", "Proceso", "Num.DB", "Descripcion", "ComentarioDB"],
        [["AL_1_001", "001", "Proceso 1", 5001, "Alarma 1", "c"]],
    )
    _anadir_tabla(
        libro,
        "ENTIDADES",
        "Tabla_Entidades",
        ["Numero", "PLC.Tag", "Descripcion"],
        [[1, "ent_001", "Entidad 1"]],
    )

    libro.save(ruta)
    return ruta


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
        else [["PLC1", "ED_001", 1, "V_ED_001", "Entrada digital", 3, 2]]
    )
    libro = Workbook()

    libro.active.title = "CONFIG"
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_Dimensiones",
        ["PLC", "N_Max_EA", "N_Max_ED"],
        [["PLC1", 10, 20]],
        con_plc=False,
    )
    _anadir_tabla(libro, "CONFIG", "Tabla_PLC", ["PLC"], [["PLC1"]], con_plc=False)
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_Procesos",
        ["PLC", "Codigo", "Nombre"],
        [["PLC1", "PR1", "Proceso uno"]],
        con_plc=False,
    )

    _anadir_tabla(
        libro,
        "DISP_ED",
        "Tabla_Disp_ED",
        ["PLC", "UID", "Numero", "Tag", "Descripcion", "E.Byte", "E.Bit"],
        filas_ed,
        con_plc=False,
    )

    libro.create_sheet("P_INT")
    _anadir_tabla(
        libro,
        "P_INT",
        "Tabla_PInt",
        ["PLC", "Numero", "Codigo", "Num.DB", "Descripcion"],
        [["PLC1", 1, "PI1", 500, "Parametro entero"]],
        con_plc=False,
    )

    libro.create_sheet("P_REAL")
    _anadir_tabla(
        libro,
        "P_REAL",
        "Tabla_PReal",
        ["PLC", "Numero", "Codigo", "Num.DB", "Descripcion"],
        [["PLC1", 1, "PR1", 501, "Parametro real"]],
        con_plc=False,
    )

    libro.create_sheet("ALARMAS")
    _anadir_tabla(
        libro,
        "ALARMAS",
        "Tabla_Alarmas",
        ["PLC", "Numero", "Proceso", "Num.DB", "Descripcion", "ComentarioDB"],
        [["PLC1", 1, "PR1", 502, "Alarma de prueba", "Comentario"]],
        con_plc=False,
    )

    libro.create_sheet("ENTIDADES")
    _anadir_tabla(
        libro,
        "ENTIDADES",
        "Tabla_Entidades",
        ["PLC", "Numero", "Descripcion", "PLC.Tag"],
        [["PLC1", 7, "Entidad de prueba", "DB7"]],
        con_plc=False,
    )

    libro.save(ruta)
    return ruta


@pytest.fixture
def seccion() -> dict[str, Any]:
    """La seccion del area tal y como esta en el ``config.json``."""
    datos = json.loads((RAIZ / "config" / "config.json").read_text(encoding="utf-8"))
    return datos["areas"]["alimentacion"]


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


@pytest.fixture
def excel_completo(tmp_path: Path) -> Path:
    """Un Excel maestro con una fila de cada dominio."""
    return escribir_excel_completo(tmp_path / "completo.xlsx")
