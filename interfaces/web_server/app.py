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
    │   ├── excel.py            /api/v1/excel/...
    │   ├── portal.py           /api/v1/portal/... + /api/v1/plcs
    │   ├── sync.py             /api/v1/sync/...
    │   └── diagnostics.py      /api/v1/logs + /api/v1/state/...
    └── static/                 (SPA Vue 3 servida en /)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from application.log_buffer import LogBuffer, get_log_buffer
from application.state import get_app_state
from infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.routers import (
    diagnostics_router,
    excel_router,
    portal_router,
    sync_router,
)


STATIC_DIR = Path(__file__).parent / "static"


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

    # ── 2. Registro de routers (Clean Architecture) ────────────────
    app.include_router(excel_router)
    app.include_router(portal_router)
    app.include_router(sync_router)
    app.include_router(diagnostics_router)

    # ── 3. Hook de compatibilidad: ``app.state.logger`` puede
    # ser substituida por otra instancia (ej. en tests). Esta
    # constante evita que olviden reasignar ``Logger``.
    _ = LogBuffer  # noqa: F841 (referencia explícita para lint)

    # ── 4. SPA estática (Vue 3) ─────────────────────────────────────
    if STATIC_DIR.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(STATIC_DIR), html=True),
            name="static",
        )

    return app


__all__ = ["create_app"]
