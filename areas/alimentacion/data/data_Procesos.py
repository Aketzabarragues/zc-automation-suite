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
      - ``preal`` / ``index_preal``: nÃƒÆ’Ã†’Ãƒ¢Ã¢â€šÂ¬Ã…¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚º de parametros reales y su
        offset dentro del DB PREAL.
      - ``pint`` / ``index_pint``: analogo para parametros enteros.
      - ``alarmas``: nÃƒÆ’Ã†’Ãƒ¢Ã¢â€šÂ¬Ã…¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚º de alarmas del proceso.
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
