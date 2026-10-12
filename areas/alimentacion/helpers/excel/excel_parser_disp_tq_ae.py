"""Parser de ``DispTQ_AE`` (Tanque Aire Esteril) del Excel corporativo.

DTO paralelo a ``DispTQ`` (mismos campos, otro ``canonical`` para
no mezclar lecturas de aire esteril con lecturas de tanques
normales en la SPA ni en el catalogo). Este parser es identico en
estructura al de ``DispTQ`` pero opera sobre la hoja/tabla
``DISP_TQ_AE`` / ``Tabla_Disp_TQ_AE`` y mapea al DTO ``DispTQ_AE``.

Diferencias con el legacy:
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del ``ExcelLoader``.
    * Sin pandas: openpyxl directo + ``extract_list_object_rows``.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas invalidas se descartan con ``logger.warning``.
    * Si se inyecta un ``ConfigManager``, las constantes ``SHEET`` /
      ``TABLE`` se sobreescriben desde
      ``ConfigManager.get_excel_target_for("tq_ae")``.

Restriccion arquitectonica: este modulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.data.data_dispositivos import DispTQ_AE
from areas.alimentacion.helpers.excel._excel_helpers import (
    _safe_int,
    _safe_str,
    extract_list_object_rows,
)
from core.infrastructure.config.config_manager import ConfigManager


logger = logging.getLogger(__name__)


class DispTQ_AEParser:
    """Parser de la ``Tabla_Disp_TQ_AE`` (hoja ``DISP_TQ_AE``).

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"DISP_TQ_AE"``).
        * ``TABLE``: nombre de la ``ListObject``
          (``"Tabla_Disp_TQ_AE"``).

    Si se inyecta un ``ConfigManager`` con un ``excel_target``
    para ``"tq_ae"``, los nombres se sobreescriben en ``__init__``.
    """

    SHEET = "DISP_TQ_AE"
    TABLE = "Tabla_Disp_TQ_AE"

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        if config_manager is not None:
            target = config_manager.get_excel_target_for("tq_ae")
            if target is not None:
                sheet = target.get("sheet")
                table = target.get("table")
                if isinstance(sheet, str) and sheet:
                    self.SHEET = sheet
                if isinstance(table, str) and table:
                    self.TABLE = table

    def extraer(self, wb: Workbook) -> list[DispTQ_AE]:
        """Extrae todos los tanques de aire esteril del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aqui).

        Returns:
            Lista de ``DispTQ_AE``. Si la hoja o la tabla no
            existen, devuelve ``[]``. Las filas que fallen al
            construir el DTO se descartan con WARNING.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DispTQ_AE] = []
        for row in rows:
            if not _safe_str(row.get("UID")) and not _safe_str(row.get("Numero")):
                continue
            plc_name = _safe_str(row.get("PLC"))
            if not plc_name:
                logger.warning("Fila sin PLC en %s: descartada", self.TABLE)
                continue
            try:
                result.append(
                    DispTQ_AE(
                        numero=_safe_int(row.get("Numero")),
                        plc_tag=_safe_str(row.get("PLC.Tag")),
                        plc_comentario=_safe_str(row.get("PLC.Comentario")),
                        descripcion=_safe_str(row.get("Descripcion")),
                        uid=_safe_str(row.get("UID")),
                        tag=_safe_str(row.get("Tag")),
                        fat=_safe_str(row.get("FAT")),
                        observaciones=_safe_str(row.get("Observaciones")),
                        plc_tipo=_safe_str(row.get("PLC.Tipo")),
                        plc_index=_safe_int(row.get("PLC.Index")),
                        hmi_index=_safe_int(row.get("Hmi.Index")),
                        hmi_texto=_safe_str(row.get("Hmi.Texto")),
                        cfg_habilitar=_safe_str(row.get("Cfg.Habilitar")),
                        comentario_db=_safe_str(row.get("ComentarioDB")),
                        plc_name=plc_name,
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


__all__ = ["DispTQ_AEParser"]
