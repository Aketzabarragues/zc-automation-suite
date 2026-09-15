"""Parser de parÃ¡metros reales del Excel corporativo.

Extrae la ``ListObject`` ``Tabla_PReal`` de la hoja ``P_REAL`` del
workbook del departamento de alimentaciÃ³n y la mapea a una lista
de ``ParamRealPLC`` (DTO inmutable definido en
``areas.alimentacion.domain.models.excel_cache``).

Diferencias con el legacy TUI (``_legacy_reference/ZC_ALM_TOOLS``):
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del loader / endpoint /
      MCP tool (Fase 5). Esto evita abrir el workbook 4 veces (uno
      por parser de software) y soporta el patrÃ³n de Fase 5 donde
      el ``ExcelLoader`` abre el workbook UNA vez y compone 11
      parsers.
    * Sin pandas: openpyxl directo. Coherente con el parser
      consolidado ``AlimentacionExcelParser`` del repo.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas invÃ¡lidas se descartan con ``logger.warning`` (no
      rompen la carga). ``extract_list_object_rows`` ya devuelve
      ``[]`` si la hoja o la tabla no existen.
    * Mismas claves literales del Excel que el legacy
      (``_legacy_reference/ZC_ALM_TOOLS/infrastructure/parsers/
      software/preal.py`` lÃ­neas 25-38): ``UID``, ``Numero``,
      ``Proceso``, ``Codigo``, ``Num.DB``, ``Producto``, ``Tipo``,
      ``Descripcion``, ``ComentarioDB``, ``Visibilidad``,
      ``Num.Lista``, ``Txt.Lista``.

Punto crÃ­tico de Fase 2 (R4 del plan): el campo ``num_lista``
**no** se mapea con ``_safe_int`` (que destruirÃ­a los marcadores
semÃ¡nticos del operario cayendo a ``0``). Se usa
``_safe_num_lista``, que preserva ``"N/A"`` y ``"TODOS"``
literalmente. Esto es coherente con la regla R4 del operario y
con el shape del DTO (``num_lista: int | str``).

RestricciÃ³n arquitectÃ³nica: este mÃ³dulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.domain.models.excel_cache import ParamRealPLC
from areas.alimentacion.helpers.parsers._xlsx_helpers import (
    _safe_int,
    _safe_num_lista,
    _safe_str,
    extract_list_object_rows,
)


logger = logging.getLogger(__name__)


class PRealParser:
    """Parser de la ``Tabla_PReal`` (hoja ``P_REAL``).

    Mapea cada fila de la ``ListObject`` a un ``ParamRealPLC``. Las
    claves de columna son **literales** (con mayÃºsculas, puntos y
    espacios) â€” exactamente como aparecen en el Excel del
    corporativo y como las consumÃ­a el legacy.

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"P_REAL"``).
        * ``TABLE``: nombre de la ``ListObject`` (``"Tabla_PReal"``).
    """

    SHEET = "P_REAL"
    TABLE = "Tabla_PReal"

    def extraer(self, wb: Workbook) -> list[ParamRealPLC]:
        """Extrae todos los parÃ¡metros reales del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aquÃ­).

        Returns:
            Lista de ``ParamRealPLC``. Si la hoja o la tabla no
            existen (R1 del plan), devuelve ``[]``. Las filas que
            fallen al construir el DTO se descartan con WARNING.

        PolÃ­tica de descarte (consistente con ``ProcesosParser``,
        legacy dropna por UID):
            * Filas con ``UID`` vacÃ­o (``None`` / ``""`` / whitespace
              / ``"nan"`` / ``"None"`` / ``"null"``) se descartan
              silenciosamente. Esto evita parÃ¡metros fantasma sin
              UID en el cache. Es el equivalente del
              ``pandas.dropna(subset=["UID"])`` del legacy TUI.
            * Filas con ``UID`` no vacÃ­o se conservan aunque el
              resto de campos estÃ© vacÃ­o: el DTO tiene defaults
              tolerantes (``str = ""``, ``int = 0``,
              ``num_lista = 0``).
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[ParamRealPLC] = []
        for row in rows:
            # PolÃ­tica legacy: dropna por UID. ``_safe_str`` ya
            # mapea ``None`` / ``""`` / ``"nan"`` / ``"None"`` /
            # ``"null"`` a ``""``.
            if _safe_str(row.get("UID")) == "":
                continue
            try:
                result.append(
                    ParamRealPLC(
                        uid=_safe_str(row.get("UID")),
                        numero=_safe_str(row.get("Numero")),
                        proceso=_safe_str(row.get("Proceso")),
                        codigo=_safe_str(row.get("Codigo")),
                        num_db=_safe_int(row.get("Num.DB")),
                        producto=_safe_str(row.get("Producto")),
                        tipo=_safe_str(row.get("Tipo")),
                        descripcion=_safe_str(row.get("Descripcion")),
                        comentario_db=_safe_str(row.get("ComentarioDB")),
                        visibilidad=_safe_str(row.get("Visibilidad")),
                        num_lista=_safe_num_lista(row.get("Num.Lista")),
                        txt_lista=_safe_str(row.get("Txt.Lista")),
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


__all__ = ["PRealParser"]
