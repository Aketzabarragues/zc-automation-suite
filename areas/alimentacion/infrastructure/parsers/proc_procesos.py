"""Parser de procesos del Excel corporativo.

Extrae la ``ListObject`` ``Tabla_Procesos`` de la hoja ``CONFIGURACION``
del workbook del departamento de alimentación y la mapea a una lista de
``ProcesoPLC`` (DTO inmutable definido en
``areas.alimentacion.domain.models.excel_cache``).

Diferencias con el legacy TUI (``_legacy_reference/ZC_ALM_TOOLS``):
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del loader / endpoint /
      MCP tool (Fase 5). Esto evita abrir el workbook 4 veces (uno
      por parser de software) y soporta el patrón de Fase 5 donde el
      ``ExcelLoader`` abre el workbook UNA vez y compone 11 parsers.
    * Sin pandas: openpyxl directo. Coherente con el parser
      consolidado ``AlimentacionExcelParser`` del repo.
    * Defensivo: cada fila se envuelve en ``try/except`` y las filas
      inválidas se descartan con ``logger.warning`` (no rompen la
      carga). ``extract_list_object_rows`` ya devuelve ``[]`` si la
      hoja o la tabla no existen.
    * Mismas claves literales del Excel que el legacy:
      ``UID``, ``Nombre``, ``Codigo``, ``PReal``, ``Index_Preal``,
      ``PInt``, ``Index_Pint``, ``Alarmas``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.domain.models.excel_cache import ProcesoPLC
from areas.alimentacion.infrastructure.parsers._xlsx_helpers import (
    extract_list_object_rows,
    _safe_int,
    _safe_str,
)


logger = logging.getLogger(__name__)


class ProcesosParser:
    """Parser de la ``Tabla_Procesos`` (hoja ``CONFIGURACION``).

    Mapea cada fila de la ``ListObject`` a un ``ProcesoPLC``. Las
    claves de columna son **literales** (con mayúsculas y, en su
    caso, guion bajo) — exactamente como aparecen en el Excel del
    corporativo y como las consumía el legacy.

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"CONFIGURACION"``).
        * ``TABLE``: nombre de la ``ListObject`` (``"Tabla_Procesos"``).
    """

    SHEET = "CONFIGURACION"
    TABLE = "Tabla_Procesos"

    def extraer(self, wb: Workbook) -> list[ProcesoPLC]:
        """Extrae todos los procesos del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aquí).

        Returns:
            Lista de ``ProcesoPLC``. Si la hoja o la tabla no existen
            (R1 del plan), devuelve ``[]``. Las filas que fallen al
            construir el DTO se descartan con WARNING.

        Política de descarte (legacy, plan §5.7 test 5):
            * Filas con ``UID`` vacío (``None`` / ``""`` / whitespace /
              ``"nan"`` / ``"None"`` / ``"null"``) se descartan
              silenciosamente. Esto evita procesos fantasma con
              ``uid=0`` en el cache. Es el equivalente del
              ``pandas.dropna(subset=["UID"])`` del legacy TUI.
            * Filas con ``UID=0`` legítimo (entero o ``"0"``) se
              conservan: ``uid=0`` es un valor válido en el Excel.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[ProcesoPLC] = []
        for row in rows:
            # Política legacy: dropna por UID. ``_safe_str`` ya mapea
            # ``None`` / ``""`` / ``"nan"`` / ``"None"`` / ``"null"`` a
            # ``""``. Un UID ``"0"`` o ``0`` pasa el filtro (es válido).
            if _safe_str(row.get("UID")) == "":
                continue
            try:
                result.append(
                    ProcesoPLC(
                        uid=_safe_int(row.get("UID")),
                        nombre=_safe_str(row.get("Nombre")),
                        codigo=_safe_str(row.get("Codigo")),
                        preal=_safe_int(row.get("PReal")),
                        index_preal=_safe_int(row.get("Index_Preal")),
                        pint=_safe_int(row.get("PInt")),
                        index_pint=_safe_int(row.get("Index_Pint")),
                        alarmas=_safe_int(row.get("Alarmas")),
                    )
                )
            except Exception as exc:  # defensivo: nunca romper la tabla
                logger.warning(
                    "Fila descartada en %s: %s",
                    self.TABLE,
                    exc,
                )
                continue
        return result


__all__ = ["ProcesosParser"]
