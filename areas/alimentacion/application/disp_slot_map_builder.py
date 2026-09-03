"""Builder de slot_maps para comentarios por instancia de DBs de dispositivos.

Une los datos de AppState (``comentario_db`` de cada dispositivo) con la
configuración TIA (``db_name``, ``db_array_name``) para producir el
mapping ``{hw_type: {slot: texto}}`` que el gateway envía a TIA.

Reutilizado por:
  - ``DispComentariosSyncUseCase`` (endpoint ``/aplicar-comentarios-disp``).
  - ``DispSyncInstancesUseCase.ejecutar_transaccion`` (best-effort
    post-compile, nuevo stage 7).
"""
from __future__ import annotations

import logging
from typing import Any

from core.application.state import AppState
from core.infrastructure.config_manager import ConfigManager


_logger = logging.getLogger(__name__)


def disp_build_slot_maps(
    app_state: AppState,
    config_manager: ConfigManager,
) -> tuple[dict[str, dict[int, str]], dict[str, str], dict[str, str], list[str]]:
    """Construye los slot_maps para todos los tipos activos del departamento.

    Returns:
        Tupla ``(slot_maps, db_names, db_array_names, warnings)``.

    - ``slot_maps[hw_type]``: ``{slot: texto}`` con ``slot_map[0] == "NO USAR"``
      y ``slot_map[i] == comentario_db`` para cada device con ``numero == i``.
    - ``db_names[hw_type]``: nombre del DB en TIA (vía ``ConfigManager``).
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
        slot_maps[hw_type] = disp_build_slot_map_for_hw(app_state, hw_type)
    return slot_maps, db_names, db_array_names, warnings


def disp_build_slot_map_for_hw(app_state: AppState, hw_type: str) -> dict[int, str]:
    """Slot map para un tipo: ``{0: 'NO USAR', i: comentario_db para cada device con numero==i}``.

    Devices con ``numero <= 0`` o duplicados se ignoran (warning en logs).
    El slot 0 siempre está presente con texto ``"NO USAR"``.
    """
    slot_map: dict[int, str] = {0: "NO USAR"}
    seen: set[int] = set()
    for device in app_state.get_devices(hw_type):
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
