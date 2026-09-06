"""Router genérico: manifests frontend de las áreas.

Endpoint:
    GET /api/v1/areas/<area_id>/manifest → AreaManifest JSON

Itera el ``AreaRegistry`` y, para cada área con
``contributes_frontend_manifest``, invoca el callable y devuelve
el dict que retorna. Si el área no existe o no aporta manifest,
devuelve 404.

El manifest se serializa a JSON. La SPA (``area-loader.js``) lo
consume y monta los componentes del área dinámicamente (sin imports
hardcoded en el shell).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.application.area_registry import AreaRegistry


router = APIRouter(prefix="/api/v1/areas", tags=["Areas"])


@router.get("/{area_id}/manifest")
def get_area_manifest(area_id: str) -> dict:
    """Devuelve el manifest frontend del área ``area_id``.

    El contenido lo aporta el ``contributes_frontend_manifest`` de
    cada ``AreaSpec``: este endpoint es genérico y no sabe de áreas
    concretas. Si el área no existe o no aporta manifest, devuelve
    404.
    """
    spec = AreaRegistry.discover().get(area_id)
    if spec is None or spec.contributes_frontend_manifest is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Área '{area_id}' no encontrada o sin manifest frontend."
            ),
        )
    return spec.contributes_frontend_manifest()


__all__ = ["router"]
