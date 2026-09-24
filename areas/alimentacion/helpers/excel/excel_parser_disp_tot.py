"""Parser de ``DispTOT`` (Totalizadores) del Excel.

Lee la ``ListObject`` ``Tabla_Disp_TOT`` de la hoja ``DISP_TOT`` del
workbook del departamento de alimentación y la mapea a una lista de
``DispTOT``.

Totalizador: contador de pulsos con factor de conversion. Anade
``tipo`` (clasificacion: litros, kg, m3, ...), ``incxpulso``
(incremento por pulso: factor de conversion pulso->unidad) y
``proceso`` (UID del proceso al que pertenece el totalizador).

Diferencias con el legacy:
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del ``ExcelLoader``.
    * Sin pandas: openpyxl directo + ``extract_list_object_rows``.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas inválidas se descartan con ``logger.warning``.
    * Si se inyecta un ``ConfigManager``, las constantes ``SHEET`` /
      ``TABLE`` se sobreescriben desde
      ``ConfigManager.get_excel_target_for("tot")``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.data.data_dispositivos import DispTOT
from areas.alimentacion.helpers.excel._excel_helpers import (
    _safe_float,
    _safe_int,
    _safe_str,
    extract_list_object_rows,
)
from core.infrastructure.config.config_manager import ConfigManager


logger = logging.getLogger(__name__)


class DispTOTParser:
    """Parser de la ``Tabla_Disp_TOT`` (hoja ``DISP_TOT``).

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"DISP_TOT"``).
        * ``TABLE``: nombre de la ``ListObject``
          (``"Tabla_Disp_TOT"``).

    Si se inyecta un ``ConfigManager`` con un ``excel_target``
    para ``"tot"``, los nombres se sobreescriben en ``__init__``.
    """

    SHEET = "DISP_TOT"
    TABLE = "Tabla_Disp_TOT"

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        if config_manager is not None:
            target = config_manager.get_excel_target_for("tot")
            if target is not None:
                sheet = target.get("sheet")
                table = target.get("table")
                if isinstance(sheet, str) and sheet:
                    self.SHEET = sheet
                if isinstance(table, str) and table:
                    self.TABLE = table

    def extraer(self, wb: Workbook) -> list[DispTOT]:
        """Extrae todos los totalizadores del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aquí).

        Returns:
            Lista de ``DispTOT``. Si la hoja o la tabla no existen,
            devuelve ``[]``. Las filas que fallen al construir el
            DTO se descartan con WARNING.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DispTOT] = []
        for row in rows:
            if not _safe_str(row.get("UID")) and not _safe_str(row.get("Numero")):
                continue
            try:
                result.append(
                    DispTOT(
                        numero=_safe_int(row.get("Numero")),
                        plc_tag=_safe_str(row.get("PLC.Tag")),
                        plc_comentario=_safe_str(row.get("PLC.Comentario")),
                        descripcion=_safe_str(row.get("Descripcion")),
                        uid=_safe_str(row.get("UID")),
                        tag=_safe_str(row.get("Tag")),
                        fat=_safe_str(row.get("FAT")),
                        tipo=_safe_str(row.get("Tipo")),
                        e_byte=_safe_int(row.get("E.Byte")),
                        e_bit=_safe_int(row.get("E.Bit")),
                        incxpulso=_safe_float(row.get("IncXPulso")),
                        gr_alarma=_safe_int(row.get("Gr.Alarma")),
                        proceso=_safe_str(row.get("Proceso")),
                        observaciones=_safe_str(row.get("Observaciones")),
                        plc_tipo=_safe_str(row.get("PLC.Tipo")),
                        plc_index=_safe_int(row.get("PLC.Index")),
                        hmi_index=_safe_int(row.get("Hmi.Index")),
                        hmi_texto=_safe_str(row.get("Hmi.Texto")),
                        cfg_habilitar=_safe_str(row.get("Cfg.Habilitar")),
                        cfg_byteentrada=_safe_str(row.get("Cfg.ByteEntrada")),
                        cfg_bitentrada=_safe_str(row.get("Cfg.BitEntrada")),
                        cfg_tipo=_safe_str(row.get("Cfg.Tipo")),
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


__all__ = ["DispTOTParser"]
