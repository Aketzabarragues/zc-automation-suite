"""Cache de bloques de un PLC.

Agrupa el resultado de un escaneo completo (bloques + tablas de
variables + UDTs). Se reconstruye en el gateway IT a partir de un
dict primitivo recibido del worker OT.

Campos:
  - blocks (dict[str, DataBloquePLC]): bloques de programa (DB/FB/FC/OB).
  - tag_tables (dict[str, DataBloquePLC]): tablas de variables PLC.
  - udts (dict[str, DataBloquePLC]): User Data Types (coleccion
    separada, nunca aparecen en ``blocks``).
  - plc_name (str): nombre del PLC al que pertenece el cache.
  - scanned_at (datetime, UTC): timestamp del ultimo escaneo.

Los tres dicts se indexan por ``DataBloquePLC.normalize_name``
(case/space-insensitive). ``scanned_at`` se serializa en ISO-8601.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.data.data_block_plc import DataBloquePLC


@dataclass(frozen=False)
class DataBloqueCache:
    """Cache de un escaneo completo de un PLC."""

    blocks: dict[str, DataBloquePLC] = field(default_factory=dict)
    tag_tables: dict[str, DataBloquePLC] = field(default_factory=dict)
    udts: dict[str, DataBloquePLC] = field(default_factory=dict)
    plc_name: str = ""
    scanned_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (JSON / IPC / SSE)."""
        return {
            "plc_name": self.plc_name,
            "blocks": [b.to_dict() for b in self.blocks.values()],
            "tag_tables": [t.to_dict() for t in self.tag_tables.values()],
            "udts": [u.to_dict() for u in self.udts.values()],
            "scanned_at": self.scanned_at.isoformat(),
        }
