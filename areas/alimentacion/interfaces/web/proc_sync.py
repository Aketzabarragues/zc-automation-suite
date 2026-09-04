"""Router ProcesosSync: ``/api/v1/procesos/sync/...``.

Endpoints de Pre-Flight (preview sin tocar TIA) y Commit
(transaccional contra el PLC) del caso de uso unificado de
sincronización de comentarios de DBs de procesos
(PReal + PInt + ALM).

``/sync/preview`` y ``/sync/commit`` invocan
``ProcSyncComentariosUseCase``, que realiza el sync de los 3
arrays en una sola transacción COM.

NO instancia gateways: vienen inyectados vía ``Depends``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from areas.alimentacion.application.proc_slot_map_builder import proc_build_slot_maps
from areas.alimentacion.application.use_cases.proc_sync_comentarios import (
    ProcSyncComentariosUseCase,
)
from core.application.log_buffer import LogBuffer
from core.application.progress_buffer import ProgressTracker
from core.application.state import AppState
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAConnectionError, TIAProcessGateway
from interfaces.web_server.dependencies import (
    get_app_state,
    get_config_manager,
    get_gateway,
    get_logger,
    get_progress_tracker,
)


router = APIRouter(prefix="/api/v1/procesos", tags=["ProcesosSync"])


class ProcesosPreviewRequest(BaseModel):
    proc_uid: int
    plc_name: str = ""  # opcional: solo para logging


class ProcesosCommitRequest(BaseModel):
    proc_uid: int
    plc_name: str
    prevision: dict[str, Any]


# ── Preview ─────────────────────────────────────────────────────────────


@router.post("/sync/preview")
async def sync_preview(
    req: ProcesosPreviewRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    logger: LogBuffer = Depends(get_logger),
    progress: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """PREVIEW: diff de comentarios por proceso. NO toca TIA.

    Calcula el diff entre el Excel (AppState) y los 3 nombres TIA
    esperados (DB_PARAM, DB_ALM, tabla). Devuelve el shape que la
    SPA renderiza en la vista ``proc_sync``.

    Resolución de la cache de bloques: la cache vive en el
    ``gateway._bloques_cache[plc_name]`` tras un
    ``scan_plc_blocks`` previo. El router la pide con
    ``gateway.get_bloques_cache(plc_name)`` (lectura pura, no
    triggerea scan). Si el PLC no ha sido escaneado, devuelve
    ``None`` y el use case reporta un warning accionable al
    operario (en lugar de fingir que los 3 bloques están
    ausentes).
    """
    plc_name = (req.plc_name or "").strip()
    bloques_cache = (
        gateway.get_bloques_cache(plc_name) if plc_name else None
    )
    use_case = ProcSyncComentariosUseCase(
        gateway=gateway,
        config_manager=config_manager,
        app_state=state,
        progress=progress,
        bloques_cache=bloques_cache,
    )
    logger.info(
        f"[procesos/preview] Calculando preview para proceso uid={req.proc_uid}."
    )
    try:
        prevision = await use_case.generar_prevision(req.proc_uid)
    except TIAConnectionError as exc:
        logger.error(f"[procesos/preview] TIA Portal no responde: {exc}")
        raise HTTPException(
            status_code=503,
            detail=(
                f"TIA Portal no responde: {exc}. "
                "Reconecta el portal y vuelve a seleccionar el PLC."
            ),
            headers={"X-Error-Type": "TIAConnectionError"},
        ) from exc
    except Exception as exc:
        logger.error(f"[procesos/preview] Fallo al calcular preview: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"generar_prevision failed: {exc}",
        ) from exc
    logger.success(
        f"[procesos/preview] Preview: "
        f"precondiciones_ok={prevision.get('precondiciones_ok')}, "
        f"{len(prevision.get('missing_blocks', []))} bloques faltantes."
    )
    return prevision


# ── Commit ──────────────────────────────────────────────────────────────


@router.post("/sync/commit")
async def sync_commit(
    req: ProcesosCommitRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    logger: LogBuffer = Depends(get_logger),
    progress: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """APPLY: 3 arrays (PReal + PInt + ALM) en UNA transacción COM única.

    El use case ``ProcSyncComentariosUseCase.ejecutar_transaccion``
    recalcula el diff desde el AppState (NO usa la ``prevision`` del
    body para evitar race conditions con cambios de Excel) y lo
    aplica en una sola transacción que envía 3 sub-ops al worker
    (una por array). El worker abre ``start_transaction``, itera
    las ops y cierra con ``end_transaction`` (rollback atómico si
    algo falla).
    """
    bloques_cache = (
        gateway.get_bloques_cache(req.plc_name)
        if req.plc_name
        else None
    )
    use_case = ProcSyncComentariosUseCase(
        gateway=gateway,
        config_manager=config_manager,
        app_state=state,
        progress=progress,
        bloques_cache=bloques_cache,
    )
    logger.info(
        f"[procesos/commit] Aplicando transacción para proceso "
        f"uid={req.proc_uid} en PLC '{req.plc_name}'."
    )
    # Inyectamos plc_name en la prevision para que el use case
    # lo extraiga (la prevision del cliente puede no traerlo).
    prevision_with_plc = dict(req.prevision)
    prevision_with_plc.setdefault("plc_name", req.plc_name)
    try:
        result = await use_case.ejecutar_transaccion(
            req.proc_uid, prevision_with_plc
        )
    except TIAConnectionError as exc:
        logger.error(f"[procesos/commit] TIA Portal no responde: {exc}")
        raise HTTPException(
            status_code=503,
            detail=(
                f"TIA Portal no responde: {exc}. "
                "Reconecta el portal y vuelve a seleccionar el PLC."
            ),
            headers={"X-Error-Type": "TIAConnectionError"},
        ) from exc
    except Exception as exc:
        logger.error(f"[procesos/commit] Fallo al aplicar transacción: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"ejecutar_transaccion failed: {exc}",
        ) from exc
    logger.success(
        f"[procesos/commit] Transacción aplicada: "
        f"{result.get('operations_executed', 0)} operaciones."
    )
    return result


__all__ = ["router"]
