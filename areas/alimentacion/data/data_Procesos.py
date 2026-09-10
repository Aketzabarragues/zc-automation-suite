"""areas.alimentacion.data.data_Procesos — Data Block de ProcesoPLC.

Fase 3, paso 3.2.4.  Migrado de ``areas/alimentacion/domain/models/excel_cache.py``
(que contiene el DTO raiz ``ExcelCache`` mas los DTOs hoja: ``ProcesoPLC``,
``ParamRealPLC``, ``ParamIntPLC``, ``AlarmaPLC``, 6 Disp*, etc.).

Un **proceso** es la unidad organizativa del Excel: agrupa un conjunto
de parametros reales, parametros enteros y alarmas que se generan
juntos en el PLC.  Este DTO contiene exclusivamente los 8 campos del
Excel corporativo.  Los nombres de DB y otros valores derivados se
computan en el consumidor (frontend para mostrar, backend futuro para
generar XML).

El legacy sigue coexistiendo (DA-006) hasta Fase 4 (4.0.2).
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
      - ``preal`` / ``index_preal``: nº de parametros reales y su
        offset dentro del DB PREAL.
      - ``pint`` / ``index_pint``: analogo para parametros enteros.
      - ``alarmas``: nº de alarmas del proceso.
    """

    uid: int
    nombre: str
    codigo: str
    preal: int = 0
    index_preal: int = 0
    pint: int = 0
    index_pint: int = 0
    alarmas: int = 0


__all__ = ["DataProcesoPLC"]
