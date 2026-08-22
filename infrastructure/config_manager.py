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
NO configurados): ``sd``, ``m_sina``, ``tq``, ``tq_ae``, ``productos``.

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


@dataclass(frozen=True)
class DispositivoTIAConfig:
    """Configuración TIA de un tipo de dispositivo del departamento activo.

    Attributes:
        key:           Identificador lógico (``"ed"``, ``"ea"``, etc.).
        db_name:       Nombre del DB (ej. ``"DB2000_ED"``).
        db_array_name: Nombre del array dentro del DB (ej. ``"ED"``).
        tag_table:     Nombre de la PlcTagTable del dispositivo
                       (ej. ``"2000_Disp_ED"``).
        config_table:  Nombre de la PlcTagTable donde residen las
                       PlcUserConstant N_MAX (típicamente
                       ``"000_Config_Dispositivos"``).
    """

    key: str
    db_name: str
    db_array_name: str
    tag_table: str
    config_table: str


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
      - **Configuración por tipo de dispositivo**:
        ``get_dispositivo_config(key)`` → ``DispositivoTIAConfig | None``.
        Alias deprecado ``get_hardware_config`` (conservado una release).
      - **Getters específicos** (None si el tipo no existe):
        ``get_tag_table_name(key)``, ``get_db_name(key)``,
        ``get_db_array_name(key)``.
      - **Carpetas TIA**: ``get_tia_folder_proceso()``,
        ``get_tia_folder_dispositivos()``, ``get_tia_folder_nmax()``.
      - **Listado**: ``list_keys()`` (alias deprecado ``list_hw_types``).

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

    # ── Configuración por tipo de dispositivo ──────────────────────────

    def get_dispositivo_config(self, key: str) -> DispositivoTIAConfig | None:
        """Devuelve la configuración TIA completa de un tipo de dispositivo.

        Args:
            key: Identificador (``"ed"``, ``"ea"``, ``"sa"``, ``"v"``,
                 ``"m"``, ``"m_vf"``).

        Returns:
            ``DispositivoTIAConfig`` con los 5 campos del config, o
            ``None`` si el tipo no existe. Loggea un warning en el
            segundo caso (NO lanza excepción: forward-compatible con
            tipos futuros aún no configurados).
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
            return DispositivoTIAConfig(
                key=key,
                db_name=str(d.get("db_name", "")),
                db_array_name=str(d.get("db_array_name", "")),
                tag_table=str(d.get("tag_table", "")),
                config_table=str(d.get("config_table", "")),
            )
        except Exception as e:
            _logger.warning(
                f"Error parseando config de '{key}': {e}. Se retorna None."
            )
            return None

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


__all__ = ["ConfigManager", "DispositivoTIAConfig"]
