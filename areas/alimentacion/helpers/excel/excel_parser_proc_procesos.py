"""Parser de procesos del Excel corporativo.

Extrae la ``ListObject`` ``Tabla_Procesos`` de la hoja ``CONFIG``
del workbook del departamento de alimentación y la mapea a una lista de
``DataProcesoPLC`` (DTO inmutable definido en
``areas.alimentacion.data.data_procesos``).

Diferencias con la herramienta TUI anterior:
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del loader / endpoint.
      Esto evita abrir el workbook 4 veces (uno por parser de
      software) y soporta el patrón donde el ``ExcelLoader`` abre
      el workbook UNA vez y compone 11 parsers.
    * Sin pandas: openpyxl directo. Coherente con el resto de
      los parsers del area.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas inválidas se descartan con ``logger.warning`` (no
      rompen la carga). ``extract_list_object_rows`` ya devuelve
      ``[]`` si la hoja o la tabla no existen.
    * Mismas claves literales del Excel que usaba la herramienta
      TUI anterior: ``UID``, ``Nombre``, ``Codigo``, ``PReal``,
      ``Index_Preal``, ``PInt``, ``Index_Pint``, ``Alarmas``,
      ``Alarmas_Hmi``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.data.data_procesos import DataProcesoPLC
from areas.alimentacion.helpers.excel._excel_helpers import (
    extract_list_object_rows,
    _safe_int,
    _safe_str,
)


logger = logging.getLogger(__name__)


class ProcesosParser:
    """Parser de la ``Tabla_Procesos`` (hoja ``CONFIG``).

    Mapea cada fila de la ``ListObject`` a un ``DataProcesoPLC``. Las
    claves de columna son **literales** (con mayúsculas y, en su
    caso, guion bajo) Ã¢â‚¬” exactamente como aparecen en el Excel del
    corporativo y como las consumia la herramienta TUI anterior.

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"CONFIG"``).
        * ``TABLE``: nombre de la ``ListObject`` (``"Tabla_Procesos"``).
    """

    SHEET = "CONFIG"
    TABLE = "Tabla_Procesos"

    def extraer(self, wb: Workbook) -> list[DataProcesoPLC]:
        """Extrae todos los procesos del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aquí).

        Returns:
            Lista de ``DataProcesoPLC``. Si la hoja o la tabla no
            existen, devuelve ``[]``. Las filas que fallen al
            construir el DTO se descartan con WARNING.

        Politica de descarte (dropna por UID):
            * Filas con ``UID`` vacío (``None`` / ``""`` / whitespace /
              ``"nan"`` / ``"None"`` / ``"null"``) se descartan
              silenciosamente. Esto evita procesos fantasma con
              ``uid=0`` en el cache. Es el equivalente del
              ``pandas.dropna(subset=["UID"])`` de la herramienta TUI anterior.
            * Filas con ``UID=0`` legítimo (entero o ``"0"``) se
              conservan: ``uid=0`` es un valor válido en el Excel.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DataProcesoPLC] = []
        for row in rows:
            # Politica de la herramienta TUI anterior: dropna por UID. ``_safe_str`` ya mapea
            # ``None`` / ``""`` / ``"nan"`` / ``"None"`` / ``"null"`` a
            # ``""``. Un UID ``"0"`` o ``0`` pasa el filtro (es válido).
            if _safe_str(row.get("UID")) == "":
                continue
            plc_name = _safe_str(row.get("PLC"))
            if not plc_name:
                logger.warning("Fila sin PLC en %s: descartada", self.TABLE)
                continue
            try:
                result.append(
                    DataProcesoPLC(
                        uid=_safe_int(row.get("UID")),
                        nombre=_safe_str(row.get("Nombre")),
                        codigo=_safe_str(row.get("Codigo")),
                        preal=_safe_int(row.get("PReal")),
                        index_preal=_safe_int(row.get("Index_Preal")),
                        pint=_safe_int(row.get("PInt")),
                        index_pint=_safe_int(row.get("Index_Pint")),
                        alarmas=_safe_int(row.get("Alarmas")),
                        # Columna nueva del Excel. Mapeada
                        # aqui como ``alm_hmi``. Si el Excel NO
                        # tiene la columna (filas mas viejas),
                        # ``_safe_int`` retorna 0 -> desired=0, lo que
                        # baja el N_MAX en TIA. Opcion A confirmada
                        # por el operario: 'el Excel es la verdad'.
                        alm_hmi=_safe_int(row.get("Alarmas_Hmi")),
                        plc_name=plc_name,
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


__all__ = ["ProcesosParser"]
