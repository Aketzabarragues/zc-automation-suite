"""Data Block de DataParamRealPLC.

Un **parámetro real** es una variable ``REAL`` (32 bits, IEEE 754) que
el PLC expone al HMI y que el operario puede ajustar en runtime
(típicamente un setpoint, un límite o un factor de escalado). Se agrupa
en un DB por proceso: ``DB{num_db}_{codigo}_PREAL`` (uno por proceso,
contiene varios ``DataParamRealPLC`` consecutivos).

Shape idéntico a ``DataParamIntPLC`` (12 campos, mismos nombres, mismos
defaults), pero **tipo distinto en Python**: ver ``data_ParametrosInt.py``
para la justificación.
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
