"""Gestor de configuración multi-departamento.

Lee ``infrastructure/config.json`` y expone el mapeo entre tipos de
dispositivo del departamento activo y nombres reales de tablas / DBs /
carpetas dentro del PLC de TIA Portal. Esto evita hardcodear nombres
como ``"000_Config_Dispositivos"`` o ``"2000_Disp_ED"`` en los casos
de uso.

Estructura del ``config.json``:

    {
      "departments": {
        "alimentacion": {
          "global_config_table_name": "000_Config_Dispositivos",
          "tia_folders": {
            "proceso":      "003_Procesos",
            "dispositivos": "2000_Dispositivos",
            "nmax":         "000_Sistema"
          },
          "n_max_catalog": [
            { "name": "N_MAX_DISP_ED", "excel_named_range": "Num_Disp_ED",
              "hw_type": "ed", "plc_tag_table": "2000_Disp_ED", "comment": "..." },
            ...
          ],
          "pending_nmax":        [ "N_MAX_DISP_FF", ... ],
          "pending_dispositivos":{ "sd": {...}, ... },
          "Dispositivos": {
            "<key>": {
              "db_name":       "DB...",
              "db_array_name": "...",
              "tag_table":     "2000_Disp_...",
              "config_table":  "000_Config_Dispositivos"
            },
            ...
          }
        },
        ...
      }
    }

Tipos de dispositivo del departamento ``alimentacion`` configurados
actualmente: ``ed``, ``ea``, ``sa``, ``v``, ``m``, ``m_vf``.

Tipos legacy pendientes de portar explícitamente (documentados pero
NO configurados, viven en ``pending_dispositivos``):
``sd``, ``m_sina``, ``tq``, ``tq_ae`` (los N_MAX asociados viven en
``pending_nmax``).

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_logger: logging.Logger = logging.getLogger(f"{__name__}.ConfigManager")


# ── Defaults defensivos (compatibilidad con configs mínimos) ────────
_DEFAULT_DEPARTMENT = "alimentacion"
_DEFAULT_GLOBAL_CONFIG_TABLE_NAME = "000_Config_Dispositivos"
_DEFAULT_TIA_FOLDER_PROCESO = "003_Procesos"
_DEFAULT_TIA_FOLDER_DISPOSITIVOS = "2000_Dispositivos"
_DEFAULT_TIA_FOLDER_NMAX = "000_Sistema"

# Catálogo de N_MAX por defecto (se usa cuando el JSON no incluye
# ``n_max_catalog``). Mantiene back-compat 1 release con configs
# mínimos que aún no migraron a la versión con ``n_max_catalog``.
_DEFAULT_NMAX_CATALOG: list[dict[str, str]] = [
    {"name": "N_MAX_DISP_ED",   "excel_named_range": "Num_Disp_ED",   "hw_type": "ed"},
    {"name": "N_MAX_DISP_EA",   "excel_named_range": "Num_Disp_EA",   "hw_type": "ea"},
    {"name": "N_MAX_DISP_SA",   "excel_named_range": "Num_Disp_SA",   "hw_type": "sa"},
    {"name": "N_MAX_DISP_V",    "excel_named_range": "Num_Disp_V",    "hw_type": "v"},
    {"name": "N_MAX_DISP_M",    "excel_named_range": "Num_Disp_M",    "hw_type": "m"},
    {"name": "N_MAX_DISP_M_VF", "excel_named_range": "Num_Disp_M_VF", "hw_type": "m_vf"},
]


@dataclass(frozen=True)
class DispositivoTIAConfig:
    """Configuración TIA de un tipo de dispositivo del departamento activo.

    Attributes:
        key:              Identificador lógico (``"ed"``, ``"ea"``, etc.).
        db_name:          Nombre del DB (ej. ``"DB2000_ED"``).
        db_array_name:    Nombre del array dentro del DB (ej. ``"ED"``).
        tag_table:        Nombre de la PlcTagTable del dispositivo
                          (ej. ``"2000_Disp_ED"``).
        config_table:     Nombre de la PlcTagTable donde residen las
                          PlcUserConstant N_MAX (típicamente
                          ``"000_Config_Dispositivos"``).
        config_constant:  Nombre de la PlcUserConstant N_MAX de este
                          tipo (ej. ``"N_MAX_DISP_ED"``). Heredado del
                          legacy ``HardwareTIAConfig.config_constant``;
                          permite vincular un tipo de dispositivo con su
                          N_MAX sin tener que conocer el nombre a priori.
    """

    key: str
    db_name: str
    db_array_name: str
    tag_table: str
    config_table: str
    config_constant: str = ""  # legacy. Si vacío, usar heurístico ``N_MAX_<KEY>``.


class ConfigManager:
    """Carga ``infrastructure/config.json`` y expone el mapeo del
    departamento activo.

    Args:
        config_path: Ruta al archivo JSON de configuración.
        department:  Nombre del departamento a resolver. Por defecto
                     ``"alimentacion"``. Debe existir como clave bajo
                     ``departments`` en el JSON; si no, se loggea un
                     warning y se retorna el primer departamento
                     disponible (forward-compatible).

    API:
      - **Tabla global N_MAX**: ``get_global_config_table_name()``.
      - **Catálogo N_MAX** (data-driven):
        ``list_nmax_active()``, ``get_nmax_entry(name)``,
        ``get_excel_named_range_for_nmax(name)``,
        ``get_nmax_for_hw_type(hw)``, ``list_nmax_pending()``.
      - **Configuración por tipo de dispositivo**:
        ``get_dispositivo_config(key)`` → ``DispositivoTIAConfig | None``.
        Alias deprecado ``get_hardware_config`` (conservado una release).
      - **Getters específicos** (None si el tipo no existe):
        ``get_tag_table_name(key)``, ``get_db_name(key)``,
        ``get_db_array_name(key)``.
      - **Resolución cross-capa** (data-driven):
        ``get_app_state_attr_for(hw)`` (→ ``"dispositivos_<hw>"``),
        ``get_excel_target_for(hw)`` (→ ``{sheet, table, canonical}``).
      - **Carpetas TIA**: ``get_tia_folder_proceso()``,
        ``get_tia_folder_dispositivos()``, ``get_tia_folder_nmax()``.
      - **Listado**: ``list_keys()`` (alias deprecado ``list_hw_types``),
        ``list_hw_types_active()`` (recomendado),
        ``list_hw_types_pending()``.

    Política de fallback: si una clave no existe, se retorna el valor
    por defecto (configurable globalmente) o ``None`` en getters de
    tipo específico, con un ``logger.warning`` (NO raise).
    """

    # Aliases para mantener back-compat una release.
    HardwareTIAConfig = DispositivoTIAConfig  # type: ignore[assignment]

    def __init__(
        self,
        config_path: str | Path = "infrastructure/config.json",
        department: str = _DEFAULT_DEPARTMENT,
    ) -> None:
        self._config_path = Path(config_path)
        self._department = department
        self._full_config: dict[str, Any] = self._load_config()
        self._department_config: dict[str, Any] = self._resolve_department()
        # Bandera de "warning ya emitido" — se inicializa ANTES de
        # invocar ``_index_nmax_catalog`` porque este puede necesitarla.
        self._warned_missing_catalog: bool = False
        # Cache de resoluciones costosas.
        self._nmax_by_name: dict[str, dict[str, str]] = self._index_nmax_catalog()
        self._nmax_by_hw: dict[str, dict[str, str]] = {
            entry["hw_type"]: entry
            for entry in self._nmax_by_name.values()
            if entry.get("hw_type")
        }

    # ── Carga ───────────────────────────────────────────────────────────

    def _load_config(self) -> dict[str, Any]:
        """Carga el archivo JSON de configuración.

        Raises:
            FileNotFoundError: Si el archivo no existe.
            json.JSONDecodeError: Si el contenido no es JSON válido.
        """
        if not self._config_path.is_file():
            raise FileNotFoundError(
                f"No se encontró el archivo de configuración: "
                f"'{self._config_path}'"
            )
        with self._config_path.open("r", encoding="utf-8") as fh:
            loaded: dict[str, Any] = json.load(fh)
            return loaded

    def _resolve_department(self) -> dict[str, Any]:
        """Resuelve la sub-config del departamento activo.

        Si el departamento solicitado no existe, se loggea un warning
        y se retorna el primer departamento disponible (forward-
        compatible con configs multi-departamento incompletas).
        """
        departments = self._full_config.get("departments", {})
        if not departments:
            _logger.warning(
                "El config no tiene bloque 'departments'. "
                "Se retorna {} (todos los getters usarán defaults)."
            )
            return {}

        if self._department in departments:
            return departments[self._department]

        first = next(iter(departments.keys()))
        _logger.warning(
            f"Departamento '{self._department}' no encontrado en "
            f"config.json. Departamentos disponibles: "
            f"{list(departments.keys())}. Se usa '{first}' como fallback."
        )
        self._department = first
        return departments[first]

    def _index_nmax_catalog(self) -> dict[str, dict[str, str]]:
        """Indexa ``n_max_catalog`` por ``name``. Aplica fallback defensivo.

        Si la clave ``n_max_catalog`` no existe en el JSON (configs
        mínimos aún no migrados), se usa ``_DEFAULT_NMAX_CATALOG`` y
        se loggea un warning una sola vez por instancia.
        """
        raw = self._department_config.get("n_max_catalog")
        if raw is None:
            if not self._warned_missing_catalog:
                _logger.warning(
                    "Bloque 'n_max_catalog' ausente en config.json; se "
                    "usa el catálogo por defecto (6 N_MAX legacy). "
                    "Migrar el config cuando sea posible."
                )
                self._warned_missing_catalog = True
            raw = _DEFAULT_NMAX_CATALOG
        indexed: dict[str, dict[str, str]] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            indexed[name] = {
                "name":              name,
                "excel_named_range": str(entry.get("excel_named_range", "")),
                "hw_type":           str(entry.get("hw_type", "")),
                "plc_tag_table":     str(entry.get("plc_tag_table", "")),
                "comment":           str(entry.get("comment", "")),
            }
        return indexed

    # ── Departamento activo ─────────────────────────────────────────────

    @property
    def department(self) -> str:
        """Nombre del departamento actualmente resuelto."""
        return self._department

    # ── Tabla global N_MAX ──────────────────────────────────────────────

    def get_global_config_table_name(self) -> str:
        """Devuelve el nombre de la tabla de configuración global (N_MAX).

        Si la clave ``global_config_table_name`` no existe en el bloque
        del departamento, retorna ``"000_Config_Dispositivos"`` como
        fallback defensivo.
        """
        return str(
            self._department_config.get(
                "global_config_table_name",
                _DEFAULT_GLOBAL_CONFIG_TABLE_NAME,
            )
        )

    # ── Catálogo N_MAX (data-driven) ────────────────────────────────────

    def list_nmax_active(self) -> list[str]:
        """Lista los nombres (``"N_MAX_DISP_ED"``…) del catálogo activo.

        El orden es el de declaración en ``n_max_catalog`` del config.
        Si el bloque no existe, se usa el catálogo legacy (6 entradas,
        mismo orden histórico: ``ED, EA, SA, V, M, M_VF``) preservando
        el contrato de orden de los tests.
        """
        return list(self._nmax_by_name.keys())

    def get_nmax_entry(self, name: str) -> dict[str, str] | None:
        """Devuelve la entrada del catálogo para ``name`` o ``None``.

        El dict devuelto tiene las claves ``name``, ``excel_named_range``,
        ``hw_type``, ``plc_tag_table``, ``comment``. Es una copia
        superficial para evitar mutaciones accidentales.
        """
        entry = self._nmax_by_name.get(name)
        return dict(entry) if entry is not None else None

    def get_excel_named_range_for_nmax(self, name: str) -> str | None:
        """Devuelve el named range del Excel que alimenta ``name`` o ``None``.

        Útil para que ``AlimentacionExcelParser`` o el caso de uso de
        carga de dimensiones sepa qué celda leer del Excel corporativo
        para una N_MAX concreta.
        """
        entry = self._nmax_by_name.get(name)
        if entry is None:
            return None
        v = entry.get("excel_named_range", "")
        return v or None

    def get_nmax_for_hw_type(self, hw_type: str) -> str | None:
        """Devuelve el nombre N_MAX asociado a ``hw_type`` o ``None``.

        Recorrido inverso de ``n_max_catalog`` (hw_type → name).
        """
        entry = self._nmax_by_hw.get(hw_type)
        return entry["name"] if entry else None

    def list_nmax_pending(self) -> list[str]:
        """Lista los N_MAX declarados en ``pending_nmax`` (aún no activos)."""
        raw = self._department_config.get("pending_nmax", [])
        if not isinstance(raw, list):
            return []
        return [str(x) for x in raw if isinstance(x, str) and x]

    # ── Configuración por tipo de dispositivo ──────────────────────────

    def get_dispositivo_config(self, key: str) -> DispositivoTIAConfig | None:
        """Devuelve la configuración TIA completa de un tipo de dispositivo.

        Args:
            key: Identificador (``"ed"``, ``"ea"``, ``"sa"``, ``"v"``,
                 ``"m"``, ``"m_vf"``).

        Returns:
            ``DispositivoTIAConfig`` con los 6 campos (5 legacy +
            ``config_constant``), o ``None`` si el tipo no existe.
            Loggea un warning en el segundo caso (NO lanza excepción:
            forward-compatible con tipos futuros aún no configurados).
        """
        dispositivos = self._department_config.get("Dispositivos", {})
        d = dispositivos.get(key)
        if d is None:
            _logger.warning(
                f"Tipo de dispositivo '{key}' no encontrado en "
                f"config.json (departamento '{self._department}', "
                f"sección 'Dispositivos'). Claves disponibles: "
                f"{list(dispositivos.keys())}. Se retorna None."
            )
            return None
        try:
            config_constant = self._resolve_config_constant(key, d)
            return DispositivoTIAConfig(
                key=key,
                db_name=str(d.get("db_name", "")),
                db_array_name=str(d.get("db_array_name", "")),
                tag_table=str(d.get("tag_table", "")),
                config_table=str(d.get("config_table", "")),
                config_constant=config_constant,
            )
        except Exception as e:
            _logger.warning(
                f"Error parseando config de '{key}': {e}. Se retorna None."
            )
            return None

    def _resolve_config_constant(self, key: str, d: dict[str, Any]) -> str:
        """Resuelve el ``config_constant`` para un tipo de dispositivo.

        Orden de prioridad:
          1. Override explícito en ``d["config_constant"]``.
          2. Entrada del ``n_max_catalog`` con ``hw_type == key``.
          3. Heurístico legacy: ``f"N_MAX_{key.upper()}"``.
        """
        override = d.get("config_constant")
        if isinstance(override, str) and override.strip():
            return override.strip()
        nmax_for_hw = self.get_nmax_for_hw_type(key)
        if nmax_for_hw:
            return nmax_for_hw
        return f"N_MAX_{key.upper()}"

    # Alias deprecado (back-compat una release).
    def get_hardware_config(self, key: str) -> DispositivoTIAConfig | None:
        """**DEPRECADO** — usa ``get_dispositivo_config``. Conservado
        una release por compat con código externo."""
        return self.get_dispositivo_config(key)

    def get_tag_table_name(self, key: str) -> str | None:
        """Devuelve el nombre de la PlcTagTable del dispositivo o None."""
        cfg = self.get_dispositivo_config(key)
        return cfg.tag_table if cfg else None

    def get_db_name(self, key: str) -> str | None:
        """Devuelve el nombre del DB (ej. ``"DB2000_ED"``) o None."""
        cfg = self.get_dispositivo_config(key)
        return cfg.db_name if cfg else None

    def get_db_array_name(self, key: str) -> str | None:
        """Devuelve el nombre del array (ej. ``"ED"``) o None."""
        cfg = self.get_dispositivo_config(key)
        return cfg.db_array_name if cfg else None

    def list_keys(self) -> list[str]:
        """Lista los tipos de dispositivo configurados en el departamento activo.

        Returns:
            Lista de claves del bloque ``Dispositivos`` del config
            (ej. ``["ed", "ea", "sa", "v", "m", "m_vf"]``). Vacía si
            la sección no existe.
        """
        dispositivos = self._department_config.get("Dispositivos", {})
        return list(dispositivos.keys())

    # Alias deprecado (back-compat una release).
    def list_hw_types(self) -> list[str]:
        """**DEPRECADO** — usa ``list_keys``. Conservado una release."""
        return self.list_keys()

    def list_hw_types_active(self) -> list[str]:
        """Sinónimo semántico de ``list_keys``. Recomendado para código nuevo."""
        return self.list_keys()

    def list_hw_types_pending(self) -> list[str]:
        """Lista los tipos declarados en ``pending_dispositivos``."""
        raw = self._department_config.get("pending_dispositivos", {})
        if not isinstance(raw, dict):
            return []
        return [str(k) for k in raw.keys() if k]

    # ── Resolvedor cross-capa: Dispositivo ⇄ AppState ──────────────────

    def get_app_state_attr_for(self, hw_type: str) -> str | None:
        """Devuelve el nombre del atributo ``AppState`` para ``hw_type``.

        Convensión determinista: ``f"dispositivos_{hw_type}"`` (p.ej.
        ``"ed"`` → ``"dispositivos_ed"``). Si el bloque ``Dispositivos``
        del config define un override en ``app_state_attr``, se respeta.
        Devuelve ``None`` si ``hw_type`` no está configurado.
        """
        d = self._department_config.get("Dispositivos", {}).get(hw_type)
        if d is None:
            return None
        override = d.get("app_state_attr")
        if isinstance(override, str) and override.strip():
            return override.strip()
        return f"dispositivos_{hw_type}"

    # ── Resolvedor cross-capa: Dispositivo ⇄ Excel ──────────────────────

    def get_excel_target_for(self, hw_type: str) -> dict[str, str] | None:
        """Devuelve la metadata de la ``ListObject`` del Excel para ``hw_type``.

        Shape del dict devuelto:
          ``{"sheet": "DISP_ED", "table": "Tabla_Disp_ED",
             "canonical": "DispED"}``

        - Override explícito: ``d["excel_target"] = {sheet, table, canonical}``.
        - Convensión: sheet ``f"DISP_{hw_type.upper()}"``, table
          ``f"Tabla_Disp_{hw_type.upper()}"``, canonical
          ``f"Disp{hw_type.replace('_', '').upper().replace('V', 'V')}"``
          (mantiene ``DispED``, ``DispM_VF`` → ``DispM_VF``).

        Devuelve ``None`` si ``hw_type`` no está configurado.
        """
        d = self._department_config.get("Dispositivos", {}).get(hw_type)
        if d is None:
            return None
        override = d.get("excel_target")
        if isinstance(override, dict) and override:
            return {
                "sheet":     str(override.get("sheet", f"DISP_{hw_type.upper()}")),
                "table":     str(override.get("table", f"Tabla_Disp_{hw_type.upper()}")),
                "canonical": str(override.get("canonical", _canonical_default(hw_type))),
            }
        return {
            "sheet":     f"DISP_{hw_type.upper()}",
            "table":     f"Tabla_Disp_{hw_type.upper()}",
            "canonical": _canonical_default(hw_type),
        }

    # ── Carpetas TIA ────────────────────────────────────────────────────

    def get_tia_folder_proceso(self) -> str:
        """Ruta de la carpeta de proceso en TIA (default: ``"003_Procesos"``)."""
        folders = self._department_config.get("tia_folders", {})
        return str(folders.get("proceso", _DEFAULT_TIA_FOLDER_PROCESO))

    def get_tia_folder_dispositivos(self) -> str:
        """Ruta de la carpeta de dispositivos en TIA (default: ``"2000_Dispositivos"``)."""
        folders = self._department_config.get("tia_folders", {})
        return str(folders.get("dispositivos", _DEFAULT_TIA_FOLDER_DISPOSITIVOS))

    def get_tia_folder_nmax(self) -> str:
        """Ruta de la carpeta TIA donde reside la tabla de N_MAX.

        Por defecto ``"000_Sistema"``: la tabla
        ``000_Config_Dispositivos`` (constantes N_MAX) vive dentro de
        esa carpeta según la jerarquía confirmada en el PLC real
        (ver ``.build_cache/base/tags/000_Sistema/``).

        El sync unificado compone la ruta final del XML como
        ``f"{get_tia_folder_nmax()}/{get_global_config_table_name()}.xml"``
        → ``000_Sistema/000_Config_Dispositivos.xml``.
        """
        folders = self._department_config.get("tia_folders", {})
        return str(folders.get("nmax", _DEFAULT_TIA_FOLDER_NMAX))


# ── Helpers puros (a nivel de módulo) ───────────────────────────────


def _canonical_default(hw_type: str) -> str:
    """Convensión canónica para ``canonical`` de un ``hw_type``.

    Reglas de transformación:
      - ``"ed"``     → ``"DispED"``
      - ``"ea"``     → ``"DispEA"``
      - ``"m_vf"``   → ``"DispM_VF"`` (preserva el guion bajo)
      - ``"m_sina"`` → ``"DispM_SINA"`` (preserva + mayúsculas)
    """
    parts = hw_type.split("_")
    return "Disp" + "_".join(p.upper() for p in parts)


__all__ = ["ConfigManager", "DispositivoTIAConfig"]
