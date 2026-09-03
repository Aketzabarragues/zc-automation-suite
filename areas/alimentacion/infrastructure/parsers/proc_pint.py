"""Parser de parámetros enteros del Excel corporativo.

Extrae la ``ListObject`` ``Tabla_PInt`` de la hoja ``P_INT`` del
workbook del departamento de alimentación y la mapea a una lista
de ``ParamIntPLC`` (DTO inmutable definido en
``areas.alimentacion.domain.models.excel_cache``).

Diferencias con el legacy TUI (``_legacy_reference/ZC_ALM_TOOLS``):
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del loader / endpoint /
      MCP tool (Fase 5). Esto evita abrir el workbook 4 veces (uno
      por parser de software) y soporta el patrón de Fase 5 donde
      el ``ExcelLoader`` abre el workbook UNA vez y compone 11
      parsers.
    * Sin pandas: openpyxl directo. Coherente con el parser
      consolidado ``AlimentacionExcelParser`` del repo.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas inválidas se descartan con ``logger.warning`` (no
      rompen la carga). ``extract_list_object_rows`` ya devuelve
      ``[]`` si la hoja o la tabla no existen.
    * Mismas claves literales del Excel que el legacy
      (``_legacy_reference/ZC_ALM_TOOLS/infrastructure/parsers/
      software/pint.py`` líneas 27-38): ``UID``, ``Numero``,
      ``Proceso``, ``Codigo``, ``Num.DB``, ``Producto``, ``Tipo``,
      ``Descripcion``, ``ComentarioDB``, ``Visibilidad``,
      ``Num.Lista``, ``Txt.Lista``.

Punto crítico de Fase 3 (heredado de R4 del plan, ya tratado en
Fase 2): el campo ``num_lista`` **no** se mapea con ``_safe_int``
(que destruiría los marcadores semánticos del operario cayendo a
``0``). Se usa ``_safe_num_lista``, que preserva ``"N/A"`` y
``"TODOS"`` literalmente. Esto es coherente con la regla R4 del
operario y con el shape del DTO (``num_lista: int | str``).

Diferencia entre ``ParamIntPLC`` y ``ParamRealPLC`` (R4 del plan):
aunque el shape (12 campos) es idéntico, los dos DTOs son
**nominalmente distintos** en Python. El parser usa su propio DTO
(``ParamIntPLC``) — no se reutiliza ``ParamRealPLC``. Si en el
futuro se quiere añadir ``rango_min``/``rango_max`` solo a
``ParamRealPLC`` (derivados de ``DispEA.RII``/``DispEA.RSI``), se
hace sin tocar ``ParamIntPLC``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.domain.models.excel_cache import ParamIntPLC
from areas.alimentacion.infrastructure.parsers._xlsx_helpers import (
    _safe_int,
    _safe_num_lista,
    _safe_str,
    extract_list_object_rows,
)


logger = logging.getLogger(__name__)


class PIntParser:
    """Parser de la ``Tabla_PInt`` (hoja ``P_INT``).

    Mapea cada fila de la ``ListObject`` a un ``ParamIntPLC``. Las
    claves de columna son **literales** (con mayúsculas, puntos y
    espacios) — exactamente como aparecen en el Excel del
    corporativo y como las consumía el legacy.

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"P_INT"``).
        * ``TABLE``: nombre de la ``ListObject`` (``"Tabla_PInt"``).
    """

    SHEET = "P_INT"
    TABLE = "Tabla_PInt"

    def extraer(self, wb: Workbook) -> list[ParamIntPLC]:
        """Extrae todos los parámetros enteros del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aquí).

        Returns:
            Lista de ``ParamIntPLC``. Si la hoja o la tabla no
            existen (R1 del plan), devuelve ``[]``. Las filas que
            fallen al construir el DTO se descartan con WARNING.

        Política de descarte (consistente con ``ProcesosParser`` y
        ``PRealParser``, legacy dropna por UID):
            * Filas con ``UID`` vacío (``None`` / ``""`` / whitespace
              / ``"nan"`` / ``"None"`` / ``"null"``) se descartan
              silenciosamente. Esto evita parámetros fantasma sin
              UID en el cache. Es el equivalente del
              ``pandas.dropna(subset=["UID"])`` del legacy TUI.
            * Filas con ``UID`` no vacío se conservan aunque el
              resto de campos esté vacío: el DTO tiene defaults
              tolerantes (``str = ""``, ``int = 0``,
              ``num_lista = 0``).
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[ParamIntPLC] = []
        for row in rows:
            # Política legacy: dropna por UID. ``_safe_str`` ya
            # mapea ``None`` / ``""`` / ``"nan"`` / ``"None"`` /
            # ``"null"`` a ``""``.
            if _safe_str(row.get("UID")) == "":
                continue
            try:
                result.append(
                    ParamIntPLC(
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


__all__ = ["PIntParser"]
