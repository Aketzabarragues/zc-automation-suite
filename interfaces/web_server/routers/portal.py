"""Router Portal: ``/api/v1/portal/...`` + ``/api/v1/plcs``.

Endpoints de conexión a TIA Portal y listado de PLCs. Todas las
dependencias se inyectan vía ``Depends``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.application.log_buffer import LogBuffer
from core.application.progress_buffer import ProgressTracker
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.dependencies import (
    get_gateway,
    get_logger,
    get_progress_tracker,
)


router = APIRouter(prefix="/api/v1", tags=["Portal"])


class OpenNewPortalRequest(BaseModel):
    project_file_path: str


@router.post("/portal/attach")
async def portal_attach(
    gateway: TIAProcessGateway = Depends(get_gateway),
    logger: LogBuffer = Depends(get_logger),
    progress: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """HOT-Attach a una instancia YA ABIERTA de TIA Portal."""
    progress.begin(
        operation="attach_portal",
        label="Conectando a TIA Portal (hot-attach)",
        stages=["attach"],
    )
    progress.start_stage("attach", "Adjuntando a instancia de TIA Portal...")
    try:
        ok = await gateway.attach_portal()
        progress.finish_stage("attach", "Attach OK" if ok else "Falló")
        progress.finish(success=ok)
    except Exception as exc:
        progress.finish_stage("attach", f"Error: {exc}")
        progress.finish(success=False, error=str(exc))
        logger.error(f"attach_portal failed: {exc}")
        raise HTTPException(
            status_code=500, detail=f"attach_portal failed: {exc}"
        ) from exc
    logger.success(
        "Hot-attach a TIA Portal OK" if ok else "attach_portal falló"
    )
    return {"ok": ok}


@router.post("/portal/open-new")
async def portal_open_new(
    req: OpenNewPortalRequest,
    gateway: TIAProcessGateway = Depends(get_gateway),
    logger: LogBuffer = Depends(get_logger),
    progress: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """Cold Start: abre un .apxx y carga el proyecto."""
    progress.begin(
        operation="open_new_portal",
        label=f"Abrir proyecto: {req.project_file_path}",
        stages=["open"],
    )
    progress.start_stage("open", f"Abrir {req.project_file_path}...")
    try:
        ok = await gateway.open_new_portal(req.project_file_path)
        progress.finish_stage("open", "Open OK" if ok else "Falló")
        progress.finish(success=ok)
    except Exception as exc:
        progress.finish_stage("open", f"Error: {exc}")
        progress.finish(success=False, error=str(exc))
        logger.error(f"open_new_portal failed: {exc}")
        raise HTTPException(
            status_code=500, detail=f"open_new_portal failed: {exc}"
        ) from exc
    logger.success(
        f"Cold start OK con proyecto '{req.project_file_path}'"
        if ok else "open_new_portal falló"
    )
    return {"ok": ok}


@router.get("/plcs")
async def listar_plcs(
    gateway: TIAProcessGateway = Depends(get_gateway),
    logger: LogBuffer = Depends(get_logger),
    progress: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """Lista los PLCs del TIA Portal conectado.

    NO tumba el servidor si TIA Portal no está conectado: cualquier
    ``Exception`` (incluido ``OpennessAccessException``) se devuelve
    como ``{"ok": False, "error": "..."}`` con HTTP 200.
    """
    progress.begin(
        operation="refresh_plcs",
        label="Listando PLCs de TIA Portal",
        stages=["list"],
    )
    progress.start_stage("list", "Pidiendo lista de PLCs a TIA Portal...")
    try:
        plcs = await gateway.get_plcs(force_refresh=True)
        progress.finish_stage("list", f"{len(plcs)} PLCs")
        progress.finish(success=True)
    except Exception as exc:
        progress.finish_stage("list", f"Error: {exc}")
        progress.finish(success=False, error=str(exc))
        logger.error(f"get_plcs failed: {exc}")
        return {
            "ok": False,
            "error": (
                "TIA Portal no conectado. "
                "Haga Attach u Open New primero."
            ),
            "detail": str(exc),
        }
    logger.info(f"PLC listados: {len(plcs)}")
    return {"ok": True, "plcs": plcs}


__all__ = ["router"]
