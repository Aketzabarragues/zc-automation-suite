"""Modelos de dispositivos del subdominio alimentación.

Define el Protocol ``Dispositivo`` (contrato base con 5 atributos
obligatorios) y 6+1 dataclasses ``frozen=True`` que lo satisfacen
estructuralmente (duck typing):

  * ``DispED``   - Entradas Digitales
  * ``DispEA``   - Entradas Analógicas
  * ``DispSA``   - Salidas Analógicas (estructura idéntica a DispEA)
  * ``DispV``    - Variables internas
  * ``DispM``    - Motores (digital)
  * ``DispM_VF`` - Motores con Variador de Frecuencia
  * ``DimensionesDispositivos`` - Cantidades numéricas por tipo

Restricciones arquitectónicas:
- Prohibido importar ``siemens_tia_scripting``.
- Prohibido el uso de ``Any`` en los atributos declarados.
- Prohibido depender de openpyxl u otras librerías de infraestructura.
- Todos los campos ``cfg_*`` son ``str`` con default ``""``.
- Los modificadores offline (``TagTableModifier`` y ``SDModifier``)
  operan sobre estos objetos accediendo directamente a sus atributos
  (``plc_tag``, ``uid``, etc.) — no a través de ``dict.get``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


# ── Protocol base ────────────────────────────────────────────────────────


@runtime_checkable
class Dispositivo(Protocol):
    """Contrato común a todo dispositivo instanciable del subdominio.

    Atributos obligatorios (mínimo denominador común):
      - ``numero``: índice secuencial dentro de su hoja Excel.
      - ``plc_tag``: nombre simbólico del PlcTag en TIA Portal.
      - ``plc_comentario``: comentario del PlcTag en TIA Portal.
      - ``descripcion``: descripción legible para el operario.
      - ``uid``: clave de identidad inmutable a través de renombres.

    El modificador offline (``TagTableModifier.remove_tags``) usa ``uid``
    para borrar PlcTags preservando referencias cruzadas del PLC.
    """

    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str


# ── Dataclasses frozen ──────────────────────────────────────────────────


@dataclass(frozen=True)
class DispED:
    """Display Entradas Digitales.

    Representa una instancia discreta de entradas digitales (bits)
    que se inyecta como PlcTag en el PLC.
    """

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos específicos ────────────────────────────────────────
    tag: int = 0
    fat: int = 0
    e_byte: int = 0
    e_bit: int = 0
    gr_alarma: str = ""
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    # ── Campos SCL (línea completa ``cfg_* := ...;``) ───────────────
    cfg_habilitar: str = ""
    cfg_byte_entrada: str = ""
    cfg_bit_entrada: str = ""
    cfg_grupo_alarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispEA:
    """Display Entradas Analógicas.

    Representa una instancia de entradas analógicas (palabras)
    que se inyecta como PlcTag en el PLC.
    """

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos específicos ────────────────────────────────────────
    tag: int = 0
    fat: int = 0
    e_byte: int = 0
    unidades: str = ""
    rii: float = 0.0  # rango inferior de escalado
    rsi: float = 0.0  # rango superior de escalado
    gr_alarma: str = ""
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    # ── Campos SCL ──────────────────────────────────────────────────
    cfg_habilitar: str = ""
    cfg_byte_entrada: str = ""
    cfg_escaladomin: str = ""
    cfg_escaladomax: str = ""
    cfg_grupo_alarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispSA:
    """Display Salidas Analógicas.

    Estructura IDÉNTICA a ``DispEA`` (mismos campos y semántica; solo
    cambia el sentido de la variable: salida vs entrada).
    """

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos específicos (idénticos a DispEA) ──────────────────
    tag: int = 0
    fat: int = 0
    e_byte: int = 0
    unidades: str = ""
    rii: float = 0.0
    rsi: float = 0.0
    gr_alarma: str = ""
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    # ── Campos SCL ──────────────────────────────────────────────────
    cfg_habilitar: str = ""
    cfg_byte_entrada: str = ""
    cfg_escaladomin: str = ""
    cfg_escaladomax: str = ""
    cfg_grupo_alarma: str = ""
    comentario_db: str = ""


@dataclass(frozen=True)
class DispV:
    """Display Variables internas (sin E/S física asociada)."""

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos específicos ────────────────────────────────────────
    tag: int = 0
    fat: int = 0
    s_byte: int = 0
    s_bit: int = 0
    rr_byte: int = 0
    rr_bit: int = 0
    rt_byte: int = 0
    rt_bit: int = 0
    gr_alarma: str = ""
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    # ── Campos SCL ──────────────────────────────────────────────────
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

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos específicos ────────────────────────────────────────
    tag: int = 0
    fat: int = 0
    s_byte: int = 0
    s_bit: int = 0
    rt_byte: int = 0
    rt_bit: int = 0
    rm_byte: int = 0
    rm_bit: int = 0
    gr_alarma: str = ""
    cuadro: str = ""
    observaciones: str = ""
    plc_tipo: str = ""
    plc_index: int = 0
    hmi_index: int = 0
    hmi_texto: str = ""
    # ── Campos SCL ──────────────────────────────────────────────────
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

    Hereda todos los campos de ``DispM`` y añade ``sa_byte`` y
    ``cfg_byteanalogica`` para el control analógico del variador.
    """

    # ── Protocol Dispositivo ─────────────────────────────────────────
    numero: int
    plc_tag: str
    plc_comentario: str
    descripcion: str
    uid: str
    # ── Atributos heredados de DispM ───────────────────────────────
    tag: int = 0
    fat: int = 0
    s_byte: int = 0
    s_bit: int = 0
    rt_byte: int = 0
    rt_bit: int = 0
    rm_byte: int = 0
    rm_bit: int = 0
    gr_alarma: str = ""
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
    # ── Campos exclusivos VFD ──────────────────────────────────────
    sa_byte: int = 0
    cfg_byteanalogica: str = ""


# ── Dimensiones ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DimensionesDispositivos:
    """Cantidades numéricas de dispositivos por tipo.

    Extraído del Excel (named ranges ``num_disp_*``) o calculado
    a partir del conteo de las listas de ``AppState``.
    """

    num_disp_ed: int = 0
    num_disp_ea: int = 0
    num_disp_sa: int = 0
    num_disp_v: int = 0
    num_disp_m: int = 0
    num_disp_m_vf: int = 0


__all__ = [
    # Protocol y dimensiones
    "Dispositivo",
    "DimensionesDispositivos",
    # Dataclasses de dispositivos
    "DispED",
    "DispEA",
    "DispSA",
    "DispV",
    "DispM",
    "DispM_VF",
]
