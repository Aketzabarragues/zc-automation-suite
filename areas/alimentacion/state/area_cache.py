"""areas.alimentacion.state.area_cache - cache del area alimentacion.

Implementa ``AreaCacheProtocol``. Los datos viven aqui, NO en
``AppCache._state``. El core solo conoce el Protocol generico; este
dataclass vive en su bounded context.

Frozen para reemplazar atomicamente la instancia via ``dataclasses.replace``
(la mutacion puntual bajo el lock vive en ``AppCache.mutate_area``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.data.data_excel_cache import DataExcelCache


@dataclass(frozen=True)
class AlimentacionAreaCache:
    """Cache del area alimentacion: Excel + previews + estado de sync."""

    excel_full: "DataExcelCache | None" = None
    excel_active: "DataExcelCache | None" = None

    preview_disp: Any = None
    preview_proc: Any = None

    last_sync_disp_at: datetime | None = None
    last_sync_proc_at: datetime | None = None

    last_disp_commit_summary: dict | None = None
    last_proc_commit_summary: dict | None = None

    def reset(self) -> "AlimentacionAreaCache":
        """Devuelve una nueva instancia con todos los campos en default."""
        return AlimentacionAreaCache()


__all__ = ["AlimentacionAreaCache"]
