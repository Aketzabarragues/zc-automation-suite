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

from core.application.log_buffer import LogBuffer
from core.application.progress_buffer import ProgressTracker
from core.application.state import AppState
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway
from core.plc.engine import Engine


def get_gateway(request: Request) -> TIAProcessGateway:
    """Devuelve la UNICA instancia de gateway inyectada en ``app.state``."""
    return request.app.state.gateway


def get_app_state(request: Request) -> AppState:
    """Devuelve el ``AppState`` Singleton (cacheado en ``app.state``)."""
    return request.app.state.app_state


def get_logger(request: Request) -> LogBuffer:
    """Devuelve el ``LogBuffer`` Singleton compartido por toda la app."""
    return request.app.state.logger


def get_progress_tracker(request: Request) -> ProgressTracker:
    """Devuelve el ``ProgressTracker`` Singleton compartido por toda la app.

    Mismo patrón que ``get_logger``: se inyecta en ``app.state`` por el
    Composition Root y los routers la recuperan vía ``Depends``. Los use
    cases la reciben directamente por constructor (no necesitan el
    request de FastAPI).
    """
    return request.app.state.progress_tracker


def get_config_manager(request: Request) -> ConfigManager:
    """Devuelve el ``ConfigManager`` inyectado en ``app.state``.

    Se construye una sola vez en el Composition Root
    (``interfaces/web_server/app.py::create_app``) y se comparte
    con todos los routers que lo necesiten (típicamente los que
    invocan casos de uso que requieren mapeo
    ``hw_type → tag_table``, como ``DispSyncInstancesUseCase``
    o ``SyncConstantsFromExcelUseCase``).
    """
    return request.app.state.config_manager


def get_engine(request: Request) -> Engine:
    """Devuelve el ``Engine`` de FBs inyectado en ``app.state``.

    El Composition Root (``interfaces/web_server/app.py::create_app``)
    construye el ``Engine`` con los FBs registrados y lo expone en
    ``app.state.engine``.  Los routers lo recuperan vía ``Depends``.

    NOTA de Fase 2, paso 2.2.1: el router ``/api/v1/plc/fb/...`` está
    creado pero ``app.py`` aún no lo inyecta.  El wiring queda
    pendiente de OK del operario.
    """
    return request.app.state.engine


__all__ = [
    "get_gateway",
    "get_app_state",
    "get_logger",
    "get_progress_tracker",
    "get_config_manager",
    "get_engine",
]
