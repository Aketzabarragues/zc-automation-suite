"""Routers de la capa web (FastAPI).

Cada submódulo expone un ``APIRouter`` independiente que se ensambla
en ``interfaces/web_server/app.py``. Los routers NO importan estado
global: todas las dependencias se reciben vía ``fastapi.Depends``.
"""
from __future__ import annotations

from .diagnostics import router as diagnostics_router
from .excel import router as excel_router
from .portal import router as portal_router
from .sync import router as sync_router

__all__ = [
    "diagnostics_router",
    "excel_router",
    "portal_router",
    "sync_router",
]
