"""El parseo del Excel maestro: la paridad con ``main`` y los avisos.

El test de paridad compara, dominio a dominio y fila a fila, con lo que
devuelven los parsers de ``main`` sobre el mismo Excel: el conjunto de campos
y todos los valores. Los valores esperados estan escritos aqui, sacados de
ejecutar ``main``.

Ningun test toca TIA: el Excel se construye aqui mismo.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

from zc_suite.areas.alimentacion.excel import parser

ESPERADO_DISPOSITIVOS: dict[str, list[dict[str, Any]]] = {

    "ed": [
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

    "ea": [
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

    "sa": [
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

    "sd": [
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

    "v": [
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

    "m": [
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

    "m_vf": [
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

    "m_sina": [
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

    "tq": [
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

    "tq_ae": [
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

    "tot": [
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

    "pid": [
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


def test_los_dispositivos_son_los_de_main(
    excel_completo: Path,
    seccion: dict[str, Any],
    tabla: Callable[..., dict[str, Any]],
) -> None:
    """Cada tipo de dispositivo, con sus campos y sus valores, como ``main``."""
    datos = parser.leer_excel(excel_completo, seccion)

    for tipo, esperado in ESPERADO_DISPOSITIVOS.items():
        filas = tabla(datos, tipo)["filas"]
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
    esperado_plcs: dict[str, Any],
) -> None:
    """Las entidades, la lista de PLCs y los N_MAX por PLC."""
    datos = parser.leer_excel(excel_completo, seccion)

    assert datos["entidades"]["filas"] == ESPERADO_ENTIDADES
    assert datos["plcs"] == esperado_plcs
    assert datos["configuracion"]["filas"] == ESPERADO_N_MAX


def test_una_fila_sucia_no_tumba_la_carga(
    excel_completo: Path,
    seccion: dict[str, Any],
    tabla: Callable[..., dict[str, Any]],
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

    sucia = tabla(datos, "ed")["filas"][1]
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
    tabla: Callable[..., dict[str, Any]],
) -> None:
    ruta = crear_excel(
        tmp_path / "sin_uid.xlsx",
        [["PLC1", "", None, "", "Entrada digital", 3, 2]],
    )

    datos = parser.leer_excel(ruta, seccion)

    assert tabla(datos, "ed")["filas"] == []


def test_una_hoja_que_no_existe_avisa_y_no_rompe(
    tmp_path: Path,
    seccion: dict[str, Any],
    tabla: Callable[..., dict[str, Any]],
) -> None:
    ruta = tmp_path / "vacio.xlsx"
    libro = Workbook()
    libro.save(ruta)

    datos = parser.leer_excel(ruta, seccion)

    assert tabla(datos, "ed")["filas"] == []
    assert "No se encuentra la hoja DISP_ED en el Excel" in datos["avisos"]
    assert "No se encuentra la hoja ENTIDADES en el Excel" in datos["avisos"]


def test_una_tabla_que_no_existe_avisa(
    excel_completo: Path,
    seccion: dict[str, Any],
    tabla: Callable[..., dict[str, Any]],
) -> None:
    libro = load_workbook(excel_completo)
    del libro["DISP_ED"].tables["Tabla_Disp_ED"]
    libro.save(excel_completo)

    datos = parser.leer_excel(excel_completo, seccion)

    assert "No se encuentra la tabla Tabla_Disp_ED en la hoja DISP_ED" in datos["avisos"]
    assert tabla(datos, "ed")["filas"] == []


def test_un_excel_completo_no_avisa_de_nada(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    assert datos["avisos"] == []


def test_las_columnas_no_cambian_con_el_formato_del_config(
    excel_completo: Path,
    seccion: dict[str, Any],
    dorado: dict[str, Any],
) -> None:
    """Las columnas y sus etiquetas son las de antes, dominio a dominio."""
    datos = parser.leer_excel(excel_completo, seccion)

    assert {
        vista["tipo"]: {"columnas": vista["columnas"], "etiquetas": vista["etiquetas"]}
        for vista in datos["dispositivos"]
    } == dorado["columnas"]["dispositivos"]
    assert {
        clave: {"columnas": vista["columnas"], "etiquetas": vista["etiquetas"]}
        for clave, vista in datos["procesos"].items()
    } == dorado["columnas"]["procesos"]
    assert {
        "columnas": datos["entidades"]["columnas"],
        "etiquetas": datos["entidades"]["etiquetas"],
    } == dorado["columnas"]["entidades"]
    assert {
        "columnas": datos["configuracion"]["columnas"],
        "etiquetas": datos["configuracion"]["etiquetas"],
    } == dorado["columnas"]["configuracion"]
