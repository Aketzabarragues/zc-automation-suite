"""Router Sync: ``/api/v1/sync/...``.

Endpoints de Pre-Flight (preview sin tocar TIA) y Commit
(transaccional contra el PLC). NO instancia gateways: vienen
inyectados vÃ­a ``Depends``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from application.log_buffer import LogBuffer
from application.state import AppState
from application.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)
from interfaces.web_server.dependencies import (
    get_app_state,
    get_config_manager,
    get_gateway,
    get_logger,
)
from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway


router = APIRouter(prefix="/api/v1/sync", tags=["Sync"])


class InstancesPreviewRequest(BaseModel):
    plc_name: str


class InstancesCommitRequest(BaseModel):
    plc_name: str
    prevision: dict[str, Any]


def _build_use_case(
    state: AppState,
    gateway: TIAProcessGateway,
    config_manager: ConfigManager,
) -> SyncDispositivosInstancesUseCase:
    """Construye el caso de uso con las dependencias inyectadas."""
    return SyncDispositivosInstancesUseCase(
        gateway=gateway,
        config_manager=config_manager,
        state=state,
    )


@router.post("/preview")
async def sync_preview(
    req: InstancesPreviewRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Lee XML actual + AppState y devuelve el Diff sin tocar TIA."""
    use_case = _build_use_case(state, gateway, config_manager)
    logger.info(f"Generando prevision para PLC '{req.plc_name}'...")
    try:
        prevision = await use_case.generar_prevision(req.plc_name)
    except Exception as exc:
        logger.error(f"generar_prevision failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"generar_prevision failed: {exc}",
        ) from exc
    logger.success(
        f"Prevision lista: "
        f"{len(prevision.get('agregados', []))} adds, "
        f"{len(prevision.get('eliminados', []))} removes, "
        f"{len(prevision.get('renombrados', []))} renames"
    )
    return prevision


@router.post("/commit")
async def sync_commit(
    req: InstancesCommitRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Aplica la prevision al PLC dentro de un lote transaccional."""
    use_case = _build_use_case(state, gateway, config_manager)
    logger.info(
        f"Aplicando prevision al PLC '{req.plc_name}' "
        f"({len(req.prevision.get('agregados', []))} adds, "
        f"{len(req.prevision.get('eliminados', []))} removes, "
        f"{len(req.prevision.get('renombrados', []))} renames)..."
    )
    try:
        result = await use_case.ejecutar_transaccion(
            req.plc_name, req.prevision
        )
    except Exception as exc:
        logger.error(f"ejecutar_transaccion failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"ejecutar_transaccion failed: {exc}",
        ) from exc
    logger.success(
        f"Transaccion completada: {result.get('operations')} ops"
    )
    return result


__all__ = ["router"]
