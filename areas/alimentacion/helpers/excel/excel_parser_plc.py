"""Parser de la ``Tabla_PLC`` del Excel corporativo (multi-PLC, sept-2026).

Lee la ``Tabla_PLC`` de la hoja ``CONFIG`` con la siguiente estructura::

    UID | PLC
    1   | PLC1
    2   | PLC2

Es la **lista canonica de PLCs disponibles** en el Excel. Las otras
tablas (Disp*, Procesos, Parametros, Alarmas, N_MAX) tienen una columna
``PLC`` cuyo valor se coteja contra esta lista (validacion fail-late,
preparada pero no activada en este PR).

Restriccion arquitectonica: este modulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.data.data_plc import DataPLC
from areas.alimentacion.helpers.excel._excel_helpers import (
    _safe_int,
    _safe_str,
    extract_list_object_rows,
)


logger = logging.getLogger(__name__)


class PLCListParser:
    """Parser de la ``Tabla_PLC`` (hoja ``CONFIG``).

    Mapea cada fila a un ``DataPLC``. Solo lee la columna ``PLC`` (la
    columna ``UID`` ya viene como entero del Excel).

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"CONFIG"``).
        * ``TABLE``: nombre de la ``ListObject`` (``"Tabla_PLC"``).

    Politica de descarte:
        * Filas con ``UID`` vacio o ``PLC`` vacio se descartan con WARNING.
        * ``uid=0`` se acepta como valor valido (no es filtrado).
    """

    SHEET = "CONFIG"
    TABLE = "Tabla_PLC"

    def extraer(self, wb: Workbook) -> list[DataPLC]:
        """Extrae todos los PLCs del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aqui).

        Returns:
            Lista de ``DataPLC``. Si la hoja o la tabla no existen,
            devuelve ``[]``.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DataPLC] = []
        for row in rows:
            # Politica legacy: dropna por UID y PLC.
            if _safe_str(row.get("UID")) == "":
                continue
            plc = _safe_str(row.get("PLC"))
            if not plc:
                logger.warning("Fila sin PLC en %s: descartada", self.TABLE)
                continue
            try:
                result.append(
                    DataPLC(
                        uid=_safe_int(row.get("UID")),
                        plc=plc,
                    )
                )
            except Exception as exc:  # defensivo: nunca romper la tabla
                logger.warning(
                    "Fila descartada en %s: %s",
                    self.TABLE,
                    exc,
                )
                continue
        logger.debug(
            f"Parser[{self.SHEET}/{self.TABLE}]: "
            f"{len(rows)} filas -> {len(result)} extraidas"
        )
        return result


__all__ = ["PLCListParser"]