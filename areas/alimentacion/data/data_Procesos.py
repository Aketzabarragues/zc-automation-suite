"""Data Block de DataProcesoPLC.

Un **proceso** es la unidad organizativa del Excel: agrupa un conjunto
de parámetros reales, parámetros enteros y alarmas que se generan
juntos en el PLC. Este DTO contiene exclusivamente los 8 campos del
Excel corporativo. Los nombres de DB y otros valores derivados se
computan en el consumidor (frontend para mostrar, backend para generar
XML).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataProcesoPLC:
    """DTO de un proceso del PLC (hoja ``CONFIGURACION`` -> ``Tabla_Procesos``).

    Campos (todos enteros/str con defaults tolerantes a celdas vacias):
      - ``uid``: identificador entero unico (1, 2, 3, ...).
      - ``nombre``: nombre legible del proceso.
      - ``codigo``: codigo corto usado en el nombre de los DBs.
      - ``preal`` / ``index_preal``: n de parametros reales y su
        offset dentro del DB PREAL.
      - ``pint`` / ``index_pint``: analogo para parametros enteros.
      - ``alarmas``: n de alarmas del proceso.
      - ``alm_hmi``: n de alarmas representadas en HMI. Septiembre 2026:
        nueva columna del Excel corporativo (``Alarmas_Hmi``). Su
        PlcUserConstant en TIA es ``<uid>_N_MAX_ALM_HMI`` y se aplica
        via el mismo flujo que ``preal`` / ``pint`` / ``alm``.
    """

    uid: int
    nombre: str
    codigo: str
    preal: int = 0
    index_preal: int = 0
    pint: int = 0
    index_pint: int = 0
    alarmas: int = 0
    alm_hmi: int = 0


__all__ = ["DataProcesoPLC"]
