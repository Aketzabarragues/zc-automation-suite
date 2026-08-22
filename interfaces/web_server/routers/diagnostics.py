"""Router Diagnostics: ``/api/v1/logs`` + ``/api/v1/state/...``.

Endpoints de sólo lectura (IT) para la SPA: vuelca el ``AppState``
y expone el ``LogBuffer``. Nunca toca la DLL de Siemens.

Migrado a data-driven: en vez de hardcodear los 6 tipos legacy,
se itera ``ConfigManager.list_hw_types_active()`` y se usa
``get_excel_target_for(hw)["canonical"]`` para resolver la clave
del dict ``dispositivos`` de la respuesta. Cuando mañana se
active un 7º tipo en el config, este endpoint lo recoge sin
cambios.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter, Depends

from application.log_buffer import LogBuffer
from application.state import AppState
from infrastructure.config_manager import ConfigManager
from interfaces.web_server.dependencies import (
    get_app_state,
    get_config_manager,
    get_logger,
)
from application.log_buffer import get_log_buffer


router = APIRouter(prefix="/api/v1", tags=["Diagnostics"])


@router.get("/state/dispositivos")
async def state_dispositivos(
    state: AppState = Depends(get_app_state),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """Vuelca el ``AppState`` Singleton a JSON para el Inspector IT.

    - ``dimensiones`` se serializa vía ``to_api_dict()`` (NO
      ``dataclasses.asdict``) para que el campo ``extras`` —
      interno del wrapper, pensado para futuros N_MAX del
      catálogo — NO aparezca en la SPA. Los 6 legacy
      ``num_disp_*`` siguen saliendo con la misma forma exacta
      que antes del refactor.
    - ``dispositivos`` se itera por ``cm.list_hw_types_active()``;
      la clave de cada entrada es la ``canonical`` resuelta vía
      ``cm.get_excel_target_for(hw)`` (``DispED``,
      ``DispEA``, ...). Los 6 legacy actuales salen idéntico
      que antes; los tipos nuevos saldrán automáticamente.
    """
    dispositivos_payload: dict[str, list[dict[str, Any]]] = {}
    for hw in config_manager.list_hw_types_active():
        target = config_manager.get_excel_target_for(hw)
        if target is None:
            continue
        canonica = target.get("canonical", "")
        if not canonica:
            continue
        dispositivos_payload[canonica] = [
            dataclasses.asdict(d) for d in state.get_devices(hw)
        ]

    return {
        "ok": True,
        "dimensiones": state.dimensiones.to_api_dict(),
        "dispositivos": dispositivos_payload,
    }


@router.get("/logs")
async def get_logs(
    _logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Devuelve snapshot de mensajes para que la SPA los muestre."""
    return {"logs": get_log_buffer().snapshot()}


@router.post("/logs/clear")
async def clear_logs(
    _logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Vacía el buffer de logs (botón 'Limpiar consola' en SPA)."""
    get_log_buffer().clear()
    return {"cleared": True}


__all__ = ["router"]
