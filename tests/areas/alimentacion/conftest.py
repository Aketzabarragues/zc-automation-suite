"""Ficheros de prueba del area de alimentacion.

El Excel maestro del operario tiene **tablas nombradas**. Aqui se construye
uno pequeno, con las mismas hojas y tablas, para probar el parser sin
ficheros reales.

El fixture completo tiene **una fila buena y una fila sucia** de cada
dominio (texto donde toca un numero, celdas vacias): es el que fija el
comportamiento del parser. Los valores esperados estan escritos en el test
de paridad, sacados de ejecutar los parsers de ``main`` sobre este mismo
fichero.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from zc_suite.areas.alimentacion import config as config_area
from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones.dispositivos import (
    generar_prevision as modulo_prevision,
)
from zc_suite.nucleo.tia import servicio as tia
from zc_suite.nucleo.tia.servicio import ServicioTIA
from zc_suite.nucleo.tia.workdir import Workdir

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


def _fila(cabeceras: list[str], valores: dict[str, Any]) -> list[Any]:
    """Una fila con un valor por cabecera. Las que no estan, van vacias."""
    return [valores.get(cabecera, "") for cabecera in cabeceras]


#: Las cabeceras de los dispositivos: la union de las de todos los tipos.
CABECERAS_DISPOSITIVO = [
    "UID",
    "Numero",
    "PLC.Tag",
    "Descripcion",
    "Tag",
    "FAT",
    "E.Byte",
    "E.Bit",
    "S.Byte",
    "S.Bit",
    "RR.Byte",
    "RR.Bit",
    "RT.Byte",
    "RT.Bit",
    "RM.Byte",
    "RM.Bit",
    "SA.Byte",
    "Gr.Alarma",
    "Cuadro",
    "Observaciones",
    "PLC.Tipo",
    "PLC.Index",
    "Hmi.Index",
    "Hmi.Texto",
    "Cfg.Habilitar",
    "Cfg.ByteEntrada",
    "Cfg.BitEntrada",
    "Cfg.EscaladoMin",
    "Cfg.EscaladoMax",
    "Cfg.GrupoAlarma",
    "Cfg.ByteRetornoReposo",
    "Cfg.BitRetornoReposo",
    "Cfg.ByteRetornoTrabajo",
    "Cfg.BitRetornoTrabajo",
    "Cfg.ByteActivacion",
    "Cfg.BitActivacion",
    "Cfg.HabRetReposo",
    "Cfg.HabRetTrabajo",
    "Cfg.ByteRetornoTermico",
    "Cfg.BitRetornoTermico",
    "Cfg.ByteConfMarcha",
    "Cfg.BitConfMarcha",
    "Cfg.HabRetTermico",
    "Cfg.HabRetConfMarcha",
    "Cfg.ByteAnalogica",
    "Cfg.VelMin",
    "Cfg.VelMax",
    "Cfg.ConstK",
    "Cfg.Tipo",
    "ComentarioDB",
    "Tipo",
    "IncXPulso",
    "Proceso",
    "PV",
    "Disp.Tipo",
    "Disp.Tag",
    "UNIDADES",
    "RII",
    "RSI",
    "Vel.Min",
    "Vel.Max",
    "ConsK",
]

#: La fila buena de un dispositivo: un valor por cabecera.
DISPOSITIVO_BUENO: dict[str, Any] = {
    "UID": "ED_001",
    "Numero": 1,
    "PLC.Tag": "V_ED_001",
    "Descripcion": "Entrada digital 1",
    "Tag": "TAG_001",
    "FAT": "FAT_001",
    "E.Byte": 3,
    "E.Bit": 2,
    "S.Byte": 4,
    "S.Bit": 5,
    "RR.Byte": 6,
    "RR.Bit": 7,
    "RT.Byte": 8,
    "RT.Bit": 9,
    "RM.Byte": 10,
    "RM.Bit": 11,
    "SA.Byte": 12,
    "Gr.Alarma": 13,
    "Cuadro": "C1",
    "Observaciones": "Observacion",
    "PLC.Tipo": "S7-1500",
    "PLC.Index": 14,
    "Hmi.Index": 15,
    "Hmi.Texto": "Texto HMI",
    "Cfg.Habilitar": "SI",
    "Cfg.ByteEntrada": "16",
    "Cfg.BitEntrada": "17",
    "Cfg.EscaladoMin": "18",
    "Cfg.EscaladoMax": "19",
    "Cfg.GrupoAlarma": "20",
    "Cfg.ByteRetornoReposo": "21",
    "Cfg.BitRetornoReposo": "22",
    "Cfg.ByteRetornoTrabajo": "23",
    "Cfg.BitRetornoTrabajo": "24",
    "Cfg.ByteActivacion": "25",
    "Cfg.BitActivacion": "26",
    "Cfg.HabRetReposo": "27",
    "Cfg.HabRetTrabajo": "28",
    "Cfg.ByteRetornoTermico": "29",
    "Cfg.BitRetornoTermico": "30",
    "Cfg.ByteConfMarcha": "31",
    "Cfg.BitConfMarcha": "32",
    "Cfg.HabRetTermico": "33",
    "Cfg.HabRetConfMarcha": "34",
    "Cfg.ByteAnalogica": "35",
    "Cfg.VelMin": "36",
    "Cfg.VelMax": "37",
    "Cfg.ConstK": "38",
    "Cfg.Tipo": "39",
    "ComentarioDB": "Comentario del DB",
    "Tipo": "Tipo 1",
    "IncXPulso": "0,5",
    "Proceso": "Proceso 1",
    "PV": "PV_1",
    "Disp.Tipo": "Disp.Tipo 1",
    "Disp.Tag": "Disp.Tag 1",
    "UNIDADES": "Litros",
    "RII": "0,5",
    "RSI": "100,5",
    "Vel.Min": "1,5",
    "Vel.Max": "2,5",
    "ConsK": "3,5",
}

#: La fila sucia: texto donde toca un numero, celdas vacias y una coma
#: decimal. Es el caso que ``main`` tolera.
DISPOSITIVO_SUCIO: dict[str, Any] = {
    "UID": "ED_002",
    "Numero": "no es un numero",
    "PLC.Tag": "",
    "Descripcion": None,
    "Tag": "",
    "FAT": "",
    "E.Byte": None,
    "E.Bit": "",
    "S.Byte": "texto",
    "S.Bit": None,
    "Gr.Alarma": "",
    "Cuadro": "",
    "Observaciones": "",
    "PLC.Tipo": "int",
    "PLC.Index": "",
    "Hmi.Index": None,
    "Hmi.Texto": "",
    "Cfg.Habilitar": "",
    "RII": "1,5",
}

#: Las doce tablas de dispositivo, con su hoja y su nombre.
TABLAS_DISPOSITIVO: tuple[tuple[str, str], ...] = (
    ("DISP_ED", "Tabla_Disp_ED"),
    ("DISP_EA", "Tabla_Disp_EA"),
    ("DISP_SA", "Tabla_Disp_SA"),
    ("DISP_SD", "Tabla_Disp_SD"),
    ("DISP_V", "Tabla_Disp_V"),
    ("DISP_M", "Tabla_Disp_M"),
    ("DISP_M_VF", "Tabla_Disp_M_VF"),
    ("DISP_M_SINA", "Tabla_Disp_M_SINA"),
    ("DISP_TQ", "Tabla_Disp_TQ"),
    ("DISP_TQ_AE", "Tabla_Disp_TQ_AE"),
    ("DISP_TOT", "Tabla_Disp_TOT"),
    ("DISP_PID", "Tabla_Disp_PID"),
)

#: Las cabeceras del software: la union de las de sus cuatro dominios.
CABECERAS_SOFTWARE = [
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
    "Nombre",
    "PReal",
    "PInt",
    "Alarmas",
    "Alarmas_Hmi",
    "Index_Preal",
    "Index_Pint",
]

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


def escribir_excel_completo(ruta: Path) -> Path:
    """Escribe el Excel maestro de prueba: dos filas de cada dominio."""
    libro = Workbook()
    libro.remove(libro.active)

    for hoja, tabla in TABLAS_DISPOSITIVO:
        _anadir_tabla(
            libro,
            hoja,
            tabla,
            CABECERAS_DISPOSITIVO,
            [
                _fila(CABECERAS_DISPOSITIVO, DISPOSITIVO_BUENO),
                _fila(CABECERAS_DISPOSITIVO, DISPOSITIVO_SUCIO),
            ],
        )

    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_PLC",
        ["UID", "PLC"],
        [[1, "PLC1"], [2, "PLC2"]],
        con_plc=False,
    )
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_Procesos",
        CABECERAS_SOFTWARE,
        [
            _fila(
                CABECERAS_SOFTWARE,
                {
                    "UID": 1,
                    "Numero": "001",
                    "Proceso": "Proceso 1",
                    "Codigo": "PR1",
                    "Num.DB": 3001,
                    "Producto": "Producto",
                    "Tipo": "Setpoint",
                    "Descripcion": "PR1",
                    "ComentarioDB": "c",
                    "Visibilidad": "Si",
                    "Num.Lista": 1,
                    "Txt.Lista": "Txt",
                    "Nombre": "Proceso 1",
                    "PReal": 1,
                    "PInt": 1,
                    "Alarmas": 16,
                    "Alarmas_Hmi": 2,
                    "Index_Preal": 3,
                    "Index_Pint": 4,
                },
            ),
            _fila(
                CABECERAS_SOFTWARE,
                {
                    "UID": 2,
                    "Numero": "002",
                    "Proceso": "Proceso 2",
                    "Codigo": "PR2",
                    "Num.DB": 3002,
                    "Producto": "Producto",
                    "Tipo": "Contador",
                    "Descripcion": "PR2",
                    "ComentarioDB": "c",
                    "Visibilidad": "Si",
                    "Num.Lista": "N/A",
                    "Txt.Lista": "Txt",
                    "Nombre": "Proceso 2",
                    "PReal": 5,
                    "PInt": 6,
                    "Alarmas": 7,
                    "Alarmas_Hmi": 8,
                    "Index_Preal": 9,
                    "Index_Pint": 10,
                },
            ),
            _fila(
                CABECERAS_SOFTWARE,
                {
                    "UID": "",
                    "Numero": "003",
                    "Proceso": "Proceso 3",
                    "Codigo": "PR3",
                    "Num.DB": 3003,
                    "Producto": "Producto",
                    "Tipo": "Setpoint",
                    "Descripcion": "PR3",
                    "ComentarioDB": "c",
                    "Visibilidad": "Si",
                    "Num.Lista": 0,
                    "Txt.Lista": "Txt",
                    "Nombre": "Proceso 3",
                    "PReal": 0,
                    "PInt": 0,
                    "Alarmas": 0,
                    "Alarmas_Hmi": 0,
                    "Index_Preal": 0,
                    "Index_Pint": 0,
                },
            ),
        ],
    )
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_Dimensiones",
        ["PLC", *[columna for columna, _valor in N_MAX], "N_Max_ENT"],
        [
            # Van al reves a proposito: los N_MAX tienen que salir ordenados
            # por PLC, como en main, no en el orden del fichero.
            ["PLC2", *[valor + 1 for _columna, valor in N_MAX], 7],
            ["PLC1", *[valor for _columna, valor in N_MAX], 6],
        ],
        con_plc=False,
    )

    _anadir_tabla(
        libro,
        "P_REAL",
        "Tabla_PReal",
        CABECERAS_SOFTWARE,
        [
            _fila(
                CABECERAS_SOFTWARE,
                {
                    "UID": "PR_1_001",
                    "Numero": "001",
                    "Proceso": "Proceso 1",
                    "Codigo": "PR1",
                    "Num.DB": 3001,
                    "Producto": "Producto",
                    "Tipo": "Setpoint",
                    "Descripcion": "PR1",
                    "ComentarioDB": "c",
                    "Visibilidad": "Si",
                    "Num.Lista": 1,
                    "Txt.Lista": "Txt",
                },
            ),
            _fila(
                CABECERAS_SOFTWARE,
                {
                    "UID": "PR_1_002",
                    "Numero": "002",
                    "Proceso": "Proceso 2",
                    "Codigo": "PR2",
                    "Num.DB": 3002,
                    "Producto": "Producto",
                    "Tipo": "Contador",
                    "Descripcion": "PR2",
                    "ComentarioDB": "c",
                    "Visibilidad": "Si",
                    "Num.Lista": "N/A",
                    "Txt.Lista": "Txt",
                },
            ),
        ],
    )
    _anadir_tabla(
        libro,
        "P_INT",
        "Tabla_PInt",
        CABECERAS_SOFTWARE,
        [
            _fila(
                CABECERAS_SOFTWARE,
                {
                    "UID": "PI_1_001",
                    "Numero": "001",
                    "Proceso": "Proceso 1",
                    "Codigo": "PR1",
                    "Num.DB": 3002,
                    "Producto": "Producto",
                    "Tipo": "Contador",
                    "Descripcion": "PI1",
                    "ComentarioDB": "c",
                    "Visibilidad": "Si",
                    "Num.Lista": 0,
                    "Txt.Lista": "Txt",
                },
            ),
            _fila(
                CABECERAS_SOFTWARE,
                {
                    "UID": "PI_1_002",
                    "Numero": "002",
                    "Proceso": "Proceso 2",
                    "Codigo": "PR2",
                    "Num.DB": 3003,
                    "Producto": "Producto",
                    "Tipo": "Setpoint",
                    "Descripcion": "PI2",
                    "ComentarioDB": "c",
                    "Visibilidad": "Si",
                    "Num.Lista": 5,
                    "Txt.Lista": "Txt",
                },
            ),
        ],
    )
    _anadir_tabla(
        libro,
        "ALARMAS",
        "Tabla_Alarmas",
        CABECERAS_SOFTWARE,
        [
            _fila(
                CABECERAS_SOFTWARE,
                {
                    "UID": "AL_1_001",
                    "Numero": "001",
                    "Proceso": "Proceso 1",
                    "Num.DB": 5001,
                    "Descripcion": "Alarma 1",
                    "ComentarioDB": "c",
                    "Visibilidad": "Si",
                    "Num.Lista": 1,
                    "Txt.Lista": "Txt",
                },
            ),
            _fila(
                CABECERAS_SOFTWARE,
                {
                    "UID": "AL_1_002",
                    "Numero": "002",
                    "Proceso": "Proceso 2",
                    "Num.DB": 5002,
                    "Descripcion": "Alarma 2",
                    "ComentarioDB": "c",
                    "Visibilidad": "Si",
                    "Num.Lista": "N/A",
                    "Txt.Lista": "Txt",
                },
            ),
        ],
    )
    _anadir_tabla(
        libro,
        "ENTIDADES",
        "Tabla_Entidades",
        ["Numero", "PLC.Tag", "Descripcion", "PLC.Comentario", "PLC.Tipo", "PLC.Index"],
        [
            [1, "ent_001", "Entidad 1", "Comentario", "int", 1],
            ["no es un numero", "ent_002", "", "", "int", ""],
        ],
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


#: El PLC del fixture de dispositivos: el mismo nombre que el PLC de TIA.
NOMBRE_PLC = "ZC_PLC_STD"

#: Las columnas de N_MAX del Excel del fixture: cabecera y valor del PLC.
N_MAX_EXCEL: tuple[tuple[str, int], ...] = (
    ("N_Max_EA", 20),
    ("N_Max_ED", 10),
    ("N_Max_M", 60),
    ("N_Max_M_SINA", 80),
    ("N_Max_M_VF", 70),
    ("N_Max_PID", 120),
    ("N_Max_SA", 30),
    ("N_Max_SD", 40),
    ("N_Max_TOT", 110),
    ("N_Max_TQ", 90),
    ("N_Max_TQ_AE", 100),
    ("N_Max_V", 50),
)

#: Las filas de la tabla de entradas digitales del Excel del fixture.
FILAS_DISP_ED: tuple[tuple[Any, ...], ...] = (
    (NOMBRE_PLC, "ED_001", 1, "ED_001", "Entrada digital 1", 3, 2),
    (NOMBRE_PLC, "ED_002", 2, "ED_002_NUEVO", "Entrada digital 2", 4, 3),
    (NOMBRE_PLC, "ED_003", 3, "ED_003", "Entrada digital 3", 5, 4),
    (NOMBRE_PLC, "ED_004", 4, "ED_004", "Entrada digital 4", 6, 5),
)

#: Lo que hay en el PLC: las constantes de usuario de cada tabla.
CONSTANTES_TIA: dict[str, tuple[tuple[str, int], ...]] = {
    "2000_Disp_ED": (
        ("ED_001", 1),
        ("ED_002", 2),
        ("ED_003", 3),
        ("ED_099", 99),
    ),
    "0_Config_Dispositivos": (
        ("N_MAX_DISP_ED", 5),
        ("N_MAX_DISP_EA", 20),
        ("N_MAX_DISP_M_VF", 70),
        ("N_MAX_DISP_TQ", 80),
        ("N_MAX_DISP_TOT", 110),
        ("N_MAX_DISP_PID", 115),
    ),
}


def xml_de_tabla(nombre: str, constantes: tuple[tuple[str, int], ...]) -> str:
    """El XML de una tabla de tags con las constantes de usuario dadas.

    Es el formato que escribe TIA al exportar una tabla de tags en plano:
    cada constante es un ``SW.Tags.PlcUserConstant`` con su ``<Name>`` (el
    ``plc_tag``) y su ``<Value>`` (el numero del slot).
    """
    partes = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<Document>",
        '  <SW.Tags.PlcTagTable ID="0">',
        "    <ObjectList>",
    ]
    for indice, (nombre_constante, valor) in enumerate(constantes, start=1):
        partes.append(
            f'      <SW.Tags.PlcUserConstant ID="{indice}">\n'
            f"        <AttributeList><Name>{nombre_constante}</Name>"
            f"<Value>{valor}</Value></AttributeList>\n"
            "      </SW.Tags.PlcUserConstant>"
        )
    partes += ["    </ObjectList>", "  </SW.Tags.PlcTagTable>", "</Document>", ""]
    return "\n".join(partes)


def escribir_excel_dispositivos(ruta: Path) -> Path:
    """Escribe el Excel del fixture: entradas digitales y los N_MAX.

    Solo la tabla de entradas digitales tiene filas: los demas dominios
    salen vacios, que es el caso normal de un Excel recienplantado.

    Args:
        ruta: donde se escribe.
    """
    libro = Workbook()
    libro.active.title = "CONFIG"
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_Dimensiones",
        ["PLC", *[columna for columna, _valor in N_MAX_EXCEL], "N_Max_ENT"],
        [[NOMBRE_PLC, *[valor for _columna, valor in N_MAX_EXCEL], 6]],
        con_plc=False,
    )
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_PLC",
        ["PLC"],
        [[NOMBRE_PLC]],
        con_plc=False,
    )
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_Procesos",
        ["PLC", "UID", "Codigo", "Nombre"],
        [[NOMBRE_PLC, 1, "PR1", "Proceso 1"]],
        con_plc=False,
    )
    _anadir_tabla(
        libro,
        "DISP_ED",
        "Tabla_Disp_ED",
        ["PLC", "UID", "Numero", "PLC.Tag", "Descripcion", "E.Byte", "E.Bit"],
        [list(fila) for fila in FILAS_DISP_ED],
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
def modelo(seccion: dict[str, Any]) -> ConfigArea:
    """El modelo del area: la seccion del ``config.json`` ya validada."""
    return config_area.cargar(seccion)


@pytest.fixture
def dorado() -> dict[str, Any]:
    """El resultado que el area daba antes de cambiar el formato del config.

    Lo fija ``tests/fixtures/expected/catalogo_alimentacion.json``: las
    pestañas, las tarjetas de N_MAX y las columnas con sus etiquetas. Cambiar
    el ``config.json`` no puede cambiar nada de eso.
    """
    ruta = RAIZ / "tests" / "fixtures" / "expected" / "catalogo_alimentacion.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


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
    """Un Excel maestro con dos filas de cada dominio."""
    return escribir_excel_completo(tmp_path / "completo.xlsx")


@pytest.fixture
def excel_dispositivos(tmp_path: Path) -> Path:
    """El Excel del fixture: entradas digitales y los N_MAX."""
    return escribir_excel_dispositivos(tmp_path / "maestro.xlsx")


@pytest.fixture
def constantes_tia() -> dict[str, tuple[tuple[str, int], ...]]:
    """Lo que hay en el PLC: las constantes de usuario de cada tabla."""
    return CONSTANTES_TIA


@pytest.fixture
def xml_tabla() -> Callable[[str, tuple[tuple[str, int], ...]], str]:
    """El XML de una tabla de tags con las constantes dadas."""
    return xml_de_tabla


# ── dobles de TIA ────────────────────────────────────────────────────────────


class TablaFalsa:
    """Una tabla de tags que exporta su XML al destino."""

    def __init__(
        self,
        nombre: str,
        constantes: tuple[tuple[str, int], ...],
        xml: Callable[[str, tuple[tuple[str, int], ...]], str],
    ) -> None:
        self._nombre = nombre
        self._constantes = constantes
        self._xml = xml

    def get_name(self) -> str:
        return self._nombre

    def export(
        self,
        target_directory_path: str,
        keep_folder_structure: bool = False,
    ) -> None:
        carpeta = Path(target_directory_path)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{self._nombre}.xml").write_text(
            self._xml(self._nombre, self._constantes),
            encoding="utf-8",
        )


class PlcFalso:
    """El PLC del fixture: solo tiene las tablas del fixture."""

    def __init__(
        self,
        constantes: dict[str, tuple[tuple[str, int], ...]],
        xml: Callable[[str, tuple[tuple[str, int], ...]], str],
    ) -> None:
        self.tablas = [
            TablaFalsa(nombre, valores, xml)
            for nombre, valores in constantes.items()
        ]

    def get_name(self) -> str:
        return NOMBRE_PLC

    def get_plc_tag_tables(self) -> list[TablaFalsa]:
        return self.tablas


class ProyectoFalso:
    """El proyecto abierto, con un solo PLC."""

    def __init__(self, plc: PlcFalso) -> None:
        self.plc = plc

    def get_plcs(self) -> list[PlcFalso]:
        return [self.plc]


class PortalFalso:
    """El portal de TIA."""

    def __init__(self, proyecto: ProyectoFalso) -> None:
        self.proyecto = proyecto

    def get_process_id(self) -> int:
        return 4242

    def get_project(self) -> ProyectoFalso:
        return self.proyecto

    def detach(self) -> None:
        pass


class TsFalso:
    """El modulo del SDK de Siemens, con un portal ya abierto."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def __init__(self, plc: PlcFalso) -> None:
        self.portal = PortalFalso(ProyectoFalso(plc))

    def get_installed_bundles(self) -> list[Any]:
        class _Bundle:
            def get_title(self) -> str:
                return "Siemens TIA Portal V18.0"

        return [_Bundle()]

    def attach_portal(self, portal_mode: str | None = None) -> PortalFalso:
        return self.portal

    def open_portal(self, portal_mode: str | None = None) -> PortalFalso:
        return self.portal

    def set_logging(self, path: str, console: bool) -> None:
        pass


class Entorno:
    """El almacen con el Excel del fixture y un TIA falso conectado.

    ``prevision()`` lanza el trabajo de la prevision y devuelve su resultado.
    """

    def __init__(
        self,
        servicio: Any,
        almacen: AlmacenExcel,
        modelo: ConfigArea,
        eventos: list[tuple[str, dict[str, Any]]],
    ) -> None:
        self.servicio = servicio
        self.almacen = almacen
        self.modelo = modelo
        self.eventos = eventos

    def prevision(self, sesion: Any = None) -> dict[str, Any]:
        """Lanza la prevision y devuelve su resultado."""
        job_id = self.servicio.lanzar(
            modulo_prevision.generar_prevision,
            plc=NOMBRE_PLC,
            almacen=self.almacen,
            config=self.modelo,
            sesion=sesion,
        )
        evento = self._esperar(job_id)
        assert evento["estado"] == "ok", evento.get("error")
        return evento["resultado"]

    def _esperar(self, job_id: str) -> dict[str, Any]:
        """Espera al evento de fin del trabajo."""
        limite = time.monotonic() + 5.0
        while time.monotonic() < limite:
            for tipo, carga in list(self.eventos):
                if tipo == "job" and carga["job"] == job_id:
                    return carga
            time.sleep(0.005)
        raise AssertionError(f"El trabajo {job_id} no termino.")


@pytest.fixture
def entorno_disp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_dispositivos: Path,
    constantes_tia: dict[str, tuple[tuple[str, int], ...]],
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> Any:
    """El almacen con el Excel del fixture y un TIA falso conectado."""
    almacen = AlmacenExcel()
    almacen.config = modelo
    almacen.volcar(excel_dispositivos)

    monkeypatch.setattr(
        modulo_prevision,
        "workdir_dispositivos",
        lambda: Workdir(
            base=tmp_path / "disp",
            preview_subcarpetas=("config", "disp"),
        ),
    )

    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: TsFalso(PlcFalso(constantes_tia, xml_tabla)),
    )
    conectar = servicio.lanzar(tia.conectar)
    _esperar_job(eventos, conectar)
    yield Entorno(servicio, almacen, modelo, eventos)
    servicio.parar()


def _esperar_job(
    eventos: list[tuple[str, dict[str, Any]]],
    job_id: str,
) -> dict[str, Any]:
    """Espera al evento de fin del trabajo indicado."""
    limite = time.monotonic() + 5.0
    while time.monotonic() < limite:
        for tipo, carga in list(eventos):
            if tipo == "job" and carga["job"] == job_id:
                return carga
        time.sleep(0.005)
    raise AssertionError(f"El trabajo {job_id} no termino.")
