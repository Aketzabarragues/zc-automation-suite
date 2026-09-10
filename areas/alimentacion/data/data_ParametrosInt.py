"""areas.alimentacion.data.data_ParametrosInt — Data Block de ParamIntPLC.

Fase 3, paso 3.2.5.  Migrado de ``areas/alimentacion/domain/models/excel_cache.py``.

Un **parametro entero** es una variable ``DINT``/``INT`` (32/16 bits) que
el PLC expone al HMI y que el operario puede ajustar en runtime
(tipicamente un contador, un indice o un factor de escalado discreto).
Se agrupa en un DB por proceso: ``DB{num_db}_{codigo}_PINT`` (uno por
proceso, contiene varios ``ParamIntPLC`` consecutivos).

Shape identico a ``DataParamRealPLC`` (12 campos, mismos nombres, mismos
defaults), pero **tipo distinto en Python** (R4 del plan, resuelto por
el operario el 2026-09-01): ``DataParamIntPLC`` y ``DataParamRealPLC``
son nominalmente dos dataclasses separadas. ``isinstance(ParamIntPLC(...), ParamRealPLC) == False``.

Razon de la separacion (R4): si en el futuro se quiere anadir
``rango_min``/``rango_max`` solo a ``DataParamRealPLC`` (derivados de
``DispEA.RII``/``DispEA.RSI``), se hace sin tocar ``DataParamIntPLC``.

El legacy sigue coexistiendo (DA-006) hasta Fase 4 (4.0.2).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataParamIntPLC:
    """DTO de un parametro entero del PLC.

    Campos:
      - ``uid``: identificador unico **str** (``'PI_1_001'``).
      - ``numero``: nº logico del parametro dentro del proceso
        (``"001"``, ``"002"``, ...).
      - ``proceso``: nombre del proceso al que pertenece.
      - ``codigo``: codigo corto del proceso.
      - ``num_db``: nº del DB donde se mapea este parametro.
      - ``producto``: nombre del producto / linea.
      - ``tipo``: clasificacion funcional (``"Contador"``, ``"Indice"``).
      - ``descripcion``: descripcion legible para el operario.
      - ``comentario_db``: comentario del DB (no del tag).
      - ``visibilidad``: flag ``"Si"`` / ``"No"``.
      - ``num_lista``: indice de la lista HMI. **CRITICO**: ``int | str``
        (no solo ``int``). Valores como ``"N/A"`` o ``"TODOS"`` son
        marcadores semanticos que el operario usa para listas de
        seleccion.
      - ``txt_lista``: texto libre asociado a ``num_lista``.
    """

    uid: str
    numero: str
    proceso: str
    codigo: str
    num_db: int
    producto: str
    tipo: str
    descripcion: str
    comentario_db: str
    visibilidad: str
    num_lista: int | str
    txt_lista: str


__all__ = ["DataParamIntPLC"]
