"""Composition Root de FastAPI para zc-automation-suite.

Fase 0.5 spike: SSE mínimo para validar PyInstaller.

Esta es la factoría única de la app. Ensambla los routers de la capa
``core/web/routers/`` y deja la instancia lista para que uvicorn la
importe (``uvicorn core.web.app:app``) o para que ``main_tray.py`` la
lance como subproceso en background.

Convenciones (.clinerules §6, §9; AGENTS.md):
  - **Routers en orden alfabético** al incluirlos.
  - La app NO importa ``siemens_tia_scripting`` (ver §1): el SDK de
    Siemens solo se carga desde ``core/worker/`` en una fase posterior.
  - Sin estado global mutable: el ``Engine`` y ``WorkerBridge`` llegarán
    en Fase 1 y se inyectarán vía ``Depends`` (AGENTS.md §3).
"""
from __future__ import annotations

from fastapi import FastAPI

from core.web.routers.spike import router as spike_router


def create_app() -> FastAPI:
    """Factoría de la app FastAPI.

    Returns:
        Instancia de FastAPI con el router de spike montado bajo
        ``/api/v1``. Los routers específicos de cada Bounded Context
        (``areas/<area>/routers.py``) se montarán en fases posteriores.
    """
    app = FastAPI(
        title="zc-automation-suite",
        version="0.1.0",
    )
    # Routers en orden alfabético (convención AGENTS.md).
    app.include_router(spike_router, prefix="/api/v1")
    return app


# Instancia a nivel de módulo — la convención habitual de FastAPI para
# que ``uvicorn core.web.app:app`` y ``from core.web.app import app``
# funcionen directamente. Tests usan esta instancia con TestClient.
app = create_app()


def main() -> None:
    """Entry point para ``python -m core.web.app`` (debug sin bandeja)."""
    import uvicorn

    uvicorn.run(
        "core.web.app:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
