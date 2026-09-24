"""Data Block de DataParamIntPLC.

Un **parámetro entero** es una variable ``DINT``/``INT`` (32/16 bits) que
el PLC expone al HMI y que el operario puede ajustar en runtime
(típicamente un contador, un índice o un factor de escalado discreto).
Se agrupa en un DB por proceso: ``DB{num_db}_{codigo}_PINT`` (uno por
proceso, contiene varios ``DataParamIntPLC`` consecutivos).

Shape idéntico a ``DataParamRealPLC`` (12 campos, mismos nombres, mismos
defaults), pero **tipo distinto en Python**: ``DataParamIntPLC`` y
``DataParamRealPLC`` son nominalmente dos dataclasses separadas.
``isinstance(DataParamIntPLC(...), DataParamRealPLC) == False``.

Razon de la separacion (R4): si en el futuro se quiere anadir
``rango_min``/``rango_max`` solo a ``DataParamRealPLC`` (derivados de
``DispEA.RII``/``DispEA.RSI``), se hace sin tocar ``DataParamIntPLC``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataParamIntPLC:
    """DTO de un parametro entero del PLC.

    Campos:
      - ``uid``: identificador unico **str** (``'PI_1_001'``).
      - ``numero``: nÃ‚º logico del parametro dentro del proceso
        (``"001"``, ``"002"``, ...).
      - ``proceso``: nombre del proceso al que pertenece.
      - ``codigo``: codigo corto del proceso.
      - ``num_db``: nÃ‚º del DB donde se mapea este parametro.
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
