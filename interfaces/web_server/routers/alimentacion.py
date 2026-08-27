"""Router Alimentación: ``/api/v1/alimentacion/...``.

Endpoints específicos del área de alimentación que NO son el sync
completo (N_MAX + devices) cubierto por ``sync.py``. Aquí vive el
commit de comentarios por instancia en los 6 DBs de dispositivos,
que se aplica DESPUÉS de ``apply_disp`` + ``compile_plc`` (los DBs
ya están redimensionados).

NO instancia gateways: vienen inyectados vía ``Depends``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from application.areas.alimentacion.use_cases.sync_comentarios_disp import (
    DispComentariosSyncUseCase,
)
from core.application.log_buffer import LogBuffer
from core.application.progress_buffer import ProgressTracker
from core.application.state import AppState
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.dependencies import (
    get_app_state,
    get_config_manager,
    get_gateway,
    get_logger,
    get_progress_tracker,
)


router = APIRouter(prefix="/api/v1/alimentacion", tags=["Alimentacion"])


class AplicarComentariosDispRequest(BaseModel):
    plc_name: str


@router.post("/aplicar-comentarios-disp", response_model=dict)
async def aplicar_comentarios_disp(
    req: AplicarComentariosDispRequest,
    state: AppState = Depends(get_app_state),
    gateway: TIAProcessGateway = Depends(get_gateway),
    config_manager: ConfigManager = Depends(get_config_manager),
    progress: ProgressTracker = Depends(get_progress_tracker),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """APPLY: comentarios por instancia a los 6 DBs en UNA transacción TIA.

    Tras ejecutar ``apply_disp`` (N_MAX) + ``compile_plc`` (redimensionado),
    este endpoint escribe el comentario de cada instancia de los DBs de
    dispositivos (ED/EA/SA/V/M/M_VF) en formato Simatic Source Documents
    (``.s7dcl``/``.s7res``) y reimporta los bloques a TIA Portal bajo
    UNA sola transacción COM con rollback atómico.

    NO exporta los PlcTag, NO toca N_MAX (eso es ``sync.py``). Solo
    actualiza el comentario por instancia.
    """
    use_case = DispComentariosSyncUseCase(
        gateway=gateway,
        config_manager=config_manager,
        app_state=state,
        progress=progress,
    )
    logger.info(
        f"[alimentacion/aplicar-comentarios-disp] Aplicando comentarios "
        f"por instancia al PLC '{req.plc_name}'..."
    )
    try:
        result = await use_case.apply_comentarios_disp(req.plc_name)
    except Exception as exc:
        logger.error(f"apply_comentarios_disp failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"apply_comentarios_disp failed: {exc}",
        ) from exc
    logger.success(
        f"[alimentacion/aplicar-comentarios-disp] OK: "
        f"{result.get('operations_executed', 0)} ops aplicadas."
    )
    return result


__all__ = ["router"]
