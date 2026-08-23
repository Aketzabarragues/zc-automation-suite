"""Router Sync: ``/api/v1/sync/disp/...``.

Endpoints de pre-flight (preview sin tocar TIA) y commit (transaccional
contra el PLC) del caso de uso unificado del área de alimentación
(``SyncDispAlimentacionUseCase``). En esta release solo cubre N_MAX
online; cuando crezca, los endpoints ``/disp/preview`` y ``/disp/apply``
extenderán su semántica sin breaking change.

NO instancia gateways: vienen inyectados vía ``Depends``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from application.areas.alimentacion.use_cases.sync_disp_alimentacion import (
    SyncDispAlimentacionUseCase,
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


class DispSyncRequest(BaseModel):
    plc_name: str


def _build_use_case(
    state: AppState,
    gateway: TIAProcessGateway,
    config_manager: ConfigManager,
) -> SyncDispAlimentacionUseCase:
    """Construye el caso de uso con las dependencias inyectadas."""
    return SyncDispAlimentacionUseCase(
        gateway=gateway,
        config_manager=config_manager,
        app_state=state,
    )


@router.post("/disp/preview")
async def disp_preview(
    req: DispSyncRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Calcula el diff de dispositivos (N_MAX) entre AppState y PLC.

    NO toca TIA Portal. Devuelve ``summary``, ``current``, ``desired``,
    ``ops`` y ``warnings`` con el formato de ``SyncDispAlimentacionUseCase.preview_disp``.
    """
    use_case = _build_use_case(state, gateway, config_manager)
    logger.info(
        f"[disp/preview] Generando preview para PLC '{req.plc_name}'..."
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
    """Aplica el diff de dispositivos (N_MAX) en UNA transacción COM única.

    El use case construye la lista de operaciones ``update_user_constant_value``
    y delega en ``gateway.execute_transactional_batch``; el worker abre
    la transacción, itera las ops online y cierra con rollback
    atómico si algo falla.
    """
    use_case = _build_use_case(state, gateway, config_manager)
    logger.info(
        f"[disp/apply] Aplicando diff al PLC '{req.plc_name}'..."
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
        f"[disp/apply] Transacción completada: {n_ops} ops ejecutadas. "
        "Recordar invocar tia_compile_plc para asentar el modelo de memoria."
    )
    return result


# ── ALIASES de backward-compat ────────────────────────────────────────
# El refactor a ``/sync/disp/...`` (release actual) rompe URLs legacy
# ``/sync/preview`` y ``/sync/commit`` que la SPA o scripts externos
# pueden seguir invocando. Estos aliases son wrappers 1-1 sobre los
# endpoints canónicos; se conservarán dos releases más y se
# eliminarán con un warning de deprecation cuando se confirme que
# nadie los usa. NO añadir lógica de negocio aquí: delegar.


@router.post("/preview")
async def sync_preview_alias(
    req: DispSyncRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """DEPRECATED alias de ``/sync/disp/preview``. Conservar 2 releases."""
    logger.warning(
        "[DEPRECATION] POST /api/v1/sync/preview llamado. "
        "Migrar a POST /api/v1/sync/disp/preview."
    )
    return await disp_preview(
        req=req,
        state=state,
        gateway=gateway,
        config_manager=config_manager,
        logger=logger,
    )


@router.post("/commit")
async def sync_commit_alias(
    req: DispSyncRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """DEPRECATED alias de ``/sync/disp/apply``. Conservar 2 releases.

    NOTA: el endpoint legacy aceptaba un body con ``prevision`` (dict)
    que se IGNORABA. El nuevo use case recalcula el diff desde el estado
    actual del AppState, por lo que el alias solo reenvía ``plc_name``.
    Si necesitas el comportamiento viejo (basado en ``prevision`` cached),
    no hay backward-compat posible: rediseña el flujo.
    """
    logger.warning(
        "[DEPRECATION] POST /api/v1/sync/commit llamado. "
        "Migrar a POST /api/v1/sync/disp/apply."
    )
    return await disp_apply(
        req=req,
        state=state,
        gateway=gateway,
        config_manager=config_manager,
        logger=logger,
    )


__all__ = ["router"]
