"""Composition Root de FastAPI para zc-automation-suite.

Fase 0.5 spike: SSE mínimo para validar PyInstaller.

Esta es la factoría única de la app. Ensambla los routers de la capa
``core/web/routers/``, monta la SPA estática en ``/``, y deja la
instancia lista para que uvicorn la importe (``uvicorn core.web.app:app``)
o para que ``main_tray.py`` la lance como subproceso en background.

Convenciones (.clinerules §6, §9; AGENTS.md):
  - **Routers en orden alfabético** al incluirlos.
  - La app NO importa ``siemens_tia_scripting`` (ver §1): el SDK de
    Siemens solo se carga desde ``core/worker/`` en una fase posterior.
  - Sin estado global mutable: el ``Engine`` y ``WorkerBridge`` llegarán
    en Fase 1 y se inyectarán vía ``Depends`` (AGENTS.md §3).
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.web.routers.spike import router as spike_router


def _static_dir() -> Path:
    """Resuelve el directorio de estáticos.

    En desarrollo (``python main_tray.py``): el directorio está junto al
    código, ``<repo>/interfaces/web_server/static/``.

    En frozen (PyInstaller): los estáticos se desempaquetan en
    ``sys._MEIPASS/static/`` por el ``--add-data`` de ``build_exe.py``.

    Returns:
        Path al directorio de estáticos. Si no existe (caso patológico),
        cae a un directorio vacío ``./static``.
    """
    # 1) Frozen: PyInstaller pone _MEIPASS en sys._MEIPASS.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "static"
        if candidate.is_dir():
            return candidate
    # 2) Desarrollo: 4 niveles arriba desde este archivo.
    #    core/web/app.py → core/web/ → core/ → <repo>/ → interfaces/web_server/static/
    candidate = Path(__file__).parent.parent.parent / "interfaces" / "web_server" / "static"
    if candidate.is_dir():
        return candidate
    # 3) Fallback: directorio vacio junto al codigo.
    return Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Factoría de la app FastAPI.

    Returns:
        Instancia de FastAPI con:
          - El router de spike bajo ``/api/v1``.
          - La SPA estática montada en ``/`` (catch-all, ``html=True`` para
            servir ``index.html`` en ``GET /``).
    """
    app = FastAPI(
        title="zc-automation-suite",
        version="0.1.0",
    )
    # Routers en orden alfabético (convención AGENTS.md).
    app.include_router(spike_router, prefix="/api/v1")
    # SPA estática: sirve /, /styles.css, /js/main.js, etc.
    # html=True hace que GET / sirva index.html automáticamente.
    # IMPORTANTE: este mount va al FINAL, después de los routers API.
    app.mount("/", StaticFiles(directory=str(_static_dir()), html=True), name="static")
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
