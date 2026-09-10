"""Composition Root de FastAPI para zc-automation-suite.

Fase 1: Engine + FBs trasversales + router generico de PLC.

Esta es la factoría única de la app. Ensambla los routers de la capa
``core/web/routers/``, monta la SPA estática en ``/``, instancia el
``FB_ConexionTIA`` con la fachada del worker y arranca el Engine en
el ``lifespan``.

Convenciones (.clinerules §5, §6, §9; AGENTS.md):
  - **Routers en orden alfabético** al incluirlos.
  - La app NO importa ``siemens_tia_scripting`` (ver §1): el SDK de
    Siemens solo se carga desde ``core/worker/`` (a través de la
    fachada, en una fase posterior).
  - El ``lifespan`` arranca el Engine al startup y lo para al
    shutdown. El shutdown también cierra la fachada del worker
    (leccion X2 de ``PLC_IE_61131_GREENFIELD.md`` §0.4: si no, el
    ``.pyd`` de Siemens queda en memoria ~200 MB zombi).
"""
from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.plc.plc import DB_ESTADO, ENGINE, FB_ConexionTIA
from core.web.routers.areas import router as areas_router
from core.web.routers.plc import router as plc_router
from core.web.routers.spike import router as spike_router
from core.worker.worker_bridge import WorkerBridge


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan de FastAPI: arranca el Engine al startup, lo para al
    shutdown.

    Startup:
      1. Instancia la fachada del worker (en Fase 1 es el stub de
         ``core/worker/worker_bridge.py``; el agente ``tia-ot-worker``
         lo sustituye por la implementacion real en su commit).
      2. Crea el ``FB_ConexionTIA`` con la fachada + la DB trasversal
         y lo registra en el Engine. Usamos ``register_fb`` con la
         clave ``"ConexionTIA"`` (misma que la convencion del proyecto).
      3. Arranca el loop del Engine (``start_loop()``). La task
         tickea FBs cada 100 ms.

    Shutdown:
      1. Para el loop del Engine (``stop_loop()``). Espera a que la
         task termine limpiamente.
      2. Cierra la fachada del worker (``shutdown()`` si existe;
         si no, ``detach()`` como fallback). Esto es la leccion X2:
         sin shutdown, el subproceso del worker queda zombi con el
         ``.pyd`` de Siemens cargado.

    Note:
        El parametro ``app`` no se usa directamente; FastAPI lo pasa
        por convencion del ``lifespan`` protocol. Lo dejamos nombrado
        para que el ``@asynccontextmanager`` lo reconozca.
    """
    # ── Startup ─────────────────────────────────────────────────────
    # Usamos el ``WorkerBridge`` real (``core/worker/worker_bridge.py``):
    # arranca un subproceso persistente con ``siemens_tia_scripting``
    # lazy-import dentro del subproceso. La interfaz
    # (``WorkerBridgeProtocol``) es identica a la del mock que usamos
    # durante el desarrollo de Fase 1, asi que el ``FB_ConexionTIA`` y
    # los routers no cambian.
    bridge = WorkerBridge()
    await bridge.start()  # idempotente: arranca el subproceso ``worker_tia``.
    fb_conexion = FB_ConexionTIA(bridge=bridge, db=DB_ESTADO)
    ENGINE.register_fb("ConexionTIA", fb_conexion)
    ENGINE.start_loop()

    try:
        yield
    finally:
        # ── Shutdown ─────────────────────────────────────────────────
        # 1) Parar el loop. Esto espera a que la task termine.
        await ENGINE.stop_loop()
        # 2) Cerrar la fachada. ``WorkerBridge.shutdown()`` envia
        # ``detach_portal`` al subproceso, cierra stdin, espera al
        # subproceso y libera el ``.pyd`` de Siemens (leccion X2:
        # si no, queda ~200 MB zombi en memoria al cerrar la app).
        await bridge.shutdown()


def create_app() -> FastAPI:
    """Factoría de la app FastAPI.

    Returns:
        Instancia de FastAPI con:
          - El router generico de PLC bajo ``/api/v1``.
          - El router de areas bajo ``/api/v1`` (catalogo + manifest,
            introducido en Fase 3 con el area ``tia_conexion``).
          - El router de spike bajo ``/api/v1`` (sigue presente
            para que el ``.exe`` empaquetado de Fase 0.5 siga
            funcionando hasta que se retire en Fase 5).
          - El lifespan que arranca/para el Engine (ver arriba).
          - La SPA estática montada en ``/``.
    """
    app = FastAPI(
        title="zc-automation-suite",
        version="0.1.0",
        lifespan=lifespan,
    )
    # Registrar las areas operativas ANTES de los routers de API.
    # El area ``tia_conexion`` anade su ``AreaSpec`` al Catalogo
    # (registry en memoria) desde su ``register()``. En Fase 4+
    # se anyadiran mas areas aqui, en el orden en que la SPA las
    # quiera pintar (catalogo respeta el orden de registro).
    from areas.tia_conexion import register as register_tia_conexion
    register_tia_conexion(ENGINE, app)

    # Routers en orden alfabetico (convencion AGENTS.md).
    # ``areas`` antes que ``plc`` antes que ``spike``: orden
    # alfabetico.
    app.include_router(areas_router, prefix="/api/v1")
    app.include_router(plc_router, prefix="/api/v1")
    app.include_router(spike_router, prefix="/api/v1")
    # Areas frontend static: sirve los ``.js`` de ``areas/<area>/frontend/``.
    # El manifest (router /api/v1/areas/{id}/manifest) devuelve URLs
    # absolutas tipo ``/areas/<area>/frontend/components/<X>.js``; el
    # ``area-loader.js`` del shell SPA hace ``import(url)`` sobre ellas.
    # ``html=False`` porque servimos .js, no HTML (no listar directorios).
    # IMPORTANTE: este mount va ANTES del mount ``/`` de la SPA, porque
    # ``/`` captura todo lo que no haya matcheado antes.
    areas_static = Path(__file__).parent.parent.parent / "areas"
    if areas_static.is_dir():
        app.mount(
            "/areas",
            StaticFiles(directory=str(areas_static), html=False),
            name="areas-static",
        )
    # SPA estatica: sirve /, /styles.css, /js/main.js, etc.
    # html=True hace que GET / sirva index.html automaticamente.
    # IMPORTANTE: este mount va al FINAL, despues de los routers API
    # y despues del mount /areas (captura todo lo demas).
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
