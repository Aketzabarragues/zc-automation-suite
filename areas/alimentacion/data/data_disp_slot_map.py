"""Slot maps y builder para comentarios por instancia de DBs de dispositivos.

Consolida:
  - El dataclass ``DataDispSlotMap``.
  - La funcion ``disp_build_slot_maps`` y ``disp_build_slot_map_for_hw``.

Une los datos del ``AppCache`` (``comentario_db`` de cada dispositivo)
con la configuracion TIA (``db_name``, ``db_array_name``) para producir
el resultado que el FB aplica contra TIA.

Reutilizado por:
  - el FB ``disp_sincronizar`` (comentarios de dispositivos).
  - el FB ``disp_generar_preview`` (stage de calculo del preview).

Decisiones de diseno:
  - El builder retorna un ``DataDispSlotMap`` (no una tupla suelta).
    Asi el wiring tiene una forma uniforme de representar el resultado.
  - ``frozen=True`` por consistencia con el resto de la familia
    ``data_*`` y porque el resultado del builder es determinista
    respecto a su input (Excel + BloqueCache + ConfigManager).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.runtime.app_cache import AppCache
from core.infrastructure.config.config_manager import ConfigManager


_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataDispSlotMap:
    """Slot maps y metadatos TIA para los tipos de dispositivos del área."""

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


def disp_build_slot_maps(
    app_cache: AppCache,
    config_manager: ConfigManager,
) -> DataDispSlotMap:
    """Construye los slot_maps para todos los tipos activos del departamento.

    Returns:
        ``DataDispSlotMap`` con los 4 campos:
        - ``slot_maps[hw_type]``: ``{slot: texto}`` con ``slot_map[0] == "NO USAR"``
          y ``slot_map[i] == comentario_db`` para cada device con ``numero == i``.
        - ``db_names[hw_type]``: nombre del DB en TIA (via ``ConfigManager``).
        - ``db_array_names[hw_type]``: nombre del array dentro del DB.
        - ``warnings``: lista de warnings (p. ej. tipo sin config TIA).
    """
    slot_maps: dict[str, dict[int, str]] = {}
    db_names: dict[str, str] = {}
    db_array_names: dict[str, str] = {}
    warnings: list[str] = []

    for hw_type in config_manager.list_hw_types_active():
        cfg = config_manager.get_dispositivo_config(hw_type)
        if cfg is None:
            warnings.append(
                f"Tipo de dispositivo '{hw_type}' sin config TIA; se omite."
            )
            continue
        db_names[hw_type] = cfg.db_name
        db_array_names[hw_type] = cfg.db_array_name
        slot_maps[hw_type] = disp_build_slot_map_for_hw(app_cache, hw_type)

    return DataDispSlotMap(
        slot_maps=slot_maps,
        db_names=db_names,
        db_array_names=db_array_names,
        warnings=warnings,
    )


def disp_build_slot_map_for_hw(app_cache: AppCache, hw_type: str) -> dict[int, str]:
    """Slot map para un tipo: ``{0: 'NO USAR', i: comentario_db para cada device con numero==i}``.

    Multi-PLC: lee devices del cache activo del area (filtrado por el
    PLC seleccionado en ``parse_excel_to_cache`` / ``with_plc``).

    Devices con ``numero <= 0`` o duplicados se ignoran (warning en logs).
    El slot 0 siempre esta presente con texto ``"NO USAR"``.

    Raises:
        RuntimeError: si el cache activo del area es ``None``.
    """
    from core.runtime.excel_cache import excel_get_active
    cache = excel_get_active(app_cache, "alimentacion")
    if cache is None:
        raise RuntimeError(
            "app_cache.excel_active_by_area['alimentacion'] es None. "
            "Cargue primero el Excel con POST /api/v1/excel/upload."
        )
    devices_iter = cache.dispositivos.get(hw_type, ())
    slot_map: dict[int, str] = {0: "NO USAR"}
    seen: set[int] = set()
    for device in devices_iter:
        numero = int(getattr(device, "numero", 0) or 0)
        if numero <= 0:
            continue
        if numero in seen:
            _logger.warning(
                f"[{hw_type}] numero={numero} duplicado; se ignora el segundo."
            )
            continue
        seen.add(numero)
        comentario_db = str(getattr(device, "comentario_db", "") or "")
        slot_map[numero] = comentario_db
    return slot_map


__all__ = ["DataDispSlotMap", "disp_build_slot_maps", "disp_build_slot_map_for_hw"]