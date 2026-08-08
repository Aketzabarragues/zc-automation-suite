"""Gestor de configuración dinámica.

Mantiene el mapeo entre tipos de dispositivo del Excel y nombres reales
de tablas dentro del PLC de TIA Portal. Esto evita **hardcodear** nombres
como ``"000_Config_Dispositivos"`` en los casos de uso (criterio del ticket).

⚠️ SCAFFOLDING — Portar la lógica real desde ``_legacy_reference/``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigManager:
    """Stub. La implementación real debe portarse desde el repositorio legacy.

    Lee ``infrastructure/config.json`` y expone helpers tipados para
    resolver nombres de tablas PLC sin acoplarlos al código de negocio.
    """

    def __init__(
        self, config_path: str | Path = "infrastructure/config.json"
    ) -> None:
        self._config_path = Path(config_path)
        self._config: dict[str, Any] = {}
        if self._config_path.is_file():
            try:
                with self._config_path.open("r", encoding="utf-8") as fh:
                    self._config = json.load(fh)
            except (OSError, json.JSONDecodeError):
                self._config = {}

    def get_global_config_table_name(self) -> str:
        """Devuelve el nombre de la tabla de configuración global.

        Raises:
            NotImplementedError: Hasta que se porten los modelos reales
                desde ``_legacy_reference/``.
        """
        raise NotImplementedError(
            "ConfigManager.get_global_config_table_name es un stub. "
            "Portar la lógica desde _legacy_reference/. "
            f"Config path: {self._config_path}"
        )
