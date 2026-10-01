"""Data Block de DataPLC.

Un **PLC** del Excel es la unidad logica de la ``Tabla_PLC`` (hoja
``CONFIG``): un ``uid`` (entero unico) y un ``plc`` (nombre que debe
matchear con el PLC en TIA Portal, igual que el resto de DTOs multi-PLC).

Esta tabla es la **lista canonica de PLCs disponibles** en el Excel.
Las otras tablas (Disp*, Procesos, Parametros, Alarmas, N_MAX) tienen
una columna ``PLC`` cuyo valor debe estar en esta tabla (validacion
fail-late, sept-2026).

Restricciones del DTO:
  - ``uid`` entero unico por PLC en el Excel.
  - ``plc`` string stripped (sin NBSP), case-sensitive en TIA (D11).
  - Default tolerante a celdas vacias.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataPLC:
    """DTO de un PLC de la ``Tabla_PLC`` (hoja ``CONFIG``).

    Atributos:
      - ``uid``: identificador entero unico (1, 2, 3, ...).
      - ``plc``: nombre del PLC (strict match con TIA Portal).

    Convenciones:
      - ``frozen=True``: inmutable.
      - Sin I/O, sin imports de ``siemens_tia_scripting`` u openpyxl.
    """

    uid: int
    plc: str = ""

    def __post_init__(self) -> None:
        # Sanity check: el nombre no puede ser None. El dataclass frozen
        # no permite reasignar, pero podemos validar en construccion.
        if self.plc is None:
            raise ValueError("DataPLC.plc no puede ser None")


__all__ = ["DataPLC"]