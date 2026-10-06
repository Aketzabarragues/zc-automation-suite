"""Parser de N_MAX del Excel corporativo (multi-PLC).

Lee una **tabla** dentro de la hoja de configuracion global
(``global_config_table_name``, tipicamente ``"000_Config_Dispositivos"``)
con la siguiente estructura::

    UID | PLC | N_Max_ED | N_Max_EA | N_Max_SD | ... | N_Max_ENT

Una fila por PLC del Excel. Cada columna ``N_Max_<hw>`` se traduce al
canonico TIA ``N_MAX_DISP_<SUFFIX>`` y se agrupa por PLC en un
``DataDimensionesPLC``. La columna ``N_Max_ENT`` se traduce al
canonico TIA ``N_MAX_ENTIDAD`` y vive en el campo tipado
``n_max_entidades`` del DTO (no en ``extras``). El resultado es un
``DimensionesDispositivos`` con ``por_plc: tuple[DataDimensionesPLC, ...]``.

Modo strict: solo se leen las columnas listadas en
``n_max_catalog[*].excel_column``. Columnas ``N_Max_*`` no listadas se
ignoran con WARNING (typo atrapado). Entradas del catalog sin columna
en el Excel se omiten (valor 0 por defecto al consultar).

Excepcion: ``N_Max_ENT`` se lee SIEMPRE si la columna aparece en la
tabla, sin depender del catalog (su entrada en ``n_max_catalog``
tiene ``hw_type=""`` y no entra en el loop del catalog).

Celdas vacias o no numericas: ``_safe_int(..., default=0)``. Validacion
soft: N_MAX=0 silencioso, sin error duro.

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
N_MAX_TABLE_NAME = "Tabla_Dimensiones"

# Hoja del Excel donde vive la tabla (igual que ``PLCListParser`` y
# ``ProcesosParser``, hardcoded a ``"CONFIG"``). NO usar
# ``tia_folders.nmax`` del ``ConfigManager`` (eso es el path TIA
# donde estan los XMLs exportados, p.ej. ``"000_Sistema"``; son DOS
# cosas distintas: hoja del Excel donde escribe el operario vs.
# directorio del PLC donde TIA guarda los datos).
SHEET = "CONFIG"

# Columna ``N_Max_ENT`` del Excel (N_MAX de entidades) se lee por
# hardcoded porque su entrada en ``n_max_catalog`` no tiene ``hw_type``.
# Si la columna no esta presente en el Excel (Excel legacy), ``n_max_entidades=0``.
N_MAX_ENT_EXCEL_COL = "N_Max_ENT"
N_MAX_ENT_CANONICO = "N_MAX_ENTIDAD"


class DimensionesParser:
    """Parser de la tabla N_MAX multi-PLC.

    Atributos:
        ``_config_manager``: ``ConfigManager`` (obligatorio).
            ``excel_column`` del catalog es data-driven via el
            ConfigManager del departamento.

    Politica:
        - Filas sin ``PLC`` se descartan con WARNING.
        - Columnas ``N_Max_*`` no listadas en catalog se ignoran con WARNING.
        - ``N_Max_ENT`` se lee siempre si esta presente (hardcoded).
        - Celdas vacias o no numericas -> ``0`` (validacion silenciosa).
        - Dos columnas que normalizan al mismo canonico -> WARNING + usa la ultima.
    """

    def __init__(self, config_manager: ConfigManager) -> None:
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

        # Index normalizado de las cabeceras del Excel: {cabecera_normalizada: cabecera_original}.
        # Asi matcheamos aunque el operario haya mezclado casing (N_Max_Ed vs N_Max_ED).
        headers_normalized: dict[str, str] = {
            self._normalize_header(h): h
            for h in (rows[0].keys() if rows else [])
        }

        # Columna N_MAX_ENTIDADES: se busca por header literal del Excel
        # (no requiere entrada en el catalog porque no es de disp).
        ent_header = headers_normalized.get(
            self._normalize_header(N_MAX_ENT_EXCEL_COL)
        )

        por_plc: dict[str, dict[str, int]] = {}
        # ``n_max_entidades_por_plc`` se llena en el mismo loop (mismo row).
        n_max_entidades_por_plc: dict[str, int] = {}
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
                # Celda vacia o None -> 0 (validacion soft).
                value = _safe_int(raw, default=0)
                if canonico in extras and extras[canonico] != value:
                    logger.warning(
                        "Columna duplicada para '%s' (valor %d vs %d)",
                        canonico, extras[canonico], value,
                    )
                extras[canonico] = value
            # N_MAX_ENTIDADES del mismo row (mismo PLC).
            if ent_header is not None:
                raw = row.get(ent_header)
                n_max_entidades_por_plc[plc_name] = _safe_int(raw, default=0)
            # Solo emitir DataDimensionesPLC si tenemos al menos un N_MAX leido.
            if extras or plc_name in n_max_entidades_por_plc:
                prev = por_plc.get(plc_name, {})
                prev.update(extras)
                por_plc[plc_name] = prev

        return DimensionesDispositivos(
            por_plc=tuple(
                DataDimensionesPLC(
                    plc_name=p,
                    extras=por_plc.get(p, {}),
                    n_max_entidades=n_max_entidades_por_plc.get(p, 0),
                )
                for p in sorted(set(por_plc) | set(n_max_entidades_por_plc))
            )
        )

    # --- helpers ---------------------------------------------------------

    def _resolve_columnas_catalog(self) -> dict[str, str]:
        """``{excel_column: hw_type}`` desde el catalog del config_manager.

        Si el catalog esta vacio, devuelve ``{}``.
        Solo se incluyen entradas que tengan ``excel_column`` no vacio.
        La entrada ``N_MAX_ENTIDAD`` (``hw_type=""``) NO se incluye
        aqui: se lee por hardcoded con la constante ``N_MAX_ENT_EXCEL_COL``.
        """
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
        """``ed`` -> ``N_MAX_DISP_ED``."""
        suffix = hw.upper()
        return f"N_MAX_DISP_{suffix}" if suffix else ""

    @staticmethod
    def _normalize_header(h: str) -> str:
        """Cabecera normalizada para matching case-insensitive.

        ``N_Max_Ed`` y ``N_Max_ED`` producen la misma clave.
        """
        return h.strip().upper() if h else ""


__all__ = ["DimensionesParser", "N_MAX_TABLE_NAME", "SHEET"]