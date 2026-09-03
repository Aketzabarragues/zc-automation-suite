"""Router Sync: ``/api/v1/sync/...``.

Endpoints de Pre-Flight (preview sin tocar TIA) y Commit
(transaccional contra el PLC) del caso de uso unificado del
área de alimentación. ``/sync/preview`` y ``/sync/commit``
invocan ``SyncDispositivosInstancesUseCase``, que realiza el
sync COMPLETO de N_MAX + devices en una sola transacción COM.

NO instancia gateways: vienen inyectados vía ``Depends``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from areas.alimentacion.application.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)
from core.application.log_buffer import LogBuffer
from core.application.state import AppState
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.dependencies import (
    get_app_state,
    get_config_manager,
    get_gateway,
    get_logger,
)


router = APIRouter(prefix="/api/v1/sync", tags=["Sync"])


class InstancesPreviewRequest(BaseModel):
    plc_name: str


class InstancesCommitRequest(BaseModel):
    plc_name: str
    prevision: dict[str, Any]


# ── Sync completo: N_MAX + devices ──────────────────────────────────────

@router.post("/preview")
async def sync_preview(
    req: InstancesPreviewRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """PREVIEW completo: N_MAX + devices. NO toca TIA.

    Calcula el diff entre el Excel (AppState) y el PLC. Devuelve el
    shape legacy que la SPA espera: ``agregados``, ``eliminados``,
    ``renombrados``, ``todos``, ``nmax`` y ``summary``.
    """
    use_case = SyncDispositivosInstancesUseCase(
        gateway=gateway, config_manager=config_manager, state=state
    )
    logger.info(
        f"[sync/preview] Calculando preview completo para PLC '{req.plc_name}'."
    )
    try:
        prevision = await use_case.generar_prevision(req.plc_name)
    except Exception as exc:
        logger.error(f"[sync/preview] Fallo al calcular preview: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"generar_prevision failed: {exc}",
        ) from exc
    logger.success(
        f"[sync/preview] Preview: "
        f"{prevision.get('summary', {}).get('agregados', 0)} altas, "
        f"{prevision.get('summary', {}).get('eliminados', 0)} bajas, "
        f"{prevision.get('summary', {}).get('renombrados', 0)} renombres, "
        f"{prevision.get('nmax', {}).get('summary', {}).get('actualizar', 0)} N_MAX."
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
    """APPLY completo: N_MAX + devices en UNA transacción COM única.

    El use case ``SyncDispositivosInstancesUseCase.ejecutar_transaccion``
    recalcula el diff desde el AppState (NO usa la ``prevision`` del
    body para evitar race conditions) y lo aplica en una sola
    transacción que incluye:
      - ``import_plc_tags_xml`` (devices add/remove, offline).
      - ``rename_plc_tag`` (devices rename, COM online).
      - ``update_user_constant_value`` (N_MAX, COM online).

    El worker abre ``start_transaction``, itera las ops y cierra con
    ``end_transaction`` (rollback atómico si algo falla).
    """
    use_case = SyncDispositivosInstancesUseCase(
        gateway=gateway, config_manager=config_manager, state=state
    )
    logger.info(
        f"[sync/commit] Aplicando transacción al PLC '{req.plc_name}'."
    )
    try:
        result = await use_case.ejecutar_transaccion(
            req.plc_name, req.prevision,
        )
    except Exception as exc:
        logger.error(f"[sync/commit] Fallo al aplicar transacción: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"ejecutar_transaccion failed: {exc}",
        ) from exc
    logger.success(
        f"[sync/commit] Transacción aplicada: {result.get('operations')} operaciones."
    )
    return result


__all__ = ["router"]
