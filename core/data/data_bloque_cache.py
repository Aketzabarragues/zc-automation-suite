"""core.data.data_bloque_cache — Data Block del cache de bloques de un PLC.

Fase 3, paso 3.1.2.  Migrado de ``core/models/bloque_cache.py`` sin
cambios de contrato: agrupa el resultado de un escaneo completo de un
PLC (bloques + tablas de variables + UDTs) y se reconstruye en el
gateway IT a partir de un dict primitivo recibido del worker OT.

Campos:
  - ``blocks`` (dict[str, BloquePLC]): bloques de programa (DB/FB/FC/OB).
  - ``tag_tables`` (dict[str, BloquePLC]): tablas de variables PLC.
  - ``udts`` (dict[str, BloquePLC]): User Data Types.
    Invariante: los UDTs NUNCA aparecen en ``blocks`` (coleccion
    separada).  El worker OT los escanea via
    ``plc.get_user_data_types()`` y el gateway los reconstruye en
    su propio slot.
  - ``plc_name`` (str): nombre del PLC al que pertenece el cache.
    Vacio si aun no se ha cacheado nada.  Se usa para logs y para
    invalidar selectivamente cuando el operario cambia de PLC
    activo.
  - ``scanned_at`` (datetime, UTC): timestamp del ultimo escaneo.
    El formato ISO-8601 es el contrato con la SPA.

Convenciones:
  - Los tres dicts estan indexados por ``BloquePLC.normalize_name``
    para lookups case/space-insensitive.
  - ``scanned_at`` se captura en UTC; ``to_dict()`` lo serializa
    en ISO-8601.

Migracion:
  - Renombrado de ``BloqueCache`` (legacy) a ``DataBloqueCache``.
    El legacy se mantiene hasta Fase 4 (DA-006 del plan: los use
    cases legacy coexisten con los DBs hasta Fase 4).
  - Import de ``DataBloquePLC`` (paso 3.1.3) desde
    ``core.data.data_bloque_plc``.  El legacy ``BloquePLC`` en
    ``core/models/bloque_plc.py`` sigue existiendo para los use
    cases que aun lo importan, pero este DB ya solo usa el nuevo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.data.data_bloque_plc import DataBloquePLC


@dataclass(frozen=False)
class DataBloqueCache:
    """Cache de un escaneo completo de un PLC.

    Instanciar con ``DataBloqueCache()`` da un cache vacio
    (sin bloques, sin tablas, sin UDTs, ``plc_name=""`` y
    ``scanned_at`` al momento de la creacion).
    """

    blocks: dict[str, DataBloquePLC] = field(default_factory=dict)
    tag_tables: dict[str, DataBloquePLC] = field(default_factory=dict)
    udts: dict[str, DataBloquePLC] = field(default_factory=dict)
    plc_name: str = ""
    scanned_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (compatible JSON / IPC / SSE)."""
        return {
            "plc_name": self.plc_name,
            "blocks": [b.to_dict() for b in self.blocks.values()],
            "tag_tables": [t.to_dict() for t in self.tag_tables.values()],
            "udts": [u.to_dict() for u in self.udts.values()],
            "scanned_at": self.scanned_at.isoformat(),
        }
