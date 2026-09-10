"""areas.alimentacion.data.data_ParametrosReal — Data Block de ParamRealPLC.

Fase 3, paso 3.2.6.  Migrado de ``areas/alimentacion/domain/models/excel_cache.py``.

Un **parametro real** es una variable ``REAL`` (32 bits, IEEE 754) que
el PLC expone al HMI y que el operario puede ajustar en runtime
(tipicamente un setpoint, un limite o un factor de escalado).  Se
agrupa en un DB por proceso: ``DB{num_db}_{codigo}_PREAL`` (uno por
proceso, contiene varios ``ParamRealPLC`` consecutivos).

Shape identico a ``DataParamIntPLC`` (12 campos, mismos nombres, mismos
defaults), pero **tipo distinto en Python** (R4 del plan): ver
``data_ParametrosInt.py`` para la justificacion.

El legacy sigue coexistiendo (DA-006) hasta Fase 4 (4.0.2).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataParamRealPLC:
    """DTO de un parametro real del PLC.

    Campos (12):
      - ``uid``: identificador unico **str** (``'PR_1_001'``).
      - ``numero``: nº logico del parametro (``"001"``, ``"002"``).
      - ``proceso``: nombre del proceso al que pertenece.
      - ``codigo``: codigo corto del proceso.
      - ``num_db``: nº del DB donde se mapea este parametro.
      - ``producto``: nombre del producto / linea.
      - ``tipo``: clasificacion funcional (``"Setpoint"``, ``"Limite"``).
      - ``descripcion``: descripcion legible.
      - ``comentario_db``: comentario del DB.
      - ``visibilidad``: ``"Si"`` / ``"No"``.
      - ``num_lista``: ``int | str`` (marcadores ``"N/A"`` / ``"TODOS"``).
      - ``txt_lista``: texto libre asociado.
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


__all__ = ["DataParamRealPLC"]
