"""Donde vive cada dominio del Excel maestro.

Un dominio es una tabla nombrada: la hoja donde esta y los campos del
modelo. De los doce tipos de dispositivo, la hoja y la tabla las dice el
``config.json`` del area (``dispositivos.<tipo>.excel``); del resto, son
fijas.

Los campos son los de los DTO de ``main``: los mismos nombres y los mismos
tipos, para que las fases siguientes los usen tal cual.
"""
from __future__ import annotations

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.modelo import (
    CAMPOS_DISPOSITIVO,
    CAMPOS_PLC,
    DECIMAL,
    ENTERO,
    NUM_LISTA,
    Campo,
    Dominio,
)

#: Hoja de la configuracion global: dimensiones, PLCs y procesos.
HOJA_CONFIG = "CONFIG"

#: Hoja de las entradas y salidas analogicas.
HOJA_PARAM_INT = "P_INT"
HOJA_PARAM_REAL = "P_REAL"

#: Hoja de las alarmas.
HOJA_ALARMAS = "ALARMAS"

#: Hoja de las entidades.
HOJA_ENTIDADES = "ENTIDADES"

# ── los dispositivos ────────────────────────────────────────────────────────

_DISP_ED = Dominio(
    clave="ed",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=(
        *CAMPOS_DISPOSITIVO,
        Campo("e_byte", "E.Byte", ENTERO),
        Campo("e_bit", "E.Bit", ENTERO),
        Campo("gr_alarma", "Gr.Alarma", ENTERO),
        Campo("cuadro", "Cuadro"),
        Campo("observaciones", "Observaciones"),
        Campo("cfg_byte_entrada", "Cfg.ByteEntrada"),
        Campo("cfg_bit_entrada", "Cfg.BitEntrada"),
        Campo("cfg_grupo_alarma", "Cfg.GrupoAlarma"),
    ),
)

_DISP_EA = Dominio(
    clave="ea",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=(
        *CAMPOS_DISPOSITIVO,
        Campo("e_byte", "E.Byte", ENTERO),
        Campo("unidades", ("UNIDADES", "Unidades")),
        Campo("rii", "RII", DECIMAL),
        Campo("rsi", "RSI", DECIMAL),
        Campo("gr_alarma", "Gr.Alarma", ENTERO),
        Campo("cuadro", "Cuadro"),
        Campo("observaciones", "Observaciones"),
        Campo("cfg_byte_entrada", "Cfg.ByteEntrada"),
        Campo("cfg_escaladomin", "Cfg.EscaladoMin"),
        Campo("cfg_escaladomax", "Cfg.EscaladoMax"),
        Campo("cfg_grupo_alarma", "Cfg.GrupoAlarma"),
    ),
)

_DISP_SA = Dominio(
    clave="sa",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=_DISP_EA.campos,
)

_DISP_SD = Dominio(
    clave="sd",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=(
        *CAMPOS_DISPOSITIVO,
        Campo("s_byte", "S.Byte", ENTERO),
        Campo("s_bit", "S.Bit", ENTERO),
        Campo("gr_alarma", "Gr.Alarma", ENTERO),
        Campo("cuadro", "Cuadro"),
        Campo("observaciones", "Observaciones"),
        Campo("cfg_byte_entrada", "Cfg.ByteEntrada"),
        Campo("cfg_bit_entrada", "Cfg.BitEntrada"),
        Campo("cfg_grupo_alarma", "Cfg.GrupoAlarma"),
    ),
)

_DISP_V = Dominio(
    clave="v",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=(
        *CAMPOS_DISPOSITIVO,
        Campo("s_byte", "S.Byte", ENTERO),
        Campo("s_bit", "S.Bit", ENTERO),
        Campo("rr_byte", "RR.Byte", ENTERO),
        Campo("rr_bit", "RR.Bit", ENTERO),
        Campo("rt_byte", "RT.Byte", ENTERO),
        Campo("rt_bit", "RT.Bit", ENTERO),
        Campo("gr_alarma", "Gr.Alarma", ENTERO),
        Campo("cuadro", "Cuadro"),
        Campo("observaciones", "Observaciones"),
        Campo("cfg_byteretornoreposo", "Cfg.ByteRetornoReposo"),
        Campo("cfg_bitretornoreposo", "Cfg.BitRetornoReposo"),
        Campo("cfg_byteretornotrabajo", "Cfg.ByteRetornoTrabajo"),
        Campo("cfg_bitretornotrabajo", "Cfg.BitRetornoTrabajo"),
        Campo("cfg_byteactivacion", "Cfg.ByteActivacion"),
        Campo("cfg_bitactivacion", "Cfg.BitActivacion"),
        Campo("cfg_habitreposo", "Cfg.HabRetReposo"),
        Campo("cfg_habitrtrabajo", "Cfg.HabRetTrabajo"),
        Campo("cfg_grupoalarma", "Cfg.GrupoAlarma"),
    ),
)

_DISP_M = Dominio(
    clave="m",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=(
        *CAMPOS_DISPOSITIVO,
        Campo("s_byte", "S.Byte", ENTERO),
        Campo("s_bit", "S.Bit", ENTERO),
        Campo("rt_byte", "RT.Byte", ENTERO),
        Campo("rt_bit", "RT.Bit", ENTERO),
        Campo("rm_byte", "RM.Byte", ENTERO),
        Campo("rm_bit", "RM.Bit", ENTERO),
        Campo("gr_alarma", "Gr.Alarma", ENTERO),
        Campo("cuadro", "Cuadro"),
        Campo("observaciones", "Observaciones"),
        Campo("cfg_byteretornotermico", "Cfg.ByteRetornoTermico"),
        Campo("cfg_bitretornotermico", "Cfg.BitRetornoTermico"),
        Campo("cfg_byteconfmarcha", "Cfg.ByteConfMarcha"),
        Campo("cfg_bitconfmarcha", "Cfg.BitConfMarcha"),
        Campo("cfg_byteactivacion", "Cfg.ByteActivacion"),
        Campo("cfg_bitactivacion", "Cfg.BitActivacion"),
        Campo("cfg_habrettermico", "Cfg.HabRetTermico"),
        Campo("cfg_habretconfmarcha", "Cfg.HabRetConfMarcha"),
        Campo("cfg_grupoalarma", "Cfg.GrupoAlarma"),
    ),
)

_DISP_M_VF = Dominio(
    clave="m_vf",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=(
        *_DISP_M.campos,
        Campo("sa_byte", "SA.Byte", ENTERO),
        Campo("cfg_byteanalogica", "Cfg.ByteAnalogica"),
    ),
)

_DISP_M_SINA = Dominio(
    clave="m_sina",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=(
        *CAMPOS_DISPOSITIVO,
        Campo("rt_byte", "RT.Byte", ENTERO),
        Campo("rt_bit", "RT.Bit", ENTERO),
        Campo("vel_min", "Vel.Min", DECIMAL),
        Campo("vel_max", "Vel.Max", DECIMAL),
        Campo("cons_k", "ConsK", DECIMAL),
        Campo("gr_alarma", "Gr.Alarma", ENTERO),
        Campo("cuadro", "Cuadro"),
        Campo("observaciones", "Observaciones"),
        Campo("cfg_byteretornotermico", "Cfg.ByteRetornoTermico"),
        Campo("cfg_bitretornotermico", "Cfg.BitRetornoTermico"),
        Campo("cfg_vel_min", "Cfg.VelMin"),
        Campo("cfg_vel_max", "Cfg.VelMax"),
        Campo("cfg_cons_k", "Cfg.ConstK"),
        Campo("cfg_grupo_alarma", "Cfg.GrupoAlarma"),
    ),
)

_DISP_TQ = Dominio(
    clave="tq",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=(
        *CAMPOS_DISPOSITIVO,
        Campo("observaciones", "Observaciones"),
    ),
)

_DISP_TQ_AE = Dominio(
    clave="tq_ae",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=_DISP_TQ.campos,
)

_DISP_TOT = Dominio(
    clave="tot",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=(
        *CAMPOS_DISPOSITIVO,
        Campo("tipo", "Tipo"),
        Campo("e_byte", "E.Byte", ENTERO),
        Campo("e_bit", "E.Bit", ENTERO),
        Campo("incxpulso", "IncXPulso", DECIMAL),
        Campo("gr_alarma", "Gr.Alarma", ENTERO),
        Campo("proceso", "Proceso"),
        Campo("observaciones", "Observaciones"),
        Campo("cfg_byteentrada", "Cfg.ByteEntrada"),
        Campo("cfg_bitentrada", "Cfg.BitEntrada"),
        Campo("cfg_tipo", "Cfg.Tipo"),
    ),
)

_DISP_PID = Dominio(
    clave="pid",
    catalogo="disp",
    descartar_si_vacias=("uid", "numero"),
    campos=(
        *CAMPOS_DISPOSITIVO,
        Campo("proceso", "Proceso"),
        Campo("pv", "PV"),
        Campo("disp_tipo", "Disp.Tipo"),
        Campo("disp_tag", "Disp.Tag"),
        Campo("observaciones", "Observaciones"),
    ),
)

#: Los doce tipos de dispositivo, por clave del ``config.json``.
DISPOSITIVOS: dict[str, Dominio] = {
    dominio.clave: dominio
    for dominio in (
        _DISP_ED,
        _DISP_EA,
        _DISP_SA,
        _DISP_SD,
        _DISP_V,
        _DISP_M,
        _DISP_M_VF,
        _DISP_M_SINA,
        _DISP_TQ,
        _DISP_TQ_AE,
        _DISP_TOT,
        _DISP_PID,
    )
}

# ── el software ─────────────────────────────────────────────────────────────

_CAMPOS_PARAMETRO = (
    Campo("uid", "UID"),
    Campo("numero", "Numero"),
    Campo("proceso", "Proceso"),
    Campo("codigo", "Codigo"),
    Campo("num_db", "Num.DB", ENTERO),
    Campo("producto", "Producto"),
    Campo("tipo", "Tipo"),
    Campo("descripcion", "Descripcion"),
    Campo("comentario_db", "ComentarioDB"),
    Campo("visibilidad", "Visibilidad"),
    Campo("num_lista", "Num.Lista", NUM_LISTA),
    Campo("txt_lista", "Txt.Lista"),
    Campo("plc_name", "PLC"),
)

PROCESOS = Dominio(
    clave="Procesos",
    hoja=HOJA_CONFIG,
    tabla="Tabla_Procesos",
    catalogo="proc",
    exigir_no_vacias=("uid",),
    campos=(
        Campo("uid", "UID", ENTERO),
        Campo("nombre", "Nombre"),
        Campo("codigo", "Codigo"),
        Campo("preal", "PReal", ENTERO),
        Campo("index_preal", "Index_Preal", ENTERO),
        Campo("pint", "PInt", ENTERO),
        Campo("index_pint", "Index_Pint", ENTERO),
        Campo("alarmas", "Alarmas", ENTERO),
        Campo("alm_hmi", "Alarmas_Hmi", ENTERO),
        Campo("plc_name", "PLC"),
    ),
)

PARAMETROS_ENTEROS = Dominio(
    clave="ParametrosEnteros",
    hoja=HOJA_PARAM_INT,
    tabla="Tabla_PInt",
    catalogo="proc",
    exigir_no_vacias=("uid",),
    campos=_CAMPOS_PARAMETRO,
)

PARAMETROS_REALES = Dominio(
    clave="ParametrosReales",
    hoja=HOJA_PARAM_REAL,
    tabla="Tabla_PReal",
    catalogo="proc",
    exigir_no_vacias=("uid",),
    campos=_CAMPOS_PARAMETRO,
)

ALARMAS = Dominio(
    clave="Alarmas",
    hoja=HOJA_ALARMAS,
    tabla="Tabla_Alarmas",
    catalogo="proc",
    exigir_no_vacias=("uid",),
    campos=(
        Campo("uid", "UID"),
        Campo("numero", "Numero"),
        Campo("proceso", "Proceso"),
        Campo("num_db", "Num.DB", ENTERO),
        Campo("descripcion", "Descripcion"),
        Campo("comentario_db", "ComentarioDB"),
        Campo("plc_name", "PLC"),
    ),
)

#: Los cuatro dominios del software, en el orden de las sub-pestanas.
SOFTWARE: tuple[Dominio, ...] = (
    PROCESOS,
    PARAMETROS_ENTEROS,
    PARAMETROS_REALES,
    ALARMAS,
)

# ── las entidades, los PLCs y las dimensiones ───────────────────────────────

ENTIDADES = Dominio(
    clave="Entidades",
    hoja=HOJA_ENTIDADES,
    tabla="Tabla_Entidades",
    catalogo="entidades",
    exigir_no_vacias=("plc_name", "plc_tag"),
    exigir_no_negativo=("numero",),
    campos=(
        Campo("numero", "Numero", ENTERO),
        Campo("plc_name", "PLC"),
        Campo("plc_tag", "PLC.Tag"),
        Campo("descripcion", "Descripcion"),
        Campo("plc_comentario", "PLC.Comentario"),
        Campo("plc_tipo", "PLC.Tipo", ENTERO),
        Campo("plc_index", "PLC.Index", ENTERO),
    ),
)

PLCS = Dominio(
    clave="PLCs",
    hoja=HOJA_CONFIG,
    tabla="Tabla_PLC",
    exigir_no_vacias=("uid", "plc"),
    exigir_plc=False,
    campos=CAMPOS_PLC,
)

#: La tabla de N_MAX por PLC. Sus campos salen del catalogo, no son fijos.
DIMENSIONES = Dominio(
    clave="Configuracion",
    hoja=HOJA_CONFIG,
    tabla="Tabla_Dimensiones",
    exigir_no_vacias=("PLC",),
    exigir_plc=False,
    campos=(),
)


def destino_de_dispositivo(clave: str, config: ConfigArea) -> tuple[str, str]:
    """La hoja y la tabla del Excel de un tipo de dispositivo.

    Args:
        clave: la clave del tipo en el ``config.json``.
        config: el modelo del area.

    Returns:
        La tupla ``(hoja, tabla)``. Vacia si el config no tiene ese tipo.
    """
    dispositivo = config.dispositivos.get(clave)
    if dispositivo is None:
        return "", ""
    return dispositivo.excel.hoja, dispositivo.excel.tabla
