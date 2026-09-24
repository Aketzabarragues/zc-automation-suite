"""Parser de N_MAX del Excel corporativo.

Lee ``wb.defined_names`` y entrega un ``DimensionesDispositivos`` con
nombres canonicos de TIA (``N_MAX_DISP_*``).

Acepta los 3 prefijos que pueda tener el Excel:
  - ``N_MAX_DISP_X``  (canonico TIA, alineado con el PLC)
  - ``Num_Disp_X``    (Title Case, estilo corporativo)
  - ``num_disp_x``    (lowercase legacy)

Todos se traducen al canonico. El Excel del operario tiene los 3
estilos en distintas hojas (definicion vs configuracion); el parser
los normaliza en una sola pasada.

Si se inyecta un ``ConfigManager``, el ``n_max_catalog`` resuelve el
nombre canonico de cada hw (data-driven). Si no, se usa un fallback
hardcoded de 6 hw_types (ED, EA, SA, V, M, M_VF).

Restriccion: este modulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging
from typing import Any

from openpyxl import Workbook

from areas.alimentacion.data.data_dimensiones import DimensionesDispositivos
from areas.alimentacion.helpers.excel._excel_helpers import (
    _safe_int,
    logger,
)
from core.infrastructure.config.config_manager import ConfigManager


# Fallback hardcoded: nombre canonico TIA por hw_type. Solo se usa si
# el parser se construye sin ``ConfigManager`` (modo historico o
# tests sin CM).
_FALLBACK_HW_TO_CANONICAL: dict[str, str] = {
    "ed":    "N_MAX_DISP_ED",
    "ea":    "N_MAX_DISP_EA",
    "sa":    "N_MAX_DISP_SA",
    "v":     "N_MAX_DISP_V",
    "m":     "N_MAX_DISP_M",
    "m_vf":  "N_MAX_DISP_M_VF",
}

# Prefijos validos de defined names. El parser acepta los 3 y los
# normaliza al canonico.
_PREFIXES: tuple[str, ...] = ("N_MAX_DISP_", "Num_Disp_", "num_disp_")


class DimensionesParser:
    """Parser de defined names N_MAX del Excel.

    Atributos:
        ``_hw_to_canonical``: ``{hw_type: nombre_canonico}``. Data-driven
            si hay ``ConfigManager``, fallback hardcoded si no.

    Politica:
        - Defined names que no empiecen por ninguno de los 3 prefijos
          se ignoran silenciosamente.
        - Defined names cuyo sufijo no se pueda resolver a un hw_type
          conocido se descartan con WARNING.
        - Valores no casteables a ``int`` se descartan silenciosamente.
    """

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self._config_manager = config_manager
        self._hw_to_canonical: dict[str, str] = self._build_hw_to_canonical()

    def _build_hw_to_canonical(self) -> dict[str, str]:
        """``{hw_type: N_MAX_DISP_<hw>}`` desde el ``n_max_catalog`` o fallback."""
        if self._config_manager is None:
            return dict(_FALLBACK_HW_TO_CANONICAL)
        result: dict[str, str] = {}
        for name in self._config_manager.list_nmax_active():
            entry = self._config_manager.get_nmax_entry(name) or {}
            hw = str(entry.get("hw_type", "")).strip()
            if name.startswith("N_MAX_") and hw:
                result[hw] = name
        return result or dict(_FALLBACK_HW_TO_CANONICAL)

    def _canonical_from_name(self, name: str) -> str | None:
        """Traduce un defined name al canonico ``N_MAX_DISP_*``.

        Returns:
            Nombre canonico o ``None`` si no se reconoce.
        """
        for prefix in _PREFIXES:
            if name.startswith(prefix):
                suffix = name[len(prefix):].lower()
                return self._hw_to_canonical.get(suffix)
        return None

    def extraer(self, wb: Workbook) -> DimensionesDispositivos:
        """Lee ``wb.defined_names`` y devuelve un ``DimensionesDispositivos``.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aqui).

        Returns:
            ``DimensionesDispositivos`` con ``extras={N_MAX_DISP_X: v}``
            para cada defined name reconocido.
        """
        defined_names = getattr(wb, "defined_names", None)
        if defined_names is None:
            return DimensionesDispositivos()

        items: Any = (
            defined_names.items()
            if hasattr(defined_names, "items")
            else []
        )

        extras: dict[str, int] = {}
        for name, definition in items:
            if not isinstance(name, str):
                continue
            canonical = self._canonical_from_name(name)
            if canonical is None:
                continue
            value = _safe_int(_resolve_value(definition, wb))
            if value:
                extras[canonical] = value

        logger.debug(
            f"Parser[N_MAX]: {len(extras)} N_MAX canonicos"
        )
        return DimensionesDispositivos(extras=extras)


# ---------------------------------------------------------------------------
# Resolucion del valor de un DefinedName (privado al modulo).
# ---------------------------------------------------------------------------


def _resolve_value(definition: Any, workbook: Any) -> Any:
    """Lee el valor de un ``DefinedName`` resolviendo su hoja y celda.

    Returns:
        El valor de la celda referenciada o ``None`` si no se pudo
        resolver la hoja/celda.
    """
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
        destinations = getattr(definition, "destinations", None)
        if destinations is not None:
            dest = list(destinations)
            if dest:
                sheet_name, coord = dest[0]
                cell = workbook[sheet_name][coord]
                if isinstance(cell, tuple):
                    cell = cell[0][0] if isinstance(cell[0], tuple) else cell[0]
                return getattr(cell, "value", None)
        cell = sheet[cell_ref]
    except (KeyError, AttributeError, TypeError):
        return None
    return getattr(cell, "value", None)


__all__ = ["DimensionesParser"]
