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

    Args:
        area_id: Identificador del área (p. ej. ``"alimentacion"``).

    Returns:
        Dict con la forma:
            ``{
                "id": str,
                "label": str,
                "icon": str,
                "components": {
                    "sidebar": "<ComponentName>",
                    "landing": "<ComponentName>",
                    "views": { "<key>": "<ComponentName>", ... }
                },
                "loaders": {
                    "<ComponentName>": "<url>",
                    ...
                }
            }``

    Raises:
        HTTPException: 404 si el área no existe o no aporta manifest
            frontend (todavía o por diseño — un área sin UI solo
            aporta comandos TIA, p. ej.).

    Notas:
        Es un endpoint genérico del shell. No sabe de áreas concretas:
        el contenido se delega 100% al ``contributes_frontend_manifest``
        de cada ``AreaSpec``. Añadir un área con UI = implementar su
        callable y registrarlo en la ``AREA_SPEC``. Cero cambios aquí.
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
