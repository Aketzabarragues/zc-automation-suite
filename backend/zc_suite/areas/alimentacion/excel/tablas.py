"""Como esta repartido el Excel maestro: hojas, tablas y cabeceras.

El Excel del operario es un ``.xlsx`` con **tablas nombradas** (ListObject).
Cada dominio vive en una hoja y una tabla. Las columnas se renombran a los
nombres de campo que usa la SPA, con un mapa explicito: el Excel trae
cabeceras literales (``"PLC.Tag"``, ``"E.Byte"``) y la SPA enseña nombres de
campo (``plc_tag``, ``e_byte``).

Este modulo es puro: no lee ficheros ni habla con nadie.
"""
from __future__ import annotations

from typing import Any

#: Hoja de la configuracion global (N_MAX, PLCs y Procesos).
HOJA_CONFIG = "CONFIG"

#: Tabla de N_MAX por PLC.
TABLA_N_MAX = "Tabla_Dimensiones"

#: Tabla de la lista canonica de PLCs.
TABLA_PLC = "Tabla_PLC"

#: Tabla de procesos.
TABLA_PROCESOS = "Tabla_Procesos"

#: Hoja y tabla de los parametros enteros.
HOJA_PARAM_INT = "P_INT"
TABLA_PARAM_INT = "Tabla_PInt"

#: Hoja y tabla de los parametros reales.
HOJA_PARAM_REAL = "P_REAL"
TABLA_PARAM_REAL = "Tabla_PReal"

#: Hoja y tabla de las alarmas.
HOJA_ALARMAS = "ALARMAS"
TABLA_ALARMAS = "Tabla_Alarmas"

#: Hoja y tabla de las entidades.
HOJA_ENTIDADES = "ENTIDADES"
TABLA_ENTIDADES = "Tabla_Entidades"

#: Los cuatro subdominios de los procesos, con su clave, hoja y tabla.
SUBDOMINIOS_PROCESOS: tuple[tuple[str, str, str], ...] = (
    ("Procesos", HOJA_CONFIG, TABLA_PROCESOS),
    ("ParametrosEnteros", HOJA_PARAM_INT, TABLA_PARAM_INT),
    ("ParametrosReales", HOJA_PARAM_REAL, TABLA_PARAM_REAL),
    ("Alarmas", HOJA_ALARMAS, TABLA_ALARMAS),
)

#: Cabecera del Excel -> nombre de campo de la SPA.
CABECERAS: dict[str, str] = {
    "PLC": "plc_name",
    "Numero": "numero",
    "Tag": "tag",
    "Descripcion": "descripcion",
    "FAT": "fat",
    "E.Byte": "e_byte",
    "E.Bit": "e_bit",
    "Gr.Alarma": "gr_alarma",
    "Cuadro": "cuadro",
    "Observaciones": "observaciones",
    "UID": "uid",
    "PLC.Tag": "plc_tag",
    "PLC.Tipo": "plc_tipo",
    "PLC.Index": "plc_index",
    "PLC.Comentario": "plc_comentario",
    "Hmi.Index": "hmi_index",
    "Hmi.Texto": "hmi_texto",
    "Cfg.Habilitar": "cfg_habilitar",
    "Cfg.ByteEntrada": "cfg_byte_entrada",
    "Cfg.BitEntrada": "cfg_bit_entrada",
    "Cfg.GrupoAlarma": "cfg_grupo_alarma",
    "ComentarioDB": "comentario_db",
    "S.Byte": "s_byte",
    "S.Bit": "s_bit",
    "RR.Byte": "rr_byte",
    "RR.Bit": "rr_bit",
    "RT.Byte": "rt_byte",
    "RT.Bit": "rt_bit",
    "RM.Byte": "rm_byte",
    "RM.Bit": "rm_bit",
    "SA.Byte": "sa_byte",
    "UNIDADES": "unidades",
    "Unidades": "unidades",
    "RII": "rii",
    "RSI": "rsi",
    "ConsK": "cons_k",
    "Vel.Min": "vel_min",
    "Vel.Max": "vel_max",
    "IncXPulso": "incxpulso",
    "Proceso": "proceso",
    "PV": "pv",
    "Disp.Tipo": "disp_tipo",
    "Disp.Tag": "disp_tag",
    "Codigo": "codigo",
    "Nombre": "nombre",
    "Num.DB": "num_db",
    "PInt": "pint",
    "PReal": "preal",
    "Alarmas": "alarmas",
    "Alarmas_Hmi": "alm_hmi",
    "Txt.Lista": "txt_lista",
    "Visibilidad": "visibilidad",
    "Producto": "producto",
    "Tipo": "tipo",
    "Index_Pint": "index_pint",
    "Index_Preal": "index_preal",
}

#: Campos cuyo valor es un entero. Los demas son texto.
CAMPOS_ENTEROS = frozenset(
    {
        "numero",
        "e_byte",
        "e_bit",
        "gr_alarma",
        "plc_index",
        "hmi_index",
        "s_byte",
        "s_bit",
        "rr_byte",
        "rr_bit",
        "rt_byte",
        "rt_bit",
        "rm_byte",
        "rm_bit",
        "sa_byte",
        "num_db",
        "pint",
        "preal",
        "alarmas",
        "alm_hmi",
        "index_pint",
        "index_preal",
    }
)

#: Campos cuyo valor es un numero decimal.
CAMPOS_DECIMALES = frozenset(
    {
        "rii",
        "rsi",
        "cons_k",
        "vel_min",
        "vel_max",
        "incxpulso",
    }
)

#: Columna del Excel con el N_MAX de las entidades.
COLUMNA_N_MAX_ENTIDADES = "N_Max_ENT"

#: Nombre canonico del N_MAX de las entidades.
N_MAX_ENTIDADES = "N_MAX_ENTIDAD"


def canonico_de_tipo(clave: str) -> str:
    """El nombre canonico de un tipo de dispositivo.

    ``"ed"`` -> ``"DispED"``, ``"m_vf"`` -> ``"DispM_VF"``, ``"tq_ae"`` ->
    ``"DispTQ_AE"``.

    Args:
        clave: la clave del tipo en el ``config.json``.
    """
    return f"Disp{clave.upper()}"


def destino_de_dispositivo(clave: str, config: dict[str, Any]) -> tuple[str, str, str]:
    """La hoja, la tabla y el canonico de un tipo de dispositivo.

    Args:
        clave: la clave del tipo en el ``config.json``.
        config: la seccion del area en el ``config.json``.

    Returns:
        La tupla ``(hoja, tabla, canonico)``. Por defecto son los nombres
        derivados de la clave; el ``excel_target`` del config los sobreescribe.
    """
    dispositivos = config.get("Dispositivos", {})
    objetivo = dispositivos.get(clave, {})
    excel_target = objetivo.get("excel_target", {}) if isinstance(objetivo, dict) else {}
    hoja = excel_target.get("sheet") or f"DISP_{clave.upper()}"
    tabla = excel_target.get("table") or f"Tabla_Disp_{clave.upper()}"
    canonico = excel_target.get("canonical") or canonico_de_tipo(clave)
    return str(hoja), str(tabla), str(canonico)


def columnas_de_dispositivo(canonico: str, config: dict[str, Any]) -> list[str]:
    """Las columnas que se ensenan de un tipo de dispositivo.

    Args:
        canonico: el nombre canonico del tipo.
        config: la seccion del area en el ``config.json``.

    Returns:
        Los nombres de campo, en el orden del catalogo. Vacio si el
        catalogo no dice nada de ese tipo.
    """
    orden = config.get("disp_catalog", {}).get("display_order", {})
    columnas = orden.get(canonico, [])
    return [str(columna) for columna in columnas]


def columnas_de_configuracion(config: dict[str, Any]) -> list[str]:
    """Las columnas de la vista de configuracion: PLC y los N_MAX.

    Args:
        config: la seccion del area en el ``config.json``.
    """
    columnas = ["PLC"]
    for entrada in config.get("n_max_catalog", []):
        nombre = entrada.get("name")
        if nombre:
            columnas.append(str(nombre))
    return columnas


def columnas_de_procesos(subdominio: str, config: dict[str, Any]) -> list[str]:
    """Las columnas de un subdominio de los procesos.

    Args:
        subdominio: ``"Procesos"``, ``"ParametrosEnteros"``,
            ``"ParametrosReales"`` o ``"Alarmas"``.
        config: la seccion del area en el ``config.json``.
    """
    claves = {
        "Procesos": "procesos",
        "ParametrosEnteros": "parametros_int",
        "ParametrosReales": "parametros_real",
        "Alarmas": "alarmas",
    }
    clave = claves.get(subdominio, "")
    orden = config.get("proc_catalog", {}).get("display_order", {})
    columnas = orden.get(clave, [])
    return [str(columna) for columna in columnas]


def columnas_de_entidades(config: dict[str, Any]) -> list[str]:
    """Las columnas de la vista de entidades.

    Args:
        config: la seccion del area en el ``config.json``.
    """
    orden = config.get("entidades_catalog", {}).get("display_order", {})
    columnas = orden.get("entidades", [])
    return [str(columna) for columna in columnas]


def valor_n_max_de_fila(fila: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Los N_MAX de una fila de la tabla de dimensiones.

    Args:
        fila: la fila, con las cabeceras literales del Excel.
        config: la seccion del area en el ``config.json``.

    Returns:
        Un dict ``{nombre_canonico: valor}`` con un N_MAX por entrada del
        catalogo, mas ``N_MAX_ENTIDAD`` si la columna esta en la tabla.
    """
    valores: dict[str, Any] = {}
    for entrada in config.get("n_max_catalog", []):
        nombre = entrada.get("name")
        columna = entrada.get("excel_column")
        if not nombre or not columna:
            continue
        valores[str(nombre)] = fila.get(str(columna), 0)
    if COLUMNA_N_MAX_ENTIDADES in fila:
        valores[N_MAX_ENTIDADES] = fila[COLUMNA_N_MAX_ENTIDADES]
    return valores
