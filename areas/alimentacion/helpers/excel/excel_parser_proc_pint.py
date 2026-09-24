"""Parser de parÃƒÆ’Ã‚¡metros enteros del Excel corporativo.

Extrae la ``ListObject`` ``Tabla_PInt`` de la hoja ``P_INT`` del
workbook del departamento de alimentaciÃƒÆ’Ã‚Â³n y la mapea a una lista
de ``DataParamIntPLC`` (DTO inmutable definido en
``areas.alimentacion.domain.models.excel_cache``).

Diferencias con el legacy TUI (``_legacy_reference/ZC_ALM_TOOLS``):
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del loader / endpoint /
      MCP tool. Esto evita abrir el workbook 4 veces (uno
      por parser de software) y soporta el patrón donde el
      ``ExcelLoader`` abre el workbook UNA vez y compone 11
      parsers.
    * Sin pandas: openpyxl directo. Coherente con el parser
      consolidado ``AlimentacionExcelParser`` del repo.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas invÃƒÆ’Ã‚¡lidas se descartan con ``logger.warning`` (no
      rompen la carga). ``extract_list_object_rows`` ya devuelve
      ``[]`` si la hoja o la tabla no existen.
    * Mismas claves literales del Excel que el legacy
      (``_legacy_reference/ZC_ALM_TOOLS/infrastructure/parsers/
      software/pint.py`` lÃƒÆ’Ã‚Â­neas 27-38): ``UID``, ``Numero``,
      ``Proceso``, ``Codigo``, ``Num.DB``, ``Producto``, ``Tipo``,
      ``Descripcion``, ``ComentarioDB``, ``Visibilidad``,
      ``Num.Lista``, ``Txt.Lista``.

Punto crítico: el campo ``num_lista`` **no** se mapea con ``_safe_int``
(que destruirÃƒÆ’Ã‚Â­a los marcadores semÃƒÆ’Ã‚¡nticos del operario cayendo a
``0``). Se usa ``_safe_num_lista``, que preserva ``"N/A"`` y
``"TODOS"`` literalmente. Esto es coherente con el shape del DTO (``num_lista: int | str``).

Diferencia entre ``DataParamIntPLC`` y ``DataParamRealPLC``:
aunque el shape (12 campos) es idÃƒÆ’©ntico, los dos DTOs son
**nominalmente distintos** en Python. El parser usa su propio DTO
(``DataParamIntPLC``) Ãƒ¢Ã¢â€šÂ¬Ã¢â‚¬Â no se reutiliza ``DataParamRealPLC``. Si en el
futuro se quiere aÃƒÆ’Ã‚Â±adir ``rango_min``/``rango_max`` solo a
``DataParamRealPLC`` (derivados de ``DispEA.RII``/``DispEA.RSI``), se
hace sin tocar ``DataParamIntPLC``.

RestricciÃƒÆ’Ã‚Â³n arquitectÃƒÆ’Ã‚Â³nica: este mÃƒÆ’Ã‚Â³dulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.data.data_parametros_int import DataParamIntPLC
from areas.alimentacion.helpers.excel._excel_helpers import (
    _safe_int,
    _safe_num_lista,
    _safe_str,
    extract_list_object_rows,
)


logger = logging.getLogger(__name__)


class PIntParser:
    """Parser de la ``Tabla_PInt`` (hoja ``P_INT``).

    Mapea cada fila de la ``ListObject`` a un ``DataParamIntPLC``. Las
    claves de columna son **literales** (con mayÃƒÆ’Ã‚ºsculas, puntos y
    espacios) Ãƒ¢Ã¢â€šÂ¬Ã¢â‚¬Â exactamente como aparecen en el Excel del
    corporativo y como las consumÃƒÆ’Ã‚Â­a el legacy.

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"P_INT"``).
        * ``TABLE``: nombre de la ``ListObject`` (``"Tabla_PInt"``).
    """

    SHEET = "P_INT"
    TABLE = "Tabla_PInt"

    def extraer(self, wb: Workbook) -> list[DataParamIntPLC]:
        """Extrae todos los parÃƒÆ’Ã‚¡metros enteros del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aquÃƒÆ’Ã‚Â­).

        Returns:
            Lista de ``DataParamIntPLC``. Si la hoja o la tabla no
            existen, devuelve ``[]``. Las filas que fallen al
            construir el DTO se descartan con WARNING.

        PolÃƒÆ’Ã‚Â­tica de descarte (consistente con ``ProcesosParser`` y
        ``PRealParser``, legacy dropna por UID):
            * Filas con ``UID`` vacÃƒÆ’Ã‚Â­o (``None`` / ``""`` / whitespace
              / ``"nan"`` / ``"None"`` / ``"null"``) se descartan
              silenciosamente. Esto evita parÃƒÆ’Ã‚¡metros fantasma sin
              UID en el cache. Es el equivalente del
              ``pandas.dropna(subset=["UID"])`` del legacy TUI.
            * Filas con ``UID`` no vacÃƒÆ’Ã‚Â­o se conservan aunque el
              resto de campos estÃƒÆ’© vacÃƒÆ’Ã‚Â­o: el DTO tiene defaults
              tolerantes (``str = ""``, ``int = 0``,
              ``num_lista = 0``).
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DataParamIntPLC] = []
        for row in rows:
            # PolÃƒÆ’Ã‚Â­tica legacy: dropna por UID. ``_safe_str`` ya
            # mapea ``None`` / ``""`` / ``"nan"`` / ``"None"`` /
            # ``"null"`` a ``""``.
            if _safe_str(row.get("UID")) == "":
                continue
            try:
                result.append(
                    DataParamIntPLC(
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
        logger.debug(
            f"Parser[{self.SHEET}/{self.TABLE}]: "
            f"{len(rows)} filas -> {len(result)} extraidas"
        )
        return result


__all__ = ["PIntParser"]
