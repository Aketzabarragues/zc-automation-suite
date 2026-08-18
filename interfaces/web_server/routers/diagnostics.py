"""Router Diagnostics: ``/api/v1/logs`` + ``/api/v1/state/...``.

Endpoints de sólo lectura (IT) para la SPA: vuelca el ``AppState``
y expone el ``LogBuffer``. Nunca toca la DLL de Siemens.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter, Depends

from application.log_buffer import LogBuffer
from application.state import AppState
from interfaces.web_server.dependencies import get_app_state, get_logger
from application.log_buffer import get_log_buffer


router = APIRouter(prefix="/api/v1", tags=["Diagnostics"])


@router.get("/state/dispositivos")
async def state_dispositivos(
    state: AppState = Depends(get_app_state),
) -> dict[str, Any]:
    """Vuelca el ``AppState`` Singleton a JSON para el Inspector IT."""
    return {
        "ok": True,
        "dimensiones": dataclasses.asdict(state.dimensiones),
        "dispositivos": {
            "DispED":   [dataclasses.asdict(d) for d in state.dispositivos_ed],
            "DispEA":   [dataclasses.asdict(d) for d in state.dispositivos_ea],
            "DispSA":   [dataclasses.asdict(d) for d in state.dispositivos_sa],
            "DispV":    [dataclasses.asdict(d) for d in state.dispositivos_v],
            "DispM":    [dataclasses.asdict(d) for d in state.dispositivos_m],
            "DispM_VF": [dataclasses.asdict(d) for d in state.dispositivos_m_vf],
        },
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
