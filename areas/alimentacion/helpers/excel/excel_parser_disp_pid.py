"""Parser de ``DispPID`` (Controladores PID) del Excel.

Lee la ``ListObject`` ``Tabla_Disp_PID`` de la hoja ``DISP_PID`` del
workbook del departamento de alimentación y la mapea a una lista de
``DispPID``.

Controlador PID: regulador de proceso. NO tiene E/S digital ni
campos analogicos directos: solo configuracion textual. Anade
``proceso`` (UID del proceso al que pertenece el PID), ``pv``
(process variable: nombre de la variable que se lee), ``disp_tipo``
y ``disp_tag`` (tipo/tag del display HMI del controlador).

Diferencias con el legacy:
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del ``ExcelLoader``.
    * Sin pandas: openpyxl directo + ``extract_list_object_rows``.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas inválidas se descartan con ``logger.warning``.
    * Si se inyecta un ``ConfigManager``, las constantes ``SHEET`` /
      ``TABLE`` se sobreescriben desde
      ``ConfigManager.get_excel_target_for("pid")``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.data.data_dispositivos import DispPID
from areas.alimentacion.helpers.excel._excel_helpers import (
    _safe_int,
    _safe_str,
    extract_list_object_rows,
)
from core.infrastructure.config.config_manager import ConfigManager


logger = logging.getLogger(__name__)


class DispPIDParser:
    """Parser de la ``Tabla_Disp_PID`` (hoja ``DISP_PID``).

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"DISP_PID"``).
        * ``TABLE``: nombre de la ``ListObject``
          (``"Tabla_Disp_PID"``).

    Si se inyecta un ``ConfigManager`` con un ``excel_target``
    para ``"pid"``, los nombres se sobreescriben en ``__init__``.
    """

    SHEET = "DISP_PID"
    TABLE = "Tabla_Disp_PID"

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        if config_manager is not None:
            target = config_manager.get_excel_target_for("pid")
            if target is not None:
                sheet = target.get("sheet")
                table = target.get("table")
                if isinstance(sheet, str) and sheet:
                    self.SHEET = sheet
                if isinstance(table, str) and table:
                    self.TABLE = table

    def extraer(self, wb: Workbook) -> list[DispPID]:
        """Extrae todos los controladores PID del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aquí).

        Returns:
            Lista de ``DispPID``. Si la hoja o la tabla no existen,
            devuelve ``[]``. Las filas que fallen al construir el
            DTO se descartan con WARNING.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DispPID] = []
        for row in rows:
            if not _safe_str(row.get("UID")) and not _safe_str(row.get("Numero")):
                continue
            try:
                result.append(
                    DispPID(
                        numero=_safe_int(row.get("Numero")),
                        plc_tag=_safe_str(row.get("PLC.Tag")),
                        plc_comentario=_safe_str(row.get("PLC.Comentario")),
                        descripcion=_safe_str(row.get("Descripcion")),
                        uid=_safe_str(row.get("UID")),
                        tag=_safe_str(row.get("Tag")),
                        fat=_safe_str(row.get("FAT")),
                        proceso=_safe_str(row.get("Proceso")),
                        pv=_safe_str(row.get("PV")),
                        disp_tipo=_safe_str(row.get("Disp.Tipo")),
                        disp_tag=_safe_str(row.get("Disp.Tag")),
                        observaciones=_safe_str(row.get("Observaciones")),
                        plc_tipo=_safe_str(row.get("PLC.Tipo")),
                        plc_index=_safe_int(row.get("PLC.Index")),
                        hmi_index=_safe_int(row.get("Hmi.Index")),
                        hmi_texto=_safe_str(row.get("Hmi.Texto")),
                        cfg_habilitar=_safe_str(row.get("Cfg.Habilitar")),
                        comentario_db=_safe_str(row.get("ComentarioDB")),
                    )
                )
            except Exception as exc:  # defensivo: nunca romper la tabla
                logger.warning(
                    "Fila descartada en %s: %s", self.TABLE, exc,
                )
                continue
        logger.debug(
            f"Parser[{self.SHEET}/{self.TABLE}]: "
            f"{len(rows)} filas -> {len(result)} extraidas"
        )
        return result


__all__ = ["DispPIDParser"]
