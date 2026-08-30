"""Router Areas: ``GET /api/v1/areas``.

Devuelve el catálogo de áreas (departamentos) configurados en
``infrastructure/config.json``. Alimenta la pantalla de bienvenida de
la SPA.

Arquitectura:
  - El router NO instancia nada: lee ``app.state.config_manager`` del
    Composition Root y delega en ``ListAreasUseCase``.
  - El endpoint es lectura pura: no muta estado del servidor.
  - Defensivo: si el config no tiene bloque ``departments``, devuelve
    ``[]`` (HTTP 200), no 500.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from core.application.area_registry import ListAreasUseCase


router = APIRouter(prefix="/api/v1", tags=["Areas"])


class AreaOut(BaseModel):
    """DTO de salida estable. NO añadir campos sin migración de SPA."""

    key: str
    label: str
    description: str
    icon: str
    available: bool


@router.get("/areas", response_model=list[AreaOut])
def list_areas(request: Request) -> list[dict[str, Any]]:
    """Lista las áreas configuradas.

    Returns:
        Lista vacía si no hay áreas configuradas. 200 OK siempre que
        el config_manager esté disponible.
    """
    config_manager = request.app.state.config_manager
    uc = ListAreasUseCase(config_manager)
    return [asdict(a) for a in uc.execute()]


__all__ = ["router", "AreaOut"]
