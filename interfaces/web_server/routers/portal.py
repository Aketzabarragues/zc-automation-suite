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
    logger.info("[portal/attach] Adjuntando a TIA Portal.")
    try:
        ok = await gateway.attach_portal()
        progress.finish_stage("attach", "Attach OK" if ok else "Falló")
        progress.finish(success=ok)
    except Exception as exc:
        progress.finish_stage("attach", f"Error: {exc}")
        progress.finish(success=False, error=str(exc))
        logger.error(f"[portal/attach] Fallo al adjuntar a TIA Portal: {exc}")
        raise HTTPException(
            status_code=500, detail=f"attach_portal failed: {exc}"
        ) from exc
    logger.success("[portal/attach] Adjuntado a TIA Portal.")
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
    logger.info(f"[portal/open] Abriendo proyecto {req.project_file_path}.")
    try:
        ok = await gateway.open_new_portal(req.project_file_path)
        progress.finish_stage("open", "Open OK" if ok else "Falló")
        progress.finish(success=ok)
    except Exception as exc:
        progress.finish_stage("open", f"Error: {exc}")
        progress.finish(success=False, error=str(exc))
        logger.error(f"[portal/open] Fallo al abrir proyecto: {exc}")
        raise HTTPException(
            status_code=500, detail=f"open_new_portal failed: {exc}"
        ) from exc
    logger.success(f"[portal/open] Proyecto abierto: {req.project_file_path}.")
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
    logger.info("[portal/plcs] Listando PLCs de TIA Portal.")
    try:
        plcs = await gateway.get_plcs(force_refresh=True)
        progress.finish_stage("list", f"{len(plcs)} PLCs")
        progress.finish(success=True)
    except Exception as exc:
        progress.finish_stage("list", f"Error: {exc}")
        progress.finish(success=False, error=str(exc))
        logger.error(f"[portal/plcs] Fallo al listar PLCs: {exc}")
        return {
            "ok": False,
            "error": (
                "TIA Portal no conectado. "
                "Haga Attach u Open New primero."
            ),
            "detail": str(exc),
        }
    logger.success(f"[portal/plcs] Listados {len(plcs)} PLCs.")
    return {"ok": True, "plcs": plcs}


@router.get("/portal/project-info")
async def get_project_info(
    gateway: TIAProcessGateway = Depends(get_gateway),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Devuelve el nombre y propiedades básicas del proyecto TIA activo.

    Mismo contrato de error que ``/plcs``: si TIA Portal no está
    conectado, devuelve ``{"ok": false, "error": "..."}`` con HTTP 200
    (no 500) para que la SPA degrade limpiamente.

    NOTA: este endpoint NO usa ``ProgressTracker``. La operación
    (``get_property("Name")`` sobre el proyecto) es prácticamente
    instantánea (<50 ms) y el Sidebar la lanza en ``Promise.all`` con
    ``/api/v1/plcs``. Si emitiéramos nuestro propio ``progress.begin()``
    concurrente con el de ``/plcs``, el tracker mostraría
    "reemplazado por" y el operario vería parpadeo en el
    ``ProgressIndicator``. La política del proyecto es: el tracker
    solo cubre operaciones largas, y el feedback de esta llamada
    es suficiente con el ``logger.info`` final.
    """
    logger.info("[portal/project] Consultando información del proyecto.")
    try:
        info = await gateway.get_project_info(force_refresh=True)
    except Exception as exc:
        logger.error(f"[portal/project] Fallo al consultar el proyecto: {exc}")
        return {
            "ok": False,
            "error": (
                "TIA Portal no conectado. "
                "Haga Attach u Open New primero."
            ),
            "detail": str(exc),
        }
    logger.success(f"[portal/project] Proyecto: {info.get('name', '(sin nombre)')}.")
    return {"ok": True, "project_info": info}


__all__ = ["router"]
