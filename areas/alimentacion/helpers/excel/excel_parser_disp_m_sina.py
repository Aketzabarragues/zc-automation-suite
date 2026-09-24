"""Parser de ``DispMSINA`` (Motores Sinamics) del Excel.

Lee la ``ListObject`` ``Tabla_Disp_M_SINA`` de la hoja ``DISP_M_SINA``
del workbook del departamento de alimentación y la mapea a una lista
de ``DispMSINA``.

Motor sinamics: variador analogico sin E/S digital. NO comparte
activacion digital (S/RM) ni consigna analogica (SA) con ``DispM_VF``,
pero añade ``vel_min``/``vel_max``/``cons_k`` (parametros analogicos
del variador) + sus 3 ``cfg_*`` SCL.

Diferencias con el legacy:
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del ``ExcelLoader``.
    * Sin pandas: openpyxl directo + ``extract_list_object_rows``.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas inválidas se descartan con ``logger.warning``.
    * Si se inyecta un ``ConfigManager``, las constantes ``SHEET`` /
      ``TABLE`` se sobreescriben desde
      ``ConfigManager.get_excel_target_for("m_sina")``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.data.data_dispositivos import DispMSINA
from areas.alimentacion.helpers.excel._excel_helpers import (
    _safe_float,
    _safe_int,
    _safe_str,
    extract_list_object_rows,
)
from core.infrastructure.config.config_manager import ConfigManager


logger = logging.getLogger(__name__)


class DispMSINAParser:
    """Parser de la ``Tabla_Disp_M_SINA`` (hoja ``DISP_M_SINA``).

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"DISP_M_SINA"``).
        * ``TABLE``: nombre de la ``ListObject``
          (``"Tabla_Disp_M_SINA"``).

    Si se inyecta un ``ConfigManager`` con un ``excel_target``
    para ``"m_sina"``, los nombres se sobreescriben en ``__init__``.
    """

    SHEET = "DISP_M_SINA"
    TABLE = "Tabla_Disp_M_SINA"

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        if config_manager is not None:
            target = config_manager.get_excel_target_for("m_sina")
            if target is not None:
                sheet = target.get("sheet")
                table = target.get("table")
                if isinstance(sheet, str) and sheet:
                    self.SHEET = sheet
                if isinstance(table, str) and table:
                    self.TABLE = table

    def extraer(self, wb: Workbook) -> list[DispMSINA]:
        """Extrae todos los motores sinamics del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aquí).

        Returns:
            Lista de ``DispMSINA``. Si la hoja o la tabla no existen,
            devuelve ``[]``. Las filas que fallen al construir el
            DTO se descartan con WARNING.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DispMSINA] = []
        for row in rows:
            if not _safe_str(row.get("UID")) and not _safe_str(row.get("Numero")):
                continue
            try:
                result.append(
                    DispMSINA(
                        numero=_safe_int(row.get("Numero")),
                        plc_tag=_safe_str(row.get("PLC.Tag")),
                        plc_comentario=_safe_str(row.get("PLC.Comentario")),
                        descripcion=_safe_str(row.get("Descripcion")),
                        uid=_safe_str(row.get("UID")),
                        tag=_safe_str(row.get("Tag")),
                        fat=_safe_str(row.get("FAT")),
                        rt_byte=_safe_int(row.get("RT.Byte")),
                        rt_bit=_safe_int(row.get("RT.Bit")),
                        vel_min=_safe_float(row.get("Vel.Min")),
                        vel_max=_safe_float(row.get("Vel.Max")),
                        cons_k=_safe_float(row.get("ConsK")),
                        gr_alarma=_safe_int(row.get("Gr.Alarma")),
                        cuadro=_safe_str(row.get("Cuadro")),
                        observaciones=_safe_str(row.get("Observaciones")),
                        plc_tipo=_safe_str(row.get("PLC.Tipo")),
                        plc_index=_safe_int(row.get("PLC.Index")),
                        hmi_index=_safe_int(row.get("Hmi.Index")),
                        hmi_texto=_safe_str(row.get("Hmi.Texto")),
                        cfg_habilitar=_safe_str(row.get("Cfg.Habilitar")),
                        cfg_byteretornotermico=_safe_str(
                            row.get("Cfg.ByteRetornoTermico")
                        ),
                        cfg_bitretornotermico=_safe_str(
                            row.get("Cfg.BitRetornoTermico")
                        ),
                        cfg_vel_min=_safe_str(row.get("Cfg.VelMin")),
                        cfg_vel_max=_safe_str(row.get("Cfg.VelMax")),
                        cfg_cons_k=_safe_str(row.get("Cfg.ConstK")),
                        cfg_grupo_alarma=_safe_str(row.get("Cfg.GrupoAlarma")),
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


__all__ = ["DispMSINAParser"]
