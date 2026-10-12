"""Parser de ``DispSD`` (Salidas Digitales) del Excel corporativo.

Replica 1:1 del patron del ``excel_parser_disp_ed.py``: lee la
``ListObject`` ``Tabla_Disp_SD`` de la hoja ``DISP_SD`` del workbook
del departamento de alimentacion y la mapea a una lista de ``DispSD``.

Campos especificos (vs. ``DispED``): ``S.Byte``/``S.Bit`` en lugar
de ``E.Byte``/``E.Bit`` (es el reverso logico de una entrada
digital). Conserva el resto del contrato (Gr.Alarma, Cuadro,
Cfg.ByteEntrada / Cfg.BitEntrada / Cfg.GrupoAlarma).

Diferencias con el legacy:
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del ``ExcelLoader``.
    * Sin pandas: openpyxl directo + ``extract_list_object_rows``.
    * Defensivo: cada fila se envuelve en ``try/except`` y las
      filas invalidas se descartan con ``logger.warning``.
    * Si se inyecta un ``ConfigManager``, las constantes ``SHEET`` /
      ``TABLE`` se sobreescriben desde
      ``ConfigManager.get_excel_target_for("sd")``.

Restriccion arquitectonica: este modulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook

from areas.alimentacion.data.data_dispositivos import DispSD
from areas.alimentacion.helpers.excel._excel_helpers import (
    _safe_int,
    _safe_str,
    extract_list_object_rows,
)
from core.infrastructure.config.config_manager import ConfigManager


logger = logging.getLogger(__name__)


class DispSDParser:
    """Parser de la ``Tabla_Disp_SD`` (hoja ``DISP_SD``).

    Atributos de clase:
        * ``SHEET``: nombre literal de la hoja (``"DISP_SD"``).
        * ``TABLE``: nombre de la ``ListObject``
          (``"Tabla_Disp_SD"``).

    Si se inyecta un ``ConfigManager`` con un ``excel_target``
    para ``"sd"``, los nombres se sobreescriben en ``__init__``.
    """

    SHEET = "DISP_SD"
    TABLE = "Tabla_Disp_SD"

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        if config_manager is not None:
            target = config_manager.get_excel_target_for("sd")
            if target is not None:
                sheet = target.get("sheet")
                table = target.get("table")
                if isinstance(sheet, str) and sheet:
                    self.SHEET = sheet
                if isinstance(table, str) and table:
                    self.TABLE = table

    def extraer(self, wb: Workbook) -> list[DispSD]:
        """Extrae todas las salidas digitales del workbook.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aqui).

        Returns:
            Lista de ``DispSD``. Si la hoja o la tabla no existen,
            devuelve ``[]``. Las filas que fallen al construir el
            DTO se descartan con WARNING.
        """
        rows = extract_list_object_rows(wb, self.SHEET, self.TABLE)
        result: list[DispSD] = []
        for row in rows:
            # Politica legacy: descartar filas sin UID ni Numero.
            if not _safe_str(row.get("UID")) and not _safe_str(row.get("Numero")):
                continue
            plc_name = _safe_str(row.get("PLC"))
            if not plc_name:
                logger.warning("Fila sin PLC en %s: descartada", self.TABLE)
                continue
            try:
                result.append(
                    DispSD(
                        numero=_safe_int(row.get("Numero")),
                        plc_tag=_safe_str(row.get("PLC.Tag")),
                        plc_comentario=_safe_str(row.get("PLC.Comentario")),
                        descripcion=_safe_str(row.get("Descripcion")),
                        uid=_safe_str(row.get("UID")),
                        tag=_safe_str(row.get("Tag")),
                        fat=_safe_str(row.get("FAT")),
                        s_byte=_safe_int(row.get("S.Byte")),
                        s_bit=_safe_int(row.get("S.Bit")),
                        gr_alarma=_safe_int(row.get("Gr.Alarma")),
                        cuadro=_safe_str(row.get("Cuadro")),
                        observaciones=_safe_str(row.get("Observaciones")),
                        plc_tipo=_safe_str(row.get("PLC.Tipo")),
                        plc_index=_safe_int(row.get("PLC.Index")),
                        hmi_index=_safe_int(row.get("Hmi.Index")),
                        hmi_texto=_safe_str(row.get("Hmi.Texto")),
                        cfg_habilitar=_safe_str(row.get("Cfg.Habilitar")),
                        cfg_byte_entrada=_safe_str(row.get("Cfg.ByteEntrada")),
                        cfg_bit_entrada=_safe_str(row.get("Cfg.BitEntrada")),
                        cfg_grupo_alarma=_safe_str(row.get("Cfg.GrupoAlarma")),
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


__all__ = ["DispSDParser"]
