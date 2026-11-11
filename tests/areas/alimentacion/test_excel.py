"""Tests del parseo del Excel maestro y de la cache del area.

Ningun test toca TIA: el Excel se construye aqui mismo y el portal no hace
falta para nada.

El test de paridad compara, dominio a dominio y fila a fila, con lo que
devuelven los parsers de ``main`` sobre el mismo Excel: el conjunto de campos
y todos los valores. Los valores esperados estan escritos aqui, sacados de
ejecutar ``main``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook

from zc_suite.areas.alimentacion.excel import almacen as modulo_almacen
from zc_suite.areas.alimentacion.excel import parser
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel

# ── los valores que espera main ──────────────────────────────────────────


#: Los dispositivos, tal y como los deja ``main``: una fila buena y una sucia.
ESPERADO_DISPOSITIVOS: dict[str, list[dict[str, Any]]] = {

    "DispED": [
        {
            "cfg_bit_entrada": "17",
            "cfg_byte_entrada": "16",
            "cfg_grupo_alarma": "20",
            "cfg_habilitar": "SI",
            "comentario_db": "Comentario del DB",
            "cuadro": "C1",
            "descripcion": "Entrada digital 1",
            "e_bit": 2,
            "e_byte": 3,
            "fat": "FAT_001",
            "gr_alarma": 13,
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "tag": "TAG_001",
            "uid": "ED_001",
        },
        {
            "cfg_bit_entrada": "",
            "cfg_byte_entrada": "",
            "cfg_grupo_alarma": "",
            "cfg_habilitar": "",
            "comentario_db": "",
            "cuadro": "",
            "descripcion": "",
            "e_bit": 0,
            "e_byte": 0,
            "fat": "",
            "gr_alarma": 0,
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "tag": "",
            "uid": "ED_002",
        },
    ],

    "DispEA": [
        {
            "cfg_byte_entrada": "16",
            "cfg_escaladomax": "19",
            "cfg_escaladomin": "18",
            "cfg_grupo_alarma": "20",
            "cfg_habilitar": "SI",
            "comentario_db": "Comentario del DB",
            "cuadro": "C1",
            "descripcion": "Entrada digital 1",
            "e_byte": 3,
            "fat": "FAT_001",
            "gr_alarma": 13,
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "rii": 0.5,
            "rsi": 100.5,
            "tag": "TAG_001",
            "uid": "ED_001",
            "unidades": "Litros",
        },
        {
            "cfg_byte_entrada": "",
            "cfg_escaladomax": "",
            "cfg_escaladomin": "",
            "cfg_grupo_alarma": "",
            "cfg_habilitar": "",
            "comentario_db": "",
            "cuadro": "",
            "descripcion": "",
            "e_byte": 0,
            "fat": "",
            "gr_alarma": 0,
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "rii": 1.5,
            "rsi": 0.0,
            "tag": "",
            "uid": "ED_002",
            "unidades": "",
        },
    ],

    "DispSA": [
        {
            "cfg_byte_entrada": "16",
            "cfg_escaladomax": "19",
            "cfg_escaladomin": "18",
            "cfg_grupo_alarma": "20",
            "cfg_habilitar": "SI",
            "comentario_db": "Comentario del DB",
            "cuadro": "C1",
            "descripcion": "Entrada digital 1",
            "e_byte": 3,
            "fat": "FAT_001",
            "gr_alarma": 13,
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "rii": 0.5,
            "rsi": 100.5,
            "tag": "TAG_001",
            "uid": "ED_001",
            "unidades": "Litros",
        },
        {
            "cfg_byte_entrada": "",
            "cfg_escaladomax": "",
            "cfg_escaladomin": "",
            "cfg_grupo_alarma": "",
            "cfg_habilitar": "",
            "comentario_db": "",
            "cuadro": "",
            "descripcion": "",
            "e_byte": 0,
            "fat": "",
            "gr_alarma": 0,
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "rii": 1.5,
            "rsi": 0.0,
            "tag": "",
            "uid": "ED_002",
            "unidades": "",
        },
    ],

    "DispSD": [
        {
            "cfg_bit_entrada": "17",
            "cfg_byte_entrada": "16",
            "cfg_grupo_alarma": "20",
            "cfg_habilitar": "SI",
            "comentario_db": "Comentario del DB",
            "cuadro": "C1",
            "descripcion": "Entrada digital 1",
            "fat": "FAT_001",
            "gr_alarma": 13,
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "s_bit": 5,
            "s_byte": 4,
            "tag": "TAG_001",
            "uid": "ED_001",
        },
        {
            "cfg_bit_entrada": "",
            "cfg_byte_entrada": "",
            "cfg_grupo_alarma": "",
            "cfg_habilitar": "",
            "comentario_db": "",
            "cuadro": "",
            "descripcion": "",
            "fat": "",
            "gr_alarma": 0,
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "s_bit": 0,
            "s_byte": 0,
            "tag": "",
            "uid": "ED_002",
        },
    ],

    "DispV": [
        {
            "cfg_bitactivacion": "26",
            "cfg_bitretornoreposo": "22",
            "cfg_bitretornotrabajo": "24",
            "cfg_byteactivacion": "25",
            "cfg_byteretornoreposo": "21",
            "cfg_byteretornotrabajo": "23",
            "cfg_grupoalarma": "20",
            "cfg_habilitar": "SI",
            "cfg_habitreposo": "27",
            "cfg_habitrtrabajo": "28",
            "comentario_db": "Comentario del DB",
            "cuadro": "C1",
            "descripcion": "Entrada digital 1",
            "fat": "FAT_001",
            "gr_alarma": 13,
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "rr_bit": 7,
            "rr_byte": 6,
            "rt_bit": 9,
            "rt_byte": 8,
            "s_bit": 5,
            "s_byte": 4,
            "tag": "TAG_001",
            "uid": "ED_001",
        },
        {
            "cfg_bitactivacion": "",
            "cfg_bitretornoreposo": "",
            "cfg_bitretornotrabajo": "",
            "cfg_byteactivacion": "",
            "cfg_byteretornoreposo": "",
            "cfg_byteretornotrabajo": "",
            "cfg_grupoalarma": "",
            "cfg_habilitar": "",
            "cfg_habitreposo": "",
            "cfg_habitrtrabajo": "",
            "comentario_db": "",
            "cuadro": "",
            "descripcion": "",
            "fat": "",
            "gr_alarma": 0,
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "rr_bit": 0,
            "rr_byte": 0,
            "rt_bit": 0,
            "rt_byte": 0,
            "s_bit": 0,
            "s_byte": 0,
            "tag": "",
            "uid": "ED_002",
        },
    ],

    "DispM": [
        {
            "cfg_bitactivacion": "26",
            "cfg_bitconfmarcha": "32",
            "cfg_bitretornotermico": "30",
            "cfg_byteactivacion": "25",
            "cfg_byteconfmarcha": "31",
            "cfg_byteretornotermico": "29",
            "cfg_grupoalarma": "20",
            "cfg_habilitar": "SI",
            "cfg_habretconfmarcha": "34",
            "cfg_habrettermico": "33",
            "comentario_db": "Comentario del DB",
            "cuadro": "C1",
            "descripcion": "Entrada digital 1",
            "fat": "FAT_001",
            "gr_alarma": 13,
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "rm_bit": 11,
            "rm_byte": 10,
            "rt_bit": 9,
            "rt_byte": 8,
            "s_bit": 5,
            "s_byte": 4,
            "tag": "TAG_001",
            "uid": "ED_001",
        },
        {
            "cfg_bitactivacion": "",
            "cfg_bitconfmarcha": "",
            "cfg_bitretornotermico": "",
            "cfg_byteactivacion": "",
            "cfg_byteconfmarcha": "",
            "cfg_byteretornotermico": "",
            "cfg_grupoalarma": "",
            "cfg_habilitar": "",
            "cfg_habretconfmarcha": "",
            "cfg_habrettermico": "",
            "comentario_db": "",
            "cuadro": "",
            "descripcion": "",
            "fat": "",
            "gr_alarma": 0,
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "rm_bit": 0,
            "rm_byte": 0,
            "rt_bit": 0,
            "rt_byte": 0,
            "s_bit": 0,
            "s_byte": 0,
            "tag": "",
            "uid": "ED_002",
        },
    ],

    "DispM_VF": [
        {
            "cfg_bitactivacion": "26",
            "cfg_bitconfmarcha": "32",
            "cfg_bitretornotermico": "30",
            "cfg_byteactivacion": "25",
            "cfg_byteanalogica": "35",
            "cfg_byteconfmarcha": "31",
            "cfg_byteretornotermico": "29",
            "cfg_grupoalarma": "20",
            "cfg_habilitar": "SI",
            "cfg_habretconfmarcha": "34",
            "cfg_habrettermico": "33",
            "comentario_db": "Comentario del DB",
            "cuadro": "C1",
            "descripcion": "Entrada digital 1",
            "fat": "FAT_001",
            "gr_alarma": 13,
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "rm_bit": 11,
            "rm_byte": 10,
            "rt_bit": 9,
            "rt_byte": 8,
            "s_bit": 5,
            "s_byte": 4,
            "sa_byte": 12,
            "tag": "TAG_001",
            "uid": "ED_001",
        },
        {
            "cfg_bitactivacion": "",
            "cfg_bitconfmarcha": "",
            "cfg_bitretornotermico": "",
            "cfg_byteactivacion": "",
            "cfg_byteanalogica": "",
            "cfg_byteconfmarcha": "",
            "cfg_byteretornotermico": "",
            "cfg_grupoalarma": "",
            "cfg_habilitar": "",
            "cfg_habretconfmarcha": "",
            "cfg_habrettermico": "",
            "comentario_db": "",
            "cuadro": "",
            "descripcion": "",
            "fat": "",
            "gr_alarma": 0,
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "rm_bit": 0,
            "rm_byte": 0,
            "rt_bit": 0,
            "rt_byte": 0,
            "s_bit": 0,
            "s_byte": 0,
            "sa_byte": 0,
            "tag": "",
            "uid": "ED_002",
        },
    ],

    "DispM_SINA": [
        {
            "cfg_bitretornotermico": "30",
            "cfg_byteretornotermico": "29",
            "cfg_cons_k": "38",
            "cfg_grupo_alarma": "20",
            "cfg_habilitar": "SI",
            "cfg_vel_max": "37",
            "cfg_vel_min": "36",
            "comentario_db": "Comentario del DB",
            "cons_k": 3.5,
            "cuadro": "C1",
            "descripcion": "Entrada digital 1",
            "fat": "FAT_001",
            "gr_alarma": 13,
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "rt_bit": 9,
            "rt_byte": 8,
            "tag": "TAG_001",
            "uid": "ED_001",
            "vel_max": 2.5,
            "vel_min": 1.5,
        },
        {
            "cfg_bitretornotermico": "",
            "cfg_byteretornotermico": "",
            "cfg_cons_k": "",
            "cfg_grupo_alarma": "",
            "cfg_habilitar": "",
            "cfg_vel_max": "",
            "cfg_vel_min": "",
            "comentario_db": "",
            "cons_k": 0.0,
            "cuadro": "",
            "descripcion": "",
            "fat": "",
            "gr_alarma": 0,
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "rt_bit": 0,
            "rt_byte": 0,
            "tag": "",
            "uid": "ED_002",
            "vel_max": 0.0,
            "vel_min": 0.0,
        },
    ],

    "DispTQ": [
        {
            "cfg_habilitar": "SI",
            "comentario_db": "Comentario del DB",
            "descripcion": "Entrada digital 1",
            "fat": "FAT_001",
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "tag": "TAG_001",
            "uid": "ED_001",
        },
        {
            "cfg_habilitar": "",
            "comentario_db": "",
            "descripcion": "",
            "fat": "",
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "tag": "",
            "uid": "ED_002",
        },
    ],

    "DispTQ_AE": [
        {
            "cfg_habilitar": "SI",
            "comentario_db": "Comentario del DB",
            "descripcion": "Entrada digital 1",
            "fat": "FAT_001",
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "tag": "TAG_001",
            "uid": "ED_001",
        },
        {
            "cfg_habilitar": "",
            "comentario_db": "",
            "descripcion": "",
            "fat": "",
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "tag": "",
            "uid": "ED_002",
        },
    ],

    "DispTOT": [
        {
            "cfg_bitentrada": "17",
            "cfg_byteentrada": "16",
            "cfg_habilitar": "SI",
            "cfg_tipo": "39",
            "comentario_db": "Comentario del DB",
            "descripcion": "Entrada digital 1",
            "e_bit": 2,
            "e_byte": 3,
            "fat": "FAT_001",
            "gr_alarma": 13,
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "incxpulso": 0.5,
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "proceso": "Proceso 1",
            "tag": "TAG_001",
            "tipo": "Tipo 1",
            "uid": "ED_001",
        },
        {
            "cfg_bitentrada": "",
            "cfg_byteentrada": "",
            "cfg_habilitar": "",
            "cfg_tipo": "",
            "comentario_db": "",
            "descripcion": "",
            "e_bit": 0,
            "e_byte": 0,
            "fat": "",
            "gr_alarma": 0,
            "hmi_index": 0,
            "hmi_texto": "",
            "incxpulso": 0.0,
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "proceso": "",
            "tag": "",
            "tipo": "",
            "uid": "ED_002",
        },
    ],

    "DispPID": [
        {
            "cfg_habilitar": "SI",
            "comentario_db": "Comentario del DB",
            "descripcion": "Entrada digital 1",
            "disp_tag": "Disp.Tag 1",
            "disp_tipo": "Disp.Tipo 1",
            "fat": "FAT_001",
            "hmi_index": 15,
            "hmi_texto": "Texto HMI",
            "numero": 1,
            "observaciones": "Observacion",
            "plc_comentario": "",
            "plc_index": 14,
            "plc_name": "PLC1",
            "plc_tag": "V_ED_001",
            "plc_tipo": "S7-1500",
            "proceso": "Proceso 1",
            "pv": "PV_1",
            "tag": "TAG_001",
            "uid": "ED_001",
        },
        {
            "cfg_habilitar": "",
            "comentario_db": "",
            "descripcion": "",
            "disp_tag": "",
            "disp_tipo": "",
            "fat": "",
            "hmi_index": 0,
            "hmi_texto": "",
            "numero": 0,
            "observaciones": "",
            "plc_comentario": "",
            "plc_index": 0,
            "plc_name": "PLC1",
            "plc_tag": "",
            "plc_tipo": "int",
            "proceso": "",
            "pv": "",
            "tag": "",
            "uid": "ED_002",
        },
    ],

}


#: El software, tal y como lo deja ``main``.
ESPERADO_SOFTWARE: dict[str, list[dict[str, Any]]] = {

    "Procesos": [
        {
            "alarmas": 16,
            "alm_hmi": 2,
            "codigo": "PR1",
            "index_pint": 4,
            "index_preal": 3,
            "nombre": "Proceso 1",
            "pint": 1,
            "plc_name": "PLC1",
            "preal": 1,
            "uid": 1,
        },
        {
            "alarmas": 7,
            "alm_hmi": 8,
            "codigo": "PR2",
            "index_pint": 10,
            "index_preal": 9,
            "nombre": "Proceso 2",
            "pint": 6,
            "plc_name": "PLC1",
            "preal": 5,
            "uid": 2,
        },
    ],

    "ParametrosEnteros": [
        {
            "codigo": "PR1",
            "comentario_db": "c",
            "descripcion": "PI1",
            "num_db": 3002,
            "num_lista": 0,
            "numero": "001",
            "plc_name": "PLC1",
            "proceso": "Proceso 1",
            "producto": "Producto",
            "tipo": "Contador",
            "txt_lista": "Txt",
            "uid": "PI_1_001",
            "visibilidad": "Si",
        },
        {
            "codigo": "PR2",
            "comentario_db": "c",
            "descripcion": "PI2",
            "num_db": 3003,
            "num_lista": 5,
            "numero": "002",
            "plc_name": "PLC1",
            "proceso": "Proceso 2",
            "producto": "Producto",
            "tipo": "Setpoint",
            "txt_lista": "Txt",
            "uid": "PI_1_002",
            "visibilidad": "Si",
        },
    ],

    "ParametrosReales": [
        {
            "codigo": "PR1",
            "comentario_db": "c",
            "descripcion": "PR1",
            "num_db": 3001,
            "num_lista": 1,
            "numero": "001",
            "plc_name": "PLC1",
            "proceso": "Proceso 1",
            "producto": "Producto",
            "tipo": "Setpoint",
            "txt_lista": "Txt",
            "uid": "PR_1_001",
            "visibilidad": "Si",
        },
        {
            "codigo": "PR2",
            "comentario_db": "c",
            "descripcion": "PR2",
            "num_db": 3002,
            "num_lista": "N/A",
            "numero": "002",
            "plc_name": "PLC1",
            "proceso": "Proceso 2",
            "producto": "Producto",
            "tipo": "Contador",
            "txt_lista": "Txt",
            "uid": "PR_1_002",
            "visibilidad": "Si",
        },
    ],

    "Alarmas": [
        {
            "comentario_db": "c",
            "descripcion": "Alarma 1",
            "num_db": 5001,
            "numero": "001",
            "plc_name": "PLC1",
            "proceso": "Proceso 1",
            "uid": "AL_1_001",
        },
        {
            "comentario_db": "c",
            "descripcion": "Alarma 2",
            "num_db": 5002,
            "numero": "002",
            "plc_name": "PLC1",
            "proceso": "Proceso 2",
            "uid": "AL_1_002",
        },
    ],

}


#: Las entidades, tal y como las deja ``main``.
ESPERADO_ENTIDADES = [
    {
        "descripcion": "Entidad 1",
        "numero": 1,
        "plc_comentario": "Comentario",
        "plc_index": 1,
        "plc_name": "PLC1",
        "plc_tag": "ent_001",
        "plc_tipo": 0,
    },
    {
        "descripcion": "",
        "numero": 0,
        "plc_comentario": "",
        "plc_index": 0,
        "plc_name": "PLC1",
        "plc_tag": "ent_002",
        "plc_tipo": 0,
    },
]


#: Los PLCs, tal y como los deja ``main``.
ESPERADO_PLCS = [
    {
        "plc": "PLC1",
        "uid": 1,
    },
    {
        "plc": "PLC2",
        "uid": 2,
    },
]


#: Los N_MAX por PLC, tal y como los deja ``main``.
ESPERADO_N_MAX = [
    {
        "N_MAX_DISP_EA": 20,
        "N_MAX_DISP_ED": 10,
        "N_MAX_DISP_M": 50,
        "N_MAX_DISP_M_SINA": 70,
        "N_MAX_DISP_M_VF": 60,
        "N_MAX_DISP_PID": 90,
        "N_MAX_DISP_SA": 30,
        "N_MAX_DISP_SD": 80,
        "N_MAX_DISP_TOT": 80,
        "N_MAX_DISP_TQ": 80,
        "N_MAX_DISP_TQ_AE": 80,
        "N_MAX_DISP_V": 40,
        "N_MAX_ENTIDAD": 6,
        "PLC": "PLC1",
    },
    {
        "N_MAX_DISP_EA": 21,
        "N_MAX_DISP_ED": 11,
        "N_MAX_DISP_M": 51,
        "N_MAX_DISP_M_SINA": 71,
        "N_MAX_DISP_M_VF": 61,
        "N_MAX_DISP_PID": 91,
        "N_MAX_DISP_SA": 31,
        "N_MAX_DISP_SD": 81,
        "N_MAX_DISP_TOT": 81,
        "N_MAX_DISP_TQ": 81,
        "N_MAX_DISP_TQ_AE": 81,
        "N_MAX_DISP_V": 41,
        "N_MAX_ENTIDAD": 7,
        "PLC": "PLC2",
    },
]


# ── la paridad con main ─────────────────────────────────────────────────────


def _tabla(datos: dict[str, Any], tipo: str) -> dict[str, Any]:
    """La tabla de un tipo de dispositivo del volcado."""
    for tabla in datos["dispositivos"]:
        if tabla["tipo"] == tipo:
            return tabla
    raise AssertionError(f"El volcado no tiene la tabla {tipo}.")


def test_los_dispositivos_son_los_de_main(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    """Cada tipo de dispositivo, con sus campos y sus valores, como ``main``."""
    datos = parser.leer_excel(excel_completo, seccion)

    for tipo, esperado in ESPERADO_DISPOSITIVOS.items():
        filas = _tabla(datos, tipo)["filas"]
        assert filas == esperado, f"el dominio {tipo} no sale como en main"


def test_el_software_es_el_de_main(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    """Procesos, parametros y alarmas, con sus campos y sus valores."""
    datos = parser.leer_excel(excel_completo, seccion)

    for dominio, esperado in ESPERADO_SOFTWARE.items():
        filas = datos["procesos"][dominio]["filas"]
        assert filas == esperado, f"el dominio {dominio} no sale como en main"


def test_las_entidades_los_plcs_y_los_n_max_son_los_de_main(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    """Las entidades, la lista de PLCs y los N_MAX por PLC."""
    datos = parser.leer_excel(excel_completo, seccion)

    assert datos["entidades"]["filas"] == ESPERADO_ENTIDADES
    assert datos["plcs"] == ESPERADO_PLCS
    assert datos["configuracion"]["filas"] == ESPERADO_N_MAX


def test_una_fila_sucia_no_tumba_la_carga(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    """``PLC.Tipo`` con texto vale ``0``, y la carga no falla.

    Es el caso real del Excel del operario: la plantilla trae ``"int"`` en
    la columna ``PLC.Tipo`` de las entidades.
    """
    datos = parser.leer_excel(excel_completo, seccion)

    entidades = datos["entidades"]["filas"]
    assert entidades[0]["plc_tipo"] == 0
    assert entidades[1]["plc_tipo"] == 0
    assert entidades[1]["numero"] == 0

    sucia = _tabla(datos, "DispED")["filas"][1]
    assert sucia["numero"] == 0
    assert sucia["e_byte"] == 0
    assert sucia["gr_alarma"] == 0
    assert sucia["plc_index"] == 0
    assert sucia["plc_tipo"] == "int"
    assert sucia["descripcion"] == ""


def test_una_fila_sin_uid_ni_numero_se_descarta(
    tmp_path: Path,
    crear_excel: Callable[..., Path],
    seccion: dict[str, Any],
) -> None:
    ruta = crear_excel(
        tmp_path / "sin_uid.xlsx",
        [["PLC1", "", None, "", "Entrada digital", 3, 2]],
    )

    datos = parser.leer_excel(ruta, seccion)

    assert _tabla(datos, "DispED")["filas"] == []


# ── los avisos ──────────────────────────────────────────────────────────────


def test_una_hoja_que_no_existe_avisa_y_no_rompe(
    tmp_path: Path,
    seccion: dict[str, Any],
) -> None:
    ruta = tmp_path / "vacio.xlsx"
    libro = Workbook()
    libro.save(ruta)

    datos = parser.leer_excel(ruta, seccion)

    assert _tabla(datos, "DispED")["filas"] == []
    assert "No se encuentra la hoja DISP_ED en el Excel" in datos["avisos"]
    assert "No se encuentra la hoja ENTIDADES en el Excel" in datos["avisos"]


def test_una_tabla_que_no_existe_avisa(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    libro = load_workbook(excel_completo)
    del libro["DISP_ED"].tables["Tabla_Disp_ED"]
    libro.save(excel_completo)

    datos = parser.leer_excel(excel_completo, seccion)

    assert "No se encuentra la tabla Tabla_Disp_ED en la hoja DISP_ED" in datos["avisos"]
    assert _tabla(datos, "DispED")["filas"] == []


def test_un_excel_completo_no_avisa_de_nada(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    assert datos["avisos"] == []


# ── las columnas que se ensenan ─────────────────────────────────────────────


def test_las_columnas_son_las_del_display_order(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    assert _tabla(datos, "DispED")["columnas"] == seccion["disp_catalog"]["display_order"][
        "DispED"
    ]
    assert datos["entidades"]["columnas"] == seccion["entidades_catalog"]["display_order"][
        "entidades"
    ]


def test_las_etiquetas_salen_del_col_labels(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    etiquetas = _tabla(datos, "DispED")["etiquetas"]
    assert etiquetas["numero"] == seccion["disp_catalog"]["col_labels"]["numero"]
    assert "plc_name" not in etiquetas or etiquetas["plc_name"] == "PLC"
    assert datos["procesos"]["Procesos"]["etiquetas"]["alm_hmi"] == "Alarmas HMI"
    assert datos["entidades"]["etiquetas"]["plc_tag"] == "PLC.Tag"


# ── la cache ────────────────────────────────────────────────────────────────


def test_el_almacen_guarda_el_volcado(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    almacen = AlmacenExcel()
    almacen.config = seccion

    almacen.volcar(excel_completo)

    assert almacen.cargado is True
    assert almacen.archivo == "completo.xlsx"
    assert almacen.cargado_en
    estado = almacen.estado()
    assert estado["cargado"] is True
    assert estado["plcs"] == ESPERADO_PLCS
    assert _tabla(estado, "DispED")["filas"][0]["plc_tag"] == "V_ED_001"


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
    assert _tabla(otro.estado(), "DispED")["filas"][0]["plc_tag"] == "V_ED_001"


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
