"""Router Sync: ``/api/v1/sync/...``.

Endpoints de Pre-Flight (preview sin tocar TIA) y Commit
(transaccional contra el PLC) del caso de uso unificado del
área de alimentación. En esta release, ``/sync/preview`` y
``/sync/commit`` invocan ``SyncDispositivosInstancesUseCase``, que
realiza el sync COMPLETO de N_MAX + devices en una sola transacción
COM. Los endpoints ``/sync/disp/*`` (N_MAX-only) se conservan como
atajo para cuando el operario solo quiera tocar N_MAX.

NO instancia gateways: vienen inyectados vía ``Depends``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from application.areas.alimentacion.use_cases.sync_disp_alimentacion import (
    SyncDispAlimentacionUseCase,
)
from application.areas.alimentacion.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)
from application.log_buffer import LogBuffer
from application.state import AppState
from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway
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


class DispSyncRequest(BaseModel):
    plc_name: str


# ── Sync completo: N_MAX + devices (RESTAURADO en esta release) ─────

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
        f"[sync/preview] Generando preview completo (N_MAX + devices) "
        f"para PLC '{req.plc_name}'..."
    )
    try:
        prevision = await use_case.generar_prevision(req.plc_name)
    except Exception as exc:
        logger.error(f"generar_prevision failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"generar_prevision failed: {exc}",
        ) from exc
    logger.success(
        f"[sync/preview] Preview lista: "
        f"{prevision.get('summary', {}).get('agregados', 0)} adds, "
        f"{prevision.get('summary', {}).get('eliminados', 0)} removes, "
        f"{prevision.get('summary', {}).get('renombrados', 0)} renames, "
        f"{prevision.get('nmax', {}).get('summary', {}).get('actualizar', 0)} N_MAX updates."
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
        f"[sync/commit] Aplicando transacción completa "
        f"(N_MAX + devices) al PLC '{req.plc_name}'..."
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
        f"[sync/commit] Transacción completada: {result.get('operations')} ops. "
        "Recordar invocar tia_compile_plc para asentar el modelo de memoria."
    )
    return result


# ── Sync N_MAX-only (atajo) ──────────────────────────────────────────

@router.post("/disp/preview")
async def disp_preview(
    req: DispSyncRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Calcula el diff de N_MAX entre AppState y PLC. NO toca TIA.

    Atajo: cuando el operario solo quiere tocar N_MAX sin pasar por
    devices. Usa ``SyncDispAlimentacionUseCase``.
    """
    use_case = SyncDispAlimentacionUseCase(
        gateway=gateway, config_manager=config_manager, app_state=state
    )
    logger.info(
        f"[disp/preview] Generando preview N_MAX-only para PLC '{req.plc_name}'..."
    )
    try:
        result = await use_case.preview_disp(req.plc_name)
    except Exception as exc:
        logger.error(f"preview_disp failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"preview_disp failed: {exc}",
        ) from exc
    n_ops = result.get("summary", {}).get("total_ops", 0)
    logger.success(
        f"[disp/preview] Preview lista: {n_ops} ops pendientes."
    )
    return result


@router.post("/disp/apply")
async def disp_apply(
    req: DispSyncRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Aplica el diff de N_MAX en UNA transacción COM única.

    Atajo N_MAX-only (vía ``SyncDispAlimentacionUseCase``).
    """
    use_case = SyncDispAlimentacionUseCase(
        gateway=gateway, config_manager=config_manager, app_state=state
    )
    logger.info(
        f"[disp/apply] Aplicando diff N_MAX al PLC '{req.plc_name}'..."
    )
    try:
        result = await use_case.apply_disp(req.plc_name)
    except Exception as exc:
        logger.error(f"apply_disp failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"apply_disp failed: {exc}",
        ) from exc
    n_ops = result.get("operations_executed", 0)
    logger.success(
        f"[disp/apply] Transacción N_MAX completada: {n_ops} ops. "
        "Recordar invocar tia_compile_plc."
    )
    return result


__all__ = ["router"]
