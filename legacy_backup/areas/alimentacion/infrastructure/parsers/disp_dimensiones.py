"""Parser de ``N_MAX`` (defined names) del Excel corporativo.

Absorbe la lógica de:
  - ``core/infrastructure/parsers/excel_parser.py::extraer_dimensiones``
    (filtra prefijos ``N_MAX_``/``Num_Disp_``, castea a ``int``).
  - ``AlimentacionExcelParser::extraer_dimensiones`` (puebla
    ``DimensionesDispositivos`` con ``extras``).

Diferencias con el legacy:
    * Recibe el workbook **ya abierto** (``wb: Workbook``). NO abre
      el archivo: esa responsabilidad es del ``ExcelLoader``.
    * Si se inyecta un ``ConfigManager``, el ``named_range_map`` se
      construye data-driven desde
      ``ConfigManager.list_nmax_active()`` /
      ``ConfigManager.get_nmax_entry(name)``. Si no, se usa el
      ``_DEFAULT_NAMED_RANGE_MAP`` (6 legacy).
    * Sin pandas: openpyxl directo + ``workbook.defined_names``.
    * Defensivo: defined names que no se puedan resolver se
      descartan silenciosamente.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging
from typing import Any

from openpyxl import Workbook

from areas.alimentacion.domain.models.excel_cache import DimensionesDispositivos
from areas.alimentacion.infrastructure.parsers._xlsx_helpers import (
    _safe_int,
    logger,
)
from core.infrastructure.config_manager import ConfigManager


# Mapa por defecto de named ranges N_MAX / num_disp_* → atributo
# legacy. Se usa como fallback cuando el parser se construye sin
# ``ConfigManager`` (modo histórico) o cuando ``extraer`` se llama
# sin ``named_range_map``.
_DEFAULT_NAMED_RANGE_MAP: dict[str, str] = {
    "N_MAX_DISP_ED":   "num_disp_ed",
    "N_MAX_DISP_EA":   "num_disp_ea",
    "N_MAX_DISP_SA":   "num_disp_sa",
    "N_MAX_DISP_V":    "num_disp_v",
    "N_MAX_DISP_M":    "num_disp_m",
    "N_MAX_DISP_M_VF": "num_disp_m_vf",
    "num_disp_ed":     "num_disp_ed",
    "num_disp_ea":     "num_disp_ea",
    "num_disp_sa":     "num_disp_sa",
    "num_disp_v":      "num_disp_v",
    "num_disp_m":      "num_disp_m",
    "num_disp_m_vf":   "num_disp_m_vf",
}


class DimensionesParser:
    """Parser de los defined names ``N_MAX_*``/``Num_Disp_*`` del Excel.

    Atributos de clase:
        * ``PREFIXES``: tupla de prefijos válidos para el filtrado
          defensivo de N_MAX adicionales (``"N_MAX_"`` y
          ``"Num_Disp_"``).

    Política:
        * Si la hoja/celda del defined name no se puede resolver
          (``KeyError``, ``TypeError``, ``AttributeError``), se
          descarta con WARNING.
        * Si el valor no se puede castear a ``int``, se descarta
          silenciosamente.
        * Si el defined name NO está en el ``named_range_map`` Y NO
          empieza por ``N_MAX_``/``Num_Disp_``, se ignora (no es un
          N_MAX).
        * Si el defined name NO está en el ``named_range_map`` pero
          empieza por ``N_MAX_``/``Num_Disp_``, va a ``extras`` (data
          driven: futuros N_MAX del catálogo).

    Si se inyecta un ``ConfigManager``, el ``named_range_map`` se
    construye data-driven desde el ``n_max_catalog`` del config.
    """

    PREFIXES: tuple[str, ...] = ("N_MAX_", "Num_Disp_")

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self._config_manager = config_manager
        self._named_range_map: dict[str, str] = self._build_named_range_map()

    def _build_named_range_map(self) -> dict[str, str]:
        """Devuelve ``{nombre_nmax: nombre_attr_legacy}``.

        Si hay ``ConfigManager``, itera ``list_nmax_active()`` y
        resuelve ``hw_type`` → ``num_disp_<hw>``. Si no, usa
        ``_DEFAULT_NAMED_RANGE_MAP``.
        """
        if self._config_manager is None:
            return dict(_DEFAULT_NAMED_RANGE_MAP)
        mapping: dict[str, str] = {}
        for nmax_name in self._config_manager.list_nmax_active():
            entry = self._config_manager.get_nmax_entry(nmax_name) or {}
            hw = entry.get("hw_type", "")
            if not hw:
                continue
            attr = f"num_disp_{hw}"
            mapping[nmax_name] = attr
            # Aceptamos también la forma legacy (``Num_Disp_X``).
            excel_nr = entry.get("excel_named_range", "")
            if excel_nr:
                mapping[excel_nr] = attr
            # Y la forma minúscula ``num_disp_x``.
            mapping[attr] = attr
        return mapping

    def extraer(
        self,
        wb: Workbook,
        named_range_map: dict[str, str] | None = None,
    ) -> DimensionesDispositivos:
        """Lee ``wb.defined_names`` y popula ``DimensionesDispositivos``.

        Args:
            wb: workbook de openpyxl **ya abierto** (no se cierra
                aquí; la responsabilidad es del ``ExcelLoader``).
            named_range_map: override opcional del mapeo
                ``{nombre_nmax: nombre_attr_legacy}``. Si es ``None``,
                se usa el del ``ConfigManager`` (si se inyectó) o el
                ``_DEFAULT_NAMED_RANGE_MAP``.

        Returns:
            ``DimensionesDispositivos`` con los 6 contadores
            canónicos + ``extras`` para N_MAX adicionales del Excel.
        """
        defined_names = getattr(wb, "defined_names", None)
        if defined_names is None:
            return DimensionesDispositivos()

        items: Any = (
            defined_names.items()
            if hasattr(defined_names, "items")
            else []
        )

        # Mapa a usar (override > CM > default).
        if named_range_map is None:
            named_range_map = self._named_range_map

        result: dict[str, int] = {}
        extras: dict[str, int] = {}
        for name, definition in items:
            if not isinstance(name, str):
                continue
            attr = named_range_map.get(name)
            if attr is not None:
                value = _safe_int(_resolve_value(definition, wb))
                result[attr] = value
            else:
                # Si el named range no es de los legacy, intentar leerlo
                # como N_MAX directo (data-driven): p.ej. un Excel que
                # defina ``N_MAX_DISP_FF`` → acaba en ``extras``.
                if any(name.startswith(p) for p in self.PREFIXES):
                    v = _safe_int(_resolve_value(definition, wb))
                    if v:
                        extras[name] = v

        if result:
            kwargs = dict(result)
            if extras:
                kwargs["extras"] = extras
            return DimensionesDispositivos(**kwargs)
        if extras:
            return DimensionesDispositivos(extras=extras)
        return DimensionesDispositivos()


# ── Helpers de mapeo de named ranges (privados al módulo) ──────────────


def _resolve_value(definition: Any, workbook: Any) -> Any:
    """Lee el valor de un ``DefinedName`` resolviendo su hoja y celda.

    Returns:
        El valor de la celda referenciada o ``None`` si no se pudo
        resolver la hoja/celda.
    """
    # Compatibilidad: openpyxl 3.1+ expone ``attr_text``; las
    # versiones anteriores usaban ``value``. Aceptamos ambos.
    attr_text: Any = (
        getattr(definition, "attr_text", None)
        or getattr(definition, "value", None)
    )
    if not isinstance(attr_text, str) or "!" not in attr_text:
        return None

    sheet_part, cell_part = attr_text.split("!", 1)
    sheet_name = sheet_part.strip().strip("'").strip('"')
    cell_ref = cell_part.replace("$", "").strip()
    try:
        sheet = workbook[sheet_name]
    except (KeyError, TypeError):
        return None
    try:
        # ``destinations`` es la API moderna (openpyxl 3.1).
        # Si está disponible, devuelve (sheet, coord) directamente.
        destinations = getattr(definition, "destinations", None)
        if destinations is not None:
            dest = list(destinations)
            if dest:
                sheet_name, coord = dest[0]
                cell = workbook[sheet_name][coord]
                if isinstance(cell, tuple):
                    cell = cell[0][0] if isinstance(cell[0], tuple) else cell[0]
                return getattr(cell, "value", None)
        # Fallback: parsear ``attr_text``.
        cell = sheet[cell_ref]
    except (KeyError, AttributeError, TypeError):
        return None
    return getattr(cell, "value", None)


__all__ = ["DimensionesParser"]
