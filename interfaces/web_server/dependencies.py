"""Inyectores de dependencias para la capa web (FastAPI).

Regla de oro de Clean Architecture en routers: **ningún** archivo
dentro de ``interfaces/web_server/routers/`` debe importar
instancias globales (``TIAProcessGateway``, ``AppState``,
``LogBuffer``). Todos los objetos se recuperan al vuelo vía
``fastapi.Depends`` desde ``request.app.state``, donde el
Composition Root (``interfaces/web_server/app.py``) los inyecta al
arrancar la app.

Beneficios:
  * Cero estado global en routers (fácil de testear con ``app.dependency_overrides``).
  * Sustituir el gateway en tests es trivial: se sobreescribe
    ``app.state.gateway`` y todos los Depends lo ven.
  * Cualquier futura lectura de configuración o de caché se añade
    aquí sin tocar los routers.
"""
from __future__ import annotations

from fastapi import Request

from application.log_buffer import LogBuffer
from application.state import AppState
from infrastructure.gateway import TIAProcessGateway


def get_gateway(request: Request) -> TIAProcessGateway:
    """Devuelve la UNICA instancia de gateway inyectada en ``app.state``."""
    return request.app.state.gateway


def get_app_state(request: Request) -> AppState:
    """Devuelve el ``AppState`` Singleton (cacheado en ``app.state``)."""
    return request.app.state.app_state


def get_logger(request: Request) -> LogBuffer:
    """Devuelve el ``LogBuffer`` Singleton compartido por toda la app."""
    return request.app.state.logger


__all__ = [
    "get_gateway",
    "get_app_state",
    "get_logger",
]
