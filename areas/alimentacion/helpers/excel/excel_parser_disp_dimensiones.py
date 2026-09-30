"""Parser de N_MAX del Excel corporativo (multi-PLC, sept-2026).

Lee una **tabla** dentro de la hoja de configuracion global
(``global_config_table_name``, tipicamente ``"000_Config_Dispositivos"``)
con la siguiente estructura::

    UID | PLC | N_Max_ED | N_Max_EA | N_Max_SD | ... | N_Max_M_TQ_AE

Una fila por PLC del Excel. Cada columna ``N_Max_<hw>`` se traduce al
canonico TIA ``N_MAX_DISP_<SUFFIX>`` y se agrupa por PLC en un
``DataDimensionesPLC``. El resultado es un ``DimensionesDispositivos``
con ``por_plc: tuple[DataDimensionesPLC, ...]``.

Modo strict: solo se leen las columnas listadas en
``n_max_catalog[*].excel_column``. Columnas ``N_Max_*`` no listadas se
ignoran con WARNING (typo atrapado). Entradas del catalog sin columna
en el Excel se omiten (valor 0 por defecto al consultar).

Celdas vacias o no numericas: ``_safe_int(..., default=0)``. Validacion
soft (D9 del plan): N_MAX=0 silencioso, sin error duro.

Restriccion arquitectonica: este modulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging
from typing import Any

from openpyxl import Workbook

from areas.alimentacion.data.data_dimensiones import (
    DataDimensionesPLC,
    DimensionesDispositivos,
)
from areas.alimentacion.helpers.excel._excel_helpers import (
    _safe_int,
    extract_list_object_rows,
)
from core.infrastructure.config.config_manager import ConfigManager


logger = logging.getLogger(__name__)


# Nombre literal de la tabla N_MAX dentro de la hoja de configuracion.
# Si la tabla no existe o el nombre difiere, el parser devuelve
# ``DimensionesDispositivos`` con ``por_plc=()`` (estado vacio, no
# rompe la carga).
N_MAX_TABLE_NAME = "Tabla_Dispositivos"

# Hoja del Excel donde vive la tabla (igual que ``PLCListParser`` y
# ``ProcesosParser``, hardcoded a ``"CONFIG"``). NO usar
# ``tia_folders.nmax`` del ``ConfigManager`` (eso es el path TIA
# donde estan los XMLs exportados, p.ej. ``"000_Sistema"``; son DOS
# cosas distintas: hoja del Excel donde escribe el operario vs.
# directorio del PLC donde TIA guarda los datos).
SHEET = "CONFIG"


class DimensionesParser:
    """Parser de la tabla N_MAX multi-PLC.

    Atributos:
        ``_config_manager``: ``ConfigManager`` opcional. Si se pasa,
            ``excel_column`` del catalog es data-driven. Si no, fallback
            a derivar ``N_Max_<HW>`` desde ``hw_type``.

    Politica:
        - Filas sin ``PLC`` se descartan con WARNING.
        - Columnas ``N_Max_*`` no listadas en catalog se ignoran con WARNING.
        - Celdas vacias o no numericas -> ``0`` (validacion silenciosa).
        - Dos columnas que normalizan al mismo canonico -> WARNING + usa la ultima.
    """

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self._config_manager = config_manager

    def extraer(self, wb: Workbook) -> DimensionesDispositivos:
        """Lee la tabla N_MAX y devuelve un ``DimensionesDispositivos``.

        Args:
            wb: workbook de openpyxl ya abierto (no se cierra aqui).

        Returns:
            ``DimensionesDispositivos`` con un ``DataDimensionesPLC`` por
            PLC del Excel. Vacio si la tabla no existe.
        """
        # Resolver la hoja: hardcoded a ``"CONFIG"`` (mismo patron que
        # ``PLCListParser`` y ``ProcesosParser``).
        rows = extract_list_object_rows(wb, SHEET, N_MAX_TABLE_NAME)
        if not rows:
            # Tabla no existe o esta vacia: no es error, es estado normal
            # si el operario aun no ha creado la tabla. Emitimos un debug
            # y devolvemos vacio.
            logger.debug(
                "Tabla N_MAX '%s' no encontrada en hoja '%s': "
                "devolviendo contenedor vacio",
                N_MAX_TABLE_NAME, SHEET,
            )
            return DimensionesDispositivos()

        # Columnas a leer: las listadas en n_max_catalog.excel_column.
        columnas_catalog: dict[str, str] = self._resolve_columnas_catalog()
        # Map: excel_column -> nombre canonico N_MAX_DISP_<X>
        excel_to_canonico: dict[str, str] = {}
        for excel_col, hw in columnas_catalog.items():
            canonico = self._canonical_from_hw(hw)
            if canonico:
                excel_to_canonico[excel_col] = canonico
        # Fallback: si no hay config_manager, derivar N_Max_<X> de hw_type
        # de las entradas del catalog. Si tampoco hay catalog,
        # no leemos nada (modo strict sin fallback).
        if not excel_to_canonico and self._config_manager is None:
            logger.debug(
                "DimensionesParser sin config_manager y sin columnas del "
                "catalog: ninguna columna N_Max_* se leera"
            )
            return DimensionesDispositivos()

        # Index normalizado de las cabeceras del Excel: {cabecera_normalizada: cabecera_original}.
        # Asi matcheamos aunque el operario haya mezclado casing (N_Max_Ed vs N_Max_ED).
        headers_normalized: dict[str, str] = {
            self._normalize_header(h): h
            for h in (rows[0].keys() if rows else [])
        }

        por_plc: dict[str, dict[str, int]] = {}
        for row in rows:
            plc_name = str(row.get("PLC") or "").strip()
            if not plc_name:
                logger.warning("Fila N_MAX sin PLC: descartada")
                continue
            extras: dict[str, int] = {}
            for excel_col, canonico in excel_to_canonico.items():
                # Buscamos la cabecera del Excel que matchee ``excel_col``
                # ignorando casing: si el catalog dice ``N_Max_ED`` y
                # el Excel tiene ``N_Max_Ed``, los matcheamos.
                excel_header = headers_normalized.get(
                    self._normalize_header(excel_col)
                )
                if excel_header is None:
                    continue  # columna no presente en este Excel
                raw = row.get(excel_header)
                # Celda vacia o None -> 0 (validacion soft, D9 del plan).
                value = _safe_int(raw, default=0)
                if canonico in extras and extras[canonico] != value:
                    logger.warning(
                        "Columna duplicada para '%s' (valor %d vs %d)",
                        canonico, extras[canonico], value,
                    )
                extras[canonico] = value
            # Solo emitir DataDimensionesPLC si tenemos al menos un N_MAX leido.
            if extras:
                prev = por_plc.get(plc_name, {})
                prev.update(extras)
                por_plc[plc_name] = prev

        return DimensionesDispositivos(
            por_plc=tuple(
                DataDimensionesPLC(plc_name=p, extras=e)
                for p, e in por_plc.items()
            )
        )

    # --- helpers ---------------------------------------------------------

    def _resolve_columnas_catalog(self) -> dict[str, str]:
        """``{excel_column: hw_type}`` desde el catalog del config_manager.

        Si no hay config_manager o el catalog esta vacio, devuelve ``{}``.
        Solo se incluyen entradas que tengan ``excel_column`` no vacio.
        """
        if self._config_manager is None:
            return {}
        result: dict[str, str] = {}
        for name in self._config_manager.list_nmax_active():
            entry = self._config_manager.get_nmax_entry(name)
            if entry is None:
                continue
            excel_col = entry.get("excel_column", "").strip()
            hw = entry.get("hw_type", "").strip()
            if excel_col and hw:
                result[excel_col] = hw
        return result

    @staticmethod
    def _canonical_from_hw(hw: str) -> str:
        """``ed`` -> ``N_MAX_DISP_ED`` (mismo patron que legacy)."""
        suffix = hw.upper()
        return f"N_MAX_DISP_{suffix}" if suffix else ""

    @staticmethod
    def _normalize_header(h: str) -> str:
        """Cabecera normalizada para matching case-insensitive.

        ``N_Max_Ed`` y ``N_Max_ED`` producen la misma clave.
        """
        return h.strip().upper() if h else ""


__all__ = ["DimensionesParser", "N_MAX_TABLE_NAME", "SHEET"]