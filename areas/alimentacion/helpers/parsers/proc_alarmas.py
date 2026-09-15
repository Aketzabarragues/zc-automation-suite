"""Parser de alarmas del Excel corporativo.

Extrae la ``ListObject`` ``Tabla_Alarmas`` de la hoja ``ALARMAS`` del
workbook del departamento de alimentaciÃƒÂ³n y la mapea a una lista
de ``DataAlarmaPLC`` (DTO inmutable definido en
``areas.alimentacion.domain.models.excel_cache``).

Diferencias con el legacy TUI (``_legacy_reference/ZC_ALM_TOOLS``):
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del loader / endpoint /
      MCP tool (Fase 5). Esto evita abrir el workbook 4 veces (uno
      por parser de software) y soporta el patrÃƒÂ³n de Fase 5 donde
      el ``ExcelLoader`` abre el workbook UNA vez y compone 11
      parsers.
    * Sin pandas: openpyxl directo. Coherente con el parser
      consolidado ``AlimentacionExcelParser`` del repo.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas invÃƒÂ¡lidas se descartan con ``logger.warning`` (no
      rompen la carga). ``extract_list_object_rows`` ya devuelve
      ``[]`` si la hoja o la tabla no existen.
    * Mismas claves literales del Excel que el legacy
      (``_legacy_reference/ZC_ALM_TOOLS/infrastructure/parsers/
      software/alarmas.py`` lÃƒÂ­neas 23-30): ``UID``, ``Numero``,
      ``Proceso``, ``Num.DB``, ``Descripcion``, ``ComentarioDB``.
      **NO** se lee ``Visibilidad`` (no existe en esta tabla del
      legacy; R-F4.1 del plan documenta que si el Excel la trae en
      el futuro, se ignora silenciosamente).

Esta es la **implementaciÃƒÂ³n de referencia** que los 6 mini parsers
de dispositivos de Fase 5 (``disp_ed.py``, ``disp_ea.py``,
``disp_sa.py``, ``disp_v.py``, ``disp_m.py``, ``disp_m_vf.py``)
imitarÃƒÂ¡n en estructura: cada uno es una clase con
``SHEET``/``TABLE`` como constantes y un ÃƒÂºnico mÃƒÂ©todo
``extraer(self, wb: Workbook) -> list[DTO]`` que delega en
``extract_list_object_rows`` y descarta filas invÃƒÂ¡lidas con
``logger.warning``. Los parsers de Fase 5 serÃƒÂ¡n casi 1:1 con
``AlarmasParser`` cambiando solo el DTO destino y las claves de
columna (R5 del plan, R-F4.1 tambiÃƒÂ©n).

R-F4.1 (defensa contra schema drift): el mÃƒÂ©todo ``extraer`` solo
lee las 6 claves que conoce (``UID``, ``Numero``, ``Proceso``,
``Num.DB``, ``Descripcion``, ``ComentarioDB``). Si el Excel incluye
columnas adicionales (por ejemplo, ``Visibilidad`` si el
corporativo decide aÃƒÂ±adirla en el futuro), esas columnas se
ignoran silenciosamente: el ``dict`` que devuelve
``extract_list_object_rows`` las contendrÃƒÂ¡ como claves, pero el
constructor de ``DataAlarmaPLC`` no las acepta (``frozen=True`` con
lista cerrada de campos) y el ``try/except`` que rodea la
construcciÃƒÂ³n las descarta con WARNING. El test
``test_columna_visibilidad_en_excel_se_ignora`` verifica esta
propiedad.

RestricciÃƒÂ³n arquitectÃƒÂ³nica: este mÃƒÂ³dulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.data.data_Alarmas import DataAlarmaPLC
from areas.alimentacion.helpers.parsers._xlsx_helpers import (
    _safe_int,
    _safe_str,
    extract_list_object_rows,
)


logger = logging.getLogger(__name__)


class AlarmasParser:
    """Parser de la ``Tabla_Alarmas`` (hoja ``ALARMAS``).

    Mapea cada fila de la ``ListObject`` a un ``DataAlarmaPLC``. Las
    claves de columna son **literales** (con mayÃƒÂºsculas, puntos y
    espacios) Ã¢â‚¬â€ exactamente como aparecen en el Excel del
    corporativo y como las consumÃƒÂ­a el legacy.

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"ALARMAS"``).
        * ``TABLE``: nombre de la ``ListObject``
          (``"Tabla_Alarmas"``).

    ImplementaciÃƒÂ³n de referencia: este parser es la plantilla
    que los 6 mini parsers de dispositivos (Fase 5.3 del plan)
    imitarÃƒÂ¡n. La ÃƒÂºnica diferencia entre ``AlarmasParser`` y un
    futuro ``DispEDParser`` serÃƒÂ¡:

        * Constantes ``SHEET``/``TABLE`` apuntando a la hoja y
          ``ListObject`` del dispositivo correspondiente.
        * DTO destino (en este caso ``DataAlarmaPLC``, 6 campos; en
          Fase 5 serÃƒÂ¡ ``DispED``, 11+ campos, etc.).
        * Claves de columna leÃƒÂ­das (las 6 del legacy alarmas, o
          las N del dispositivo).
    """

    SHEET = "ALARMAS"
    TABLE = "Tabla_Alarmas"

    def extraer(self, wb: Workbook) -> list[DataAlarmaPLC]:
        """Lee las alarmas del workbook ya abierto.

        Descarta las filas con UID vacÃƒÂ­o y las que fallen al
        construir el DTO. Si la hoja o la tabla no existen,
        devuelve ``[]``.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DataAlarmaPLC] = []
        for row in rows:
            # PolÃƒÂ­tica legacy: dropna por UID. ``_safe_str`` ya
            # mapea ``None`` / ``""`` / ``"nan"`` / ``"None"`` /
            # ``"null"`` a ``""``.
            if _safe_str(row.get("UID")) == "":
                continue
            try:
                result.append(
                    DataAlarmaPLC(
                        uid=_safe_str(row.get("UID")),
                        numero=_safe_str(row.get("Numero")),
                        proceso=_safe_str(row.get("Proceso")),
                        num_db=_safe_int(row.get("Num.DB")),
                        descripcion=_safe_str(row.get("Descripcion")),
                        comentario_db=_safe_str(row.get("ComentarioDB")),
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


__all__ = ["AlarmasParser"]
