"""Composition Root de la capa web (FastAPI).

``create_app`` es la **única** factoría de la aplicación.
Ensambla los routers ASSEMBLING-LAYER y deja las dependencias
vivas en ``app.state`` para que los ``Depends`` de los routers
puedan recogerlas sin acoplamiento.

NO importa ``siemens_tia_scripting``. Los routers reciben un
``TIAProcessGateway`` ya construido desde el Composition Root
externo (``main.py --web``); esta capa sólo cablea.

Estructura final:

    interfaces/web_server/
    ├── __init__.py            (vacío, marca paquete)
    ├── app.py                  (este archivo, factoría)
    ├── dependencies.py         (inyectores)
    ├── routers/
    │   ├── __init__.py
    │   ├── areas.py            /api/v1/areas
    │   ├── excel.py            /api/v1/excel/...
    │   ├── portal.py           /api/v1/portal/... + /api/v1/plcs
    │   ├── sync.py             /api/v1/sync/...
    │   └── diagnostics.py      /api/v1/logs + /api/v1/state/...
    └── static/                 (SPA Vue 3 servida en /)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles as _BaseStaticFiles

from application.log_buffer import get_log_buffer
from application.state import get_app_state
from infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.routers import (
    areas_router,
    catalog_router,
    diagnostics_router,
    excel_router,
    portal_router,
    sync_router,
)


STATIC_DIR = Path(__file__).parent / "static"


class NoCacheStaticFiles(_BaseStaticFiles):
    """Sirve estáticos con ``Cache-Control: no-store``.

    Razón: durante el desarrollo de la SPA (cambios frecuentes en
    ``js/*.js`` y ``styles.css``), el navegador tiende a cachear
    agresivamente los módulos ESM. Si el usuario edita un ``.js``
    y refresca, el navegador puede mezclar una versión cacheada
    antigua de un módulo con la nueva de otro, provocando errores
    ``does not provide an export named 'X'`` que sólo se arreglan
    con un hard-refresh (Ctrl+Shift+R).

    Con ``no-store`` el navegador siempre pide al servidor y la
    SPA siempre está sincronizada con el código del disco. En
    producción este comportamiento sigue siendo aceptable: la SPA
    es pequeña (~50 KB de JS) y la app se sirve en OT/IT donde la
    latencia no es el cuello de botella.
    """

    def file_response(self, *args, **kwargs) -> FileResponse:  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store"
        return response


def create_app(gateway: TIAProcessGateway) -> FastAPI:
    """Crea la aplicación FastAPI con Composition Root explícito.

    Args:
        gateway: Única instancia de ``TIAProcessGateway`` (creada
            por el Composition Root externo, **NO** se re-instancia
            aquí para no duplicar el RCW de TIA Portal).
    """
    app = FastAPI(title="ZC Automation Suite - Web Server")

    # ── 1. Inyección de estado (Composition Root → app.state) ─────
    # Todos los routers leen estas dependencias vía ``Depends``.
    app.state.gateway = gateway
    app.state.app_state = get_app_state()
    app.state.logger = get_log_buffer()
    # ``ConfigManager`` se construye aquí (Composition Root) y se
    # expone a los routers que lo necesiten (ej. ``sync.py`` que
    # lo pasa a ``SyncDispositivosInstancesUseCase``).
    from infrastructure.config_manager import ConfigManager
    app.state.config_manager = ConfigManager("infrastructure/config.json")

    # ── 2. Registro de routers (Clean Architecture) ────────────────
    app.include_router(excel_router)
    app.include_router(portal_router)
    app.include_router(sync_router)
    app.include_router(diagnostics_router)
    app.include_router(areas_router)
    app.include_router(catalog_router)

    # ── 4. SPA estática (Vue 3) ─────────────────────────────────────
    if STATIC_DIR.exists():
        app.mount(
            "/",
            NoCacheStaticFiles(directory=str(STATIC_DIR), html=True),
            name="static",
        )

    return app


__all__ = ["create_app"]
