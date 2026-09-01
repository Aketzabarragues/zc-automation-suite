"""Gestor de configuración multi-departamento (genérico).

Lee ``infrastructure/config.json`` y expone el mapeo entre tipos de
dispositivo del departamento activo y nombres reales de tablas / DBs /
carpetas dentro del PLC de TIA Portal. Esto evita hardcodear nombres
como ``"000_Config_Dispositivos"`` o ``"2000_Disp_ED"`` en los casos
de uso.

Este módulo es **genérico** (Plan: Bounded Contexts — PR 1):

  - NO tiene defaults hardcoded de un área concreta (alimentación).
  - Si una clave no existe en el JSON: warning + fallback genérico
    (``""`` o ``[]`` según el caso).
  - Las áreas aportan sus defaults específicos vía
    ``AreaSpec.contributes_config_defaults`` (cableado en PR 2).

Estructura del ``config.json``:

    {
      "departments": {
        "<area_id>": {
          "global_config_table_name": "...",
          "tia_folders": { "proceso": "...", "dispositivos": "...", "nmax": "..." },
          "n_max_catalog":       [ { "name": "N_MAX_...", "hw_type": "..." }, ... ],
          "pending_nmax":        [ "N_MAX_...", ... ],
          "pending_dispositivos":{ "<hw>": {...}, ... },
          "Dispositivos":        { "<key>": { "db_name": "..." }, ... }
        },
        ...
      }
    }

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_logger: logging.Logger = logging.getLogger(f"{__name__}.ConfigManager")


# ── Fallbacks genéricos (PR 1: ya no hay defaults de alimentación) ─────
# Antes de PR 1, este módulo exponía ``_DEFAULT_DEPARTMENT =
# "alimentacion"`` y ``_DEFAULT_NMAX_CATALOG`` con los 6 N_MAX legacy.
# Ahora esos defaults se aportan por el área "alimentación" vía
# ``contributes_config_defaults`` (PR 2). Si en el JSON no está la
# clave, el getter retorna un valor vacío y loggea un warning.
_DEFAULT_GLOBAL_CONFIG_TABLE_NAME = ""        # antes "000_Config_Dispositivos"
_DEFAULT_TIA_FOLDER_PROCESO = ""              # antes "003_Procesos"
_DEFAULT_TIA_FOLDER_DISPOSITIVOS = ""         # antes "2000_Dispositivos"
_DEFAULT_TIA_FOLDER_NMAX = ""                 # antes "000_Sistema"


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
                          PlcUserConstant N_MAX.
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
        department:  Nombre del departamento a resolver. Si es ``""`` o
                     el departamento no existe, se usa el primer
                     departamento disponible (forward-compatible con
                     configs multi-área incompletas). Antes de PR 1
                     el default era ``"alimentacion"``; ahora es
                     cadena vacía → primer departamento disponible.

    API:
      - **Tabla global N_MAX**: ``get_global_config_table_name()``.
      - **Catálogo N_MAX** (data-driven):
        ``list_nmax_active()``, ``get_nmax_entry(name)``,
        ``get_excel_named_range_for_nmax(name)``,
        ``get_nmax_for_hw_type(hw)``, ``list_nmax_pending()``.
      - **Configuración por tipo de dispositivo**:
        ``get_dispositivo_config(key)`` → ``DispositivoTIAConfig | None``.
      - **Getters específicos** (None si el tipo no existe):
        ``get_tag_table_name(key)``, ``get_db_name(key)``,
        ``get_db_array_name(key)``.
      - **Resolución cross-capa** (data-driven):
        ``get_app_state_attr_for(hw)`` (→ ``"dispositivos_<hw>"``),
        ``get_excel_target_for(hw)`` (→ ``{sheet, table, canonical}``).
      - **Carpetas TIA**: ``get_tia_folder_proceso()``,
        ``get_tia_folder_dispositivos()``, ``get_tia_folder_nmax()``.
      - **Listado**: ``list_keys()``,
        ``list_hw_types_active()`` (recomendado),
        ``list_hw_types_pending()``.
      - **Defaults por área (PR 1)**: ``apply_defaults(dept_cfg)`` —
        delega en las áreas registradas para rellenar claves
        ausentes. Es no-op si no hay áreas registradas (caso actual
        antes de PR 2).

    Política de fallback: si una clave no existe, se retorna el valor
    por defecto (cadena vacía o ``[]``) con un ``logger.warning``
    (NO raise).
    """

    def __init__(
        self,
        config_path: str | Path = "infrastructure/config.json",
        department: str = "",
    ) -> None:
        # ── Resolución frozen-aware ───────────────────────────────────
        # En modo empaquetado (PyInstaller --onefile), el CWD del
        # proceso es la carpeta desde la que el operario ejecuta el
        # .exe (típicamente ``%USERPROFILE%\Desktop``), NO el repo.
        # El ``config.json`` bundleado vive en ``sys._MEIPASS``. Si
        # lo encontramos allí, lo preferimos sobre cualquier ruta
        # relativa a CWD: así el .exe es "copy & run" sin requerir
        # un ``config.json`` adyacente. En modo dev, este bloque es
        # no-op (sys.frozen es False).
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                frozen_cfg = Path(meipass) / "infrastructure" / "config.json"
                if frozen_cfg.is_file():
                    config_path = frozen_cfg

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

        Si el departamento solicitado no existe (o es ``""``), se
        loggea un warning y se retorna el primer departamento
        disponible (forward-compatible con configs multi-departamento
        incompletas). Si no hay departamentos, retorna ``{}``.
        """
        departments = self._full_config.get("departments", {})
        if not departments:
            _logger.warning(
                "El config no tiene bloque 'departments'. "
                "Se retorna {} (todos los getters usarán defaults vacíos)."
            )
            return {}

        if self._department and self._department in departments:
            return departments[self._department]

        first = next(iter(departments.keys()))
        if not self._department:
            _logger.info(
                f"No se especificó departamento; se usa el primero "
                f"disponible: '{first}'."
            )
        else:
            _logger.warning(
                f"Departamento '{self._department}' no encontrado en "
                f"config.json. Departamentos disponibles: "
                f"{list(departments.keys())}. Se usa '{first}' como fallback."
            )
        self._department = first
        return departments[first]

    def get_departments_config(self) -> dict[str, dict[str, Any]]:
        """Devuelve el bloque ``departments`` completo del config.

        Counterpart público de ``_resolve_department`` (que solo
        devuelve la sub-config del departamento activo). Usado por
        ``ListAreasUseCase`` para iterar TODOS los departamentos
        declarados, no solo el activo.

        Returns:
            Dict ``{dept_id: dept_subconfig}`` con todos los
            departamentos. Vacío si el config no tiene bloque
            ``departments``. Nunca retorna ``None``.
        """
        departments = self._full_config.get("departments", {})
        if not isinstance(departments, dict):
            return {}
        return departments

    def _index_nmax_catalog(self) -> dict[str, dict[str, str]]:
        """Indexa ``n_max_catalog`` por ``name``.

        Si la clave ``n_max_catalog`` no existe en el JSON, retorna
        ``{}`` (genérico, vacío) y se loggea un warning una sola vez
        por instancia. Antes de PR 1, retornaba los 6 N_MAX legacy
        como fallback defensivo; ese comportamiento pasa al área
        "alimentación" vía ``contributes_config_defaults`` (PR 2).
        """
        raw = self._department_config.get("n_max_catalog")
        if raw is None:
            if not self._warned_missing_catalog:
                _logger.warning(
                    "Bloque 'n_max_catalog' ausente en config.json; "
                    "el catálogo queda vacío (genérico). El área "
                    "activa puede aportar defaults vía "
                    "contributes_config_defaults (PR 2)."
                )
                self._warned_missing_catalog = True
            raw = []
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

    def apply_defaults(self, dept_cfg: dict[str, Any] | None = None) -> None:
        """Hook PR 1+2: delega en las áreas registradas para rellenar
        claves ausentes en la sub-config del departamento activo.

        Recorre ``AreaRegistry.discover().all()`` y, para cada
        ``AreaSpec`` con ``contributes_config_defaults`` no nulo, la
        invoca pasando ``(dept_cfg, dept_id)``. El callable del área
        muta ``dept_cfg`` in-place para añadir las claves que falten.

        Detección de firma (PR 2): los ``contributes_config_defaults``
        se invocan con la firma nueva ``(dept_cfg, dept_id)``. Por
        back-compat, si un callable solo acepta ``(dept_cfg)``
        (p. ej. tests internos que mockean el ``AreaSpec``), se
        llama sin ``dept_id`` usando ``inspect.signature``.

        Tras invocar todos los callbacks, **re-indexa** los caches
        internos (``_nmax_by_name`` / ``_nmax_by_hw``) por si el
        callback del área añadió entradas a ``n_max_catalog``.

        Args:
            dept_cfg: Sub-bloque del departamento a rellenar. Si es
                      ``None``, se usa ``self._department_config``.
        """
        if dept_cfg is None:
            dept_cfg = self._department_config
        # Import perezoso para evitar ciclo: core.infrastructure importa
        # core.application solo aquí.
        try:
            from core.application.area_registry import AreaRegistry
        except ImportError:
            _logger.debug(
                "AreaRegistry no disponible; apply_defaults es no-op."
            )
            return
        # Detección de firma una sola vez: si la spec pide solo
        # ``dept_cfg``, no le pasamos ``dept_id`` (back-compat).
        import inspect

        for spec in AreaRegistry.discover().all():
            fn = getattr(spec, "contributes_config_defaults", None)
            if fn is None:
                continue
            try:
                sig = inspect.signature(fn)
                if "dept_id" in sig.parameters:
                    fn(dept_cfg=dept_cfg, dept_id=self._department)
                else:
                    # Back-compat: callable legacy que solo conoce dept_cfg.
                    fn(dept_cfg=dept_cfg)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "apply_defaults: %s.contributes_config_defaults "
                    "falló: %s",
                    spec.id, exc,
                )
        # Re-indexar caches por si el callback del área añadió entradas
        # (p. ej. ``n_max_catalog`` con los 6 N_MAX legacy). Permitimos
        # que la advertencia por "catálogo ausente" se emita de nuevo
        # la próxima vez, ya que ahora la clave SÍ existe.
        self._warned_missing_catalog = False
        self._nmax_by_name = self._index_nmax_catalog()
        self._nmax_by_hw = {
            entry["hw_type"]: entry
            for entry in self._nmax_by_name.values()
            if entry.get("hw_type")
        }

    # ── Departamento activo ─────────────────────────────────────────────

    @property
    def department(self) -> str:
        """Nombre del departamento actualmente resuelto."""
        return self._department

    # ── Tabla global N_MAX ──────────────────────────────────────────────

    def get_global_config_table_name(self) -> str:
        """Devuelve el nombre de la tabla de configuración global (N_MAX).

        Si la clave ``global_config_table_name`` no existe en el bloque
        del departamento, retorna ``""`` (genérico). El área puede
        aportar su valor por defecto vía ``contributes_config_defaults``.
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
        Vacío si la clave no existe (genérico) o si el catálogo está
        vacío.
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
        """Devuelve el named range del Excel que alimenta ``name`` o ``None``."""
        entry = self._nmax_by_name.get(name)
        if entry is None:
            return None
        v = entry.get("excel_named_range", "")
        return v or None

    def get_nmax_for_hw_type(self, hw_type: str) -> str | None:
        """Devuelve el nombre N_MAX asociado a ``hw_type`` o ``None``."""
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
        """Lista los tipos de dispositivo configurados en el departamento activo."""
        dispositivos = self._department_config.get("Dispositivos", {})
        return list(dispositivos.keys())

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
          ``f"Disp{hw_type.replace('_', '').upper().replace('V', 'V')}``
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
        """Ruta de la carpeta de proceso en TIA (default: ``""``)."""
        folders = self._department_config.get("tia_folders", {})
        return str(folders.get("proceso", _DEFAULT_TIA_FOLDER_PROCESO))

    def get_tia_folder_dispositivos(self) -> str:
        """Ruta de la carpeta de dispositivos en TIA (default: ``""``)."""
        folders = self._department_config.get("tia_folders", {})
        return str(folders.get("dispositivos", _DEFAULT_TIA_FOLDER_DISPOSITIVOS))

    def get_tia_folder_nmax(self) -> str:
        """Ruta de la carpeta TIA donde reside la tabla de N_MAX.

        Por defecto ``""`` (genérico). Si el área aporta su carpeta
        N_MAX vía ``contributes_config_defaults`` (PR 2), se respeta.
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
