"""Gestor de configuración dinámica.

Lee ``infrastructure/config.json`` y expone el mapeo entre tipos de
dispositivo del Excel y nombres reales de tablas dentro del PLC de
TIA Portal. Esto evita hardcodear nombres como ``"000_Config_Dispositivos"``
en los casos de uso.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_DEFAULT_GLOBAL_CONFIG_TABLE_NAME = "000_Config_Dispositivos"


class ConfigManager:
    """Carga ``infrastructure/config.json`` y expone el mapeo dinámico."""

    def __init__(
        self, config_path: str | Path = "infrastructure/config.json"
    ) -> None:
        self._config_path = Path(config_path)
        self._config: dict[str, Any] = self._load_config()

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

    def get_global_config_table_name(self) -> str:
        """Devuelve el nombre de la tabla de configuración global.

        Si la clave ``global_config_table_name`` no existe en el JSON,
        retorna ``"000_Config_Dispositivos"`` como fallback defensivo
        (mantiene compatibilidad con proyectos legacy que no tenían
        el ``config.json`` explícito).
        """
        return str(
            self._config.get(
                "global_config_table_name",
                _DEFAULT_GLOBAL_CONFIG_TABLE_NAME,
            )
        )
