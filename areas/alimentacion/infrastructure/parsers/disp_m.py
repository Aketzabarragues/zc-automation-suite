"""Parser de ``DispM`` (Motores digitales) del Excel corporativo.

Replica 1:1 del ``_build_dispm`` del parser consolidado legacy
(``AlimentacionExcelParser``). Lee la ``ListObject``
``Tabla_Disp_M`` de la hoja ``DISP_M`` del workbook del
departamento de alimentación y la mapea a una lista de ``DispM``.

Campos específicos: ``S.Byte/S.Bit`` (salida/activación),
``RT.Byte/RT.Bit`` (retorno térmico), ``RM.Byte/RM.Bit`` (retorno
de confirmación de marcha) + 8 campos SCL ``cfg_*`` que preservan
líneas SCL crudas (sin truncar).

Diferencias con el legacy:
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del ``ExcelLoader``.
    * Sin pandas: openpyxl directo + ``extract_list_object_rows``.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas inválidas se descartan con ``logger.warning``.
    * Si se inyecta un ``ConfigManager``, las constantes ``SHEET`` /
      ``TABLE`` se sobreescriben desde
      ``ConfigManager.get_excel_target_for("m")``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.domain.models.excel_cache import DispM
from areas.alimentacion.infrastructure.parsers._xlsx_helpers import (
    _safe_int,
    _safe_str,
    extract_list_object_rows,
)
from core.infrastructure.config_manager import ConfigManager


logger = logging.getLogger(__name__)


class DispMParser:
    """Parser de la ``Tabla_Disp_M`` (hoja ``DISP_M``).

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"DISP_M"``).
        * ``TABLE``: nombre de la ``ListObject``
          (``"Tabla_Disp_M"``).

    Si se inyecta un ``ConfigManager`` con un ``excel_target``
    para ``"m"``, los nombres se sobreescriben en ``__init__``.
    """

    SHEET = "DISP_M"
    TABLE = "Tabla_Disp_M"

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        if config_manager is not None:
            target = config_manager.get_excel_target_for("m")
            if target is not None:
                sheet = target.get("sheet")
                table = target.get("table")
                if isinstance(sheet, str) and sheet:
                    self.SHEET = sheet
                if isinstance(table, str) and table:
                    self.TABLE = table

    def extraer(self, wb: Workbook) -> list[DispM]:
        """Extrae todos los motores digitales del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aquí).

        Returns:
            Lista de ``DispM``. Si la hoja o la tabla no existen,
            devuelve ``[]``. Las filas que fallen al construir el
            DTO se descartan con WARNING.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DispM] = []
        for row in rows:
            if not _safe_str(row.get("UID")) and not _safe_str(row.get("Numero")):
                continue
            try:
                result.append(
                    DispM(
                        numero=_safe_int(row.get("Numero")),
                        plc_tag=_safe_str(row.get("PLC.Tag")),
                        plc_comentario=_safe_str(row.get("PLC.Comentario")),
                        descripcion=_safe_str(row.get("Descripcion")),
                        uid=_safe_str(row.get("UID")),
                        tag=_safe_str(row.get("Tag")),
                        fat=_safe_str(row.get("FAT")),
                        s_byte=_safe_int(row.get("S.Byte")),
                        s_bit=_safe_int(row.get("S.Bit")),
                        rt_byte=_safe_int(row.get("RT.Byte")),
                        rt_bit=_safe_int(row.get("RT.Bit")),
                        rm_byte=_safe_int(row.get("RM.Byte")),
                        rm_bit=_safe_int(row.get("RM.Bit")),
                        gr_alarma=_safe_int(row.get("Gr.Alarma")),
                        cuadro=_safe_str(row.get("Cuadro")),
                        observaciones=_safe_str(row.get("Observaciones")),
                        plc_tipo=_safe_str(row.get("PLC.Tipo")),
                        plc_index=_safe_int(row.get("PLC.Index")),
                        hmi_index=_safe_int(row.get("Hmi.Index")),
                        hmi_texto=_safe_str(row.get("Hmi.Texto")),
                        cfg_habilitar=_safe_str(row.get("Cfg.Habilitar")),
                        cfg_byteretornotermico=_safe_str(row.get("Cfg.ByteRetornoTermico")),
                        cfg_bitretornotermico=_safe_str(row.get("Cfg.BitRetornoTermico")),
                        cfg_byteconfmarcha=_safe_str(row.get("Cfg.ByteConfMarcha")),
                        cfg_bitconfmarcha=_safe_str(row.get("Cfg.BitConfMarcha")),
                        cfg_byteactivacion=_safe_str(row.get("Cfg.ByteActivacion")),
                        cfg_bitactivacion=_safe_str(row.get("Cfg.BitActivacion")),
                        cfg_habrettermico=_safe_str(row.get("Cfg.HabRetTermico")),
                        cfg_habretconfmarcha=_safe_str(row.get("Cfg.HabRetConfMarcha")),
                        cfg_grupoalarma=_safe_str(row.get("Cfg.GrupoAlarma")),
                        comentario_db=_safe_str(row.get("ComentarioDB")),
                    )
                )
            except Exception as exc:  # defensivo: nunca romper la tabla
                logger.warning(
                    "Fila descartada en %s: %s", self.TABLE, exc,
                )
                continue
        return result


__all__ = ["DispMParser"]
