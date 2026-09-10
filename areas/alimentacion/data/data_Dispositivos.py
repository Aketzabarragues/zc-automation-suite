"""areas.alimentacion.data.data_Dispositivos — Data Blocks de dispositivos.

Fase 3, paso 3.2.2.  Migrado de ``areas/alimentacion/domain/models/excel_cache.py``.
Agrupa SOLO la familia "Dispositivos" en data pura (Protocol + 6 Disp*).
``DimensionesDispositivos`` migra a su propio archivo
``data_Dimensiones.py`` (subdivision del plan original) para mantener
cada archivo < 200 lineas segun la regla del operario.

El legacy sigue coexistiendo (DA-006) y exporta los mismos nombres para
back-compat hasta Fase 4 (4.0.2: borrar ``areas/alimentacion/domain/``).

Convencion: ``frozen=True``, sin I/O, sin imports de
``siemens_tia_scripting`` u openpyxl.  ``str`` -> default ``""``,
``int`` -> default ``0``, ``float`` -> default ``0.0``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class Dispositivo(Protocol):
    """Contrato comun a todo dispositivo instanciable.

    Atributos: ``numero``, ``plc_tag``, ``plc_comentario``,
    ``descripcion``, ``uid`` (clave inmutable a traves de renombres).
    """

    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str


@dataclass(frozen=True)
class DispED:
    """Display Entradas Digitales (bits)."""

    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    tag: str = ""
    fat: str = ""
    e_byte: int = 0
    e_bit: int = 0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    cfg_habilitar: str = ""
    cfg_byte_entrada: str = ""
    cfg_bit_entrada: str = ""
    cfg_grupo_alarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispEA:
    """Display Entradas Analogicas (palabras)."""

    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    tag: str = ""
    fat: str = ""
    e_byte: int = 0
    unidades: str = ""
    rii: float = 0.0
    rsi: float = 0.0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    cfg_habilitar: str = ""
    cfg_byte_entrada: str = ""
    cfg_escaladomin: str = ""
    cfg_escaladomax: str = ""
    cfg_grupo_alarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispSA:
    """Display Salidas Analogicas (identico a DispEA, sentido invertido)."""

    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    tag: str = ""
    fat: str = ""
    e_byte: int = 0
    unidades: str = ""
    rii: float = 0.0
    rsi: float = 0.0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    cfg_habilitar: str = ""
    cfg_byte_entrada: str = ""
    cfg_escaladomin: str = ""
    cfg_escaladomax: str = ""
    cfg_grupo_alarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispV:
    """Display Variables internas (sin E/S fisica asociada)."""

    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    tag: str = ""
    fat: str = ""
    s_byte: int = 0
    s_bit: int = 0
    rr_byte: int = 0
    rr_bit: int = 0
    rt_byte: int = 0
    rt_bit: int = 0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    cfg_habilitar: str = ""
    cfg_byteretornoreposo: str = ""
    cfg_bitretornoreposo: str = ""
    cfg_byteretornotrabajo: str = ""
    cfg_bitretornotrabajo: str = ""
    cfg_byteactivacion: str = ""
    cfg_bitactivacion: str = ""
    cfg_habitreposo: str = ""
    cfg_habitrtrabajo: str = ""
    cfg_grupoalarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispM:
    """Display Motor (digital)."""

    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    tag: str = ""
    fat: str = ""
    s_byte: int = 0
    s_bit: int = 0
    rt_byte: int = 0
    rt_bit: int = 0
    rm_byte: int = 0
    rm_bit: int = 0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    cfg_habilitar: str = ""
    cfg_byteretornotermico: str = ""
    cfg_bitretornotermico: str = ""
    cfg_byteconfmarcha: str = ""
    cfg_bitconfmarcha: str = ""
    cfg_byteactivacion: str = ""
    cfg_bitactivacion: str = ""
    cfg_habrettermico: str = ""
    cfg_habretconfmarcha: str = ""
    cfg_grupoalarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispM_VF:
    """Display Motor con Variador de Frecuencia (VFD).

    Anade ``sa_byte`` y ``cfg_byteanalogica`` a los campos de ``DispM``.
    """

    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    tag: str = ""
    fat: str = ""
    s_byte: int = 0
    s_bit: int = 0
    rt_byte: int = 0
    rt_bit: int = 0
    rm_byte: int = 0
    rm_bit: int = 0
    gr_alarma: int = 0
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    cfg_habilitar: str = ""
    cfg_byteretornotermico: str = ""
    cfg_bitretornotermico: str = ""
    cfg_byteconfmarcha: str = ""
    cfg_bitconfmarcha: str = ""
    cfg_byteactivacion: str = ""
    cfg_bitactivacion: str = ""
    cfg_habrettermico: str = ""
    cfg_habretconfmarcha: str = ""
    cfg_grupoalarma: str = ""
    comentario_db: str = ""
    sa_byte: int = 0
    cfg_byteanalogica: str = ""


__all__ = ["Dispositivo", "DispED", "DispEA", "DispSA", "DispV", "DispM", "DispM_VF"]
