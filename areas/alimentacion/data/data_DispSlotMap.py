"""areas.alimentacion.data.data_DispSlotMap — Data Block de slot maps de dispositivos.

Fase 3, paso 3.2.8.  **No existe un dataclass ``DispSlotMap`` en el
legacy**: la funcion ``disp_build_slot_maps`` en
``areas/alimentacion/application/disp_slot_map_builder.py`` retorna
una tupla de 4 valores ``(slot_maps, db_names, db_array_names, warnings)``.
Este paso **consolida** la tupla en un dataclass con 4 campos para
consistencia con ``DataProcSlotMap`` (paso 3.2.9) y para que el wiring
(DA-005.5) tenga una forma uniforme de representar el resultado del
builder.

Campos:
  - ``slot_maps``: ``dict[hw_type, dict[int, str]]``.  ``slot_map[0] ==
    "NO USAR"`` (convención TIA) y ``slot_map[i] == comentario_db``
    para cada device con ``numero == i``.
  - ``db_names``: ``dict[hw_type, str]``.  Nombre del DB en TIA
    (vía ``ConfigManager``).
  - ``db_array_names``: ``dict[hw_type, str]``.  Nombre del array
    dentro del DB.
  - ``warnings``: ``list[str]``.  Warnings no fatales (p. ej. tipo sin
    config TIA).

Migracion:
  - El builder legacy sigue retornando la tupla (DA-006).  Un shim
    paralelo o un wrapper que cree el ``DataDispSlotMap`` a partir de
    la tupla se introducira en el wiring (DA-005.5) si los callers lo
    necesitan; por ahora el dataclass existe como destino formal.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DataDispSlotMap:
    """Slot maps y metadatos TIA para los 6 tipos de dispositivos.

    ``frozen=True`` por consistencia con el resto de la familia
    ``data_*`` y porque el resultado del builder es determinista
    respecto a su input (Excel + BloqueCache + ConfigManager).
    """

    slot_maps: dict[str, dict[int, str]] = field(default_factory=dict)
    db_names: dict[str, str] = field(default_factory=dict)
    db_array_names: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (compatible JSON / IPC / SSE)."""
        return {
            "slot_maps": {
                hw: {str(slot): txt for slot, txt in slots.items()}
                for hw, slots in self.slot_maps.items()
            },
            "db_names": dict(self.db_names),
            "db_array_names": dict(self.db_array_names),
            "warnings": list(self.warnings),
        }


__all__ = ["DataDispSlotMap"]
