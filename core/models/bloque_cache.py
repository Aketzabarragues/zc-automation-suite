"""Value Object: ``BloqueCache``.

DTO mutable que agrupa el resultado de un escaneo completo de un PLC:
todos sus bloques de programa + todas sus tablas de variables (tag tables)
+ todos sus User Data Types (UDTs).
Se cachea en el gateway IT (``TIAProcessGateway._bloques_cache``) y se
reconstruye a partir de un dict primitivo recibido del worker OT.

Convenciones:
  - ``blocks``, ``tag_tables`` y ``udts`` son ``dict[str, BloquePLC]``
    indexados por ``BloquePLC.normalize_name`` para lookups
    case/space-insensitive.
  - ``scanned_at`` se captura en UTC; el formato ISO-8601 es el contrato
    con la SPA.
  - ``plc_name`` se almacena para logs y para invalidar selectivamente
    cuando el operario cambia de PLC activo.
  - Invariante: los UDTs NUNCA aparecen en ``blocks`` (colección separada).
    El worker OT los escanea via ``plc.get_user_data_types()`` y el
    gateway IT los reconstruye en su propio slot. La SPA los pinta en un
    tab independiente ("UDTs") del "Cache de bloques".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.models.bloque_plc import BloquePLC


@dataclass
class BloqueCache:
    """Resultado cacheable de un escaneo completo de un PLC."""

    blocks: dict[str, BloquePLC] = field(default_factory=dict)
    tag_tables: dict[str, BloquePLC] = field(default_factory=dict)
    udts: dict[str, BloquePLC] = field(default_factory=dict)
    plc_name: str = ""
    scanned_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (compatible JSON / IPC)."""
        return {
            "plc_name": self.plc_name,
            "blocks": [b.to_dict() for b in self.blocks.values()],
            "tag_tables": [t.to_dict() for t in self.tag_tables.values()],
            "udts": [u.to_dict() for u in self.udts.values()],
            "scanned_at": self.scanned_at.isoformat(),
        }
