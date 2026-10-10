"""core.data.data_plc_info - tipos de datos compartidos del PLC.

`PlcInfo` y `PlcProject` son los tipos GENERICOS de proceso: el AppCache
los guarda como dato cacheado del worker TIA Portal. No son tipos del
area (eso vive en areas/<area>/data/). Solo lo que el worker expone.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlcInfo:
    """PLC descubierto por el worker TIA."""
    name: str
    type: str
    ip: str


@dataclass(frozen=True)
class PlcProject:
    """Proyecto TIA activo (keyed por plc_name en app_cache)."""
    name: str | None
    path: str | None
    version: str | None


__all__ = ["PlcInfo", "PlcProject"]