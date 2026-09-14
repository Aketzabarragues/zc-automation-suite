"""Estado global de la app como data pura, serializable a SSE.

Data Block puro (sin comportamiento, sin I/O). La clase ``AppState``
legacy en ``core/runtime/app_state.py`` mantiene el Singleton y la
integracion con las areas; este DB es el shape de datos que viaja al
frontend via SSE.

Campos:
  - dispositivos (dict[str, list[Any]]): dispositivos indexados por hw_type.
  - dimensiones (dict[str, Any]): N_MAX de PlcUserConstants (default {}).
  - excel_cache (Any): cache IT del Excel. NO se serializa en to_dict().
  - excel_path (str | None): ruta absoluta del Excel cacheado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=False)
class DataAppState:
    """Estado de la app como data pura, serializable a SSE."""

    dispositivos: dict[str, list[Any]] = field(default_factory=dict)
    dimensiones: dict[str, Any] = field(default_factory=dict)
    excel_cache: Any = None
    excel_path: str | None = None

    def set_devices(self, hw_type: str, devices: list[Any]) -> None:
        """Sustituye la lista de dispositivos de ``hw_type``.

        Copia la lista para evitar aliasing entre el caller y el estado.
        """
        self.dispositivos[hw_type] = list(devices)

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (JSON / IPC / SSE).

        ``excel_cache`` se excluye (objetos no-JSON); se emite
        ``excel_loaded`` para que la SPA sepa si hay Excel en memoria.
        """
        return {
            "dispositivos": {
                hw: list(devs) for hw, devs in self.dispositivos.items()
            },
            "dimensiones": dict(self.dimensiones),
            "excel_loaded": self.excel_cache is not None,
            "excel_path": self.excel_path,
        }
