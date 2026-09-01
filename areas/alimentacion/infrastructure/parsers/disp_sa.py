"""Parser de ``DispSA`` (Salidas Analógicas) del Excel corporativo.

Replica 1:1 del ``_build_disp_sa`` del parser consolidado legacy
(``AlimentacionExcelParser``). Estructura IDÉNTICA a ``DispEA`` (mismos
campos y semántica; solo cambia el sentido de la variable: salida vs
entrada).

Lee la ``ListObject`` ``Tabla_Disp_SA`` de la hoja ``DISP_SA`` del
workbook del departamento de alimentación y la mapea a una lista
de ``DispSA``.

Diferencias con el legacy:
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del ``ExcelLoader``.
    * Sin pandas: openpyxl directo + ``extract_list_object_rows``.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas inválidas se descartan con ``logger.warning``.
    * Si se inyecta un ``ConfigManager``, las constantes ``SHEET`` /
      ``TABLE`` se sobreescriben desde
      ``ConfigManager.get_excel_target_for("sa")``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.domain.models.excel_cache import DispSA
from areas.alimentacion.infrastructure.parsers._xlsx_helpers import (
    _safe_float,
    _safe_int,
    _safe_str,
    extract_list_object_rows,
)
from core.infrastructure.config_manager import ConfigManager


logger = logging.getLogger(__name__)


class DispSAParser:
    """Parser de la ``Tabla_Disp_SA`` (hoja ``DISP_SA``).

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"DISP_SA"``).
        * ``TABLE``: nombre de la ``ListObject``
          (``"Tabla_Disp_SA"``).

    Si se inyecta un ``ConfigManager`` con un ``excel_target``
    para ``"sa"``, los nombres se sobreescriben en ``__init__``.
    """

    SHEET = "DISP_SA"
    TABLE = "Tabla_Disp_SA"

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        if config_manager is not None:
            target = config_manager.get_excel_target_for("sa")
            if target is not None:
                sheet = target.get("sheet")
                table = target.get("table")
                if isinstance(sheet, str) and sheet:
                    self.SHEET = sheet
                if isinstance(table, str) and table:
                    self.TABLE = table

    def extraer(self, wb: Workbook) -> list[DispSA]:
        """Extrae todas las salidas analógicas del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aquí).

        Returns:
            Lista de ``DispSA``. Si la hoja o la tabla no existen,
            devuelve ``[]``. Las filas que fallen al construir el
            DTO se descartan con WARNING.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DispSA] = []
        for row in rows:
            if not _safe_str(row.get("UID")) and not _safe_str(row.get("Numero")):
                continue
            try:
                # ``UNIDADES`` en MAYÚSCULAS (legacy). Aceptamos
                # también ``Unidades`` por compat hacia delante.
                unidades_raw = row.get("UNIDADES")
                if unidades_raw is None:
                    unidades_raw = row.get("Unidades")
                result.append(
                    DispSA(
                        numero=_safe_int(row.get("Numero")),
                        plc_tag=_safe_str(row.get("PLC.Tag")),
                        plc_comentario=_safe_str(row.get("PLC.Comentario")),
                        descripcion=_safe_str(row.get("Descripcion")),
                        uid=_safe_str(row.get("UID")),
                        tag=_safe_str(row.get("Tag")),
                        fat=_safe_str(row.get("FAT")),
                        e_byte=_safe_int(row.get("E.Byte")),
                        unidades=_safe_str(unidades_raw),
                        rii=_safe_float(row.get("RII")),
                        rsi=_safe_float(row.get("RSI")),
                        gr_alarma=_safe_int(row.get("Gr.Alarma")),
                        cuadro=_safe_str(row.get("Cuadro")),
                        observaciones=_safe_str(row.get("Observaciones")),
                        plc_tipo=_safe_str(row.get("PLC.Tipo")),
                        plc_index=_safe_int(row.get("PLC.Index")),
                        hmi_index=_safe_int(row.get("Hmi.Index")),
                        hmi_texto=_safe_str(row.get("Hmi.Texto")),
                        cfg_habilitar=_safe_str(row.get("Cfg.Habilitar")),
                        cfg_byte_entrada=_safe_str(row.get("Cfg.ByteEntrada")),
                        cfg_escaladomin=_safe_str(row.get("Cfg.EscaladoMin")),
                        cfg_escaladomax=_safe_str(row.get("Cfg.EscaladoMax")),
                        cfg_grupo_alarma=_safe_str(row.get("Cfg.GrupoAlarma")),
                        comentario_db=_safe_str(row.get("ComentarioDB")),
                    )
                )
            except Exception as exc:  # defensivo: nunca romper la tabla
                logger.warning(
                    "Fila descartada en %s: %s", self.TABLE, exc,
                )
                continue
        return result


__all__ = ["DispSAParser"]
