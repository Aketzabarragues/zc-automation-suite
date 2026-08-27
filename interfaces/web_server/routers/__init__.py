"""Routers GENÉRICOS de la capa web (FastAPI).

Solo routers del shell (comunes a todas las áreas). Los routers
específicos de cada Bounded Context viven en
``areas/<area>/interfaces/web/`` y los monta el shell vía
``AreaRegistry.for_each("contributes_routers", app=app)`` desde
``interfaces/web_server/app.py``.

Cada submódulo expone un ``APIRouter`` independiente que se ensambla
en ``interfaces/web_server/app.py``. Los routers NO importan estado
global: todas las dependencias se reciben vía ``fastapi.Depends``.
"""
from __future__ import annotations

from .areas import router as areas_router
from .catalog import router as catalog_router
from .diagnostics import router as diagnostics_router
from .portal import router as portal_router

__all__ = [
    "areas_router",
    "catalog_router",
    "diagnostics_router",
    "portal_router",
]
