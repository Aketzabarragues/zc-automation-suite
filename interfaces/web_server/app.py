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
    │   ├── catalog.py          /api/v1/catalog
    │   ├── portal.py           /api/v1/portal/... + /api/v1/plcs
    │   └── diagnostics.py      /api/v1/logs + /api/v1/state/...
    └── static/                 (SPA Vue 3 servida en /)

Los routers específicos de cada Bounded Context (alimentación:
``/api/v1/alimentacion/*``, ``/api/v1/sync/*``, ``/api/v1/excel/*``)
se descubren dinámicamente vía ``AreaRegistry.for_each("contributes_routers", app=app)``
y ya NO se importan directamente aquí.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles as _BaseStaticFiles

from core.application.area_registry import AreaRegistry
from core.application.log_buffer import get_log_buffer
from core.application.progress_buffer import get_progress_tracker
from core.application.state import get_app_state
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.routers import (
    area_manifests_router,
    areas_router,
    catalog_router,
    diagnostics_router,
    portal_router,
    tia_connection_router,
)


STATIC_DIR = Path(__file__).parent / "static"
# Directorio donde viven los frontends de las áreas (componentes Vue 3
# y manifest). El ``manifest.py`` de cada área apunta a ``/static/areas/<area>/...``
# con prefijo ``/static/areas/<area>/frontend/``; el mount de abajo sirve
# exactamente ese árbol bajo ``/static/areas/``.
#
# La ruta cambia entre desarrollo y .exe (frozen):
#   * **Desarrollo**: ``Path(__file__).parent.parent.parent / "areas"``
#     apunta a ``<raíz>/areas/`` (donde están los ``.js`` del área).
#   * **Frozen** (PyInstaller --onefile): los archivos del frontend del
#     área están bundleados en ``sys._MEIPASS/interfaces/web_server/
#     static/areas/alimentacion/`` (ver ``build_exe.py::PROJECT_DATA_FILES``).
#     Por tanto, en el .exe, ``AREAS_STATIC_DIR`` debe ser
#     ``STATIC_DIR / "areas"`` (que coincide con la ruta del bundle).
# Si no se hace este cambio, en el .exe el mount serviría un directorio
# inexistente y los ``import()`` de la SPA fallarían con
# ``Failed to fetch dynamically imported module``.
if getattr(sys, "frozen", False):
    AREAS_STATIC_DIR = STATIC_DIR / "areas"
else:
    # ``Path(__file__).parent.parent.parent`` = raíz del repo
    # (app.py está en ``interfaces/web_server/app.py``).
    AREAS_STATIC_DIR = Path(__file__).parent.parent.parent / "areas"


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


@asynccontextmanager
async def _tia_lifespan(app: FastAPI):
    """Lifespan que arranca el worker persistente al startup y lo
    cierra al shutdown (auditoría X2 + fix de event loop post-implementación).

    **Startup (este PR, sept-2026 round 2):**

    Si el gateway es persistente (``persistent=True``), llama
    ``await gateway.start()`` ANTES del ``yield``. Esto es
    crítico y por eso vive en el lifespan (no en
    ``WebServiceSupervisor._serve_once``): el ``gateway.start()``
    crea un reader task en asyncio, y ese reader task DEBE vivir
    en el mismo event loop que uvicorn para que sobreviva
    cuando el operario llame a ``connect()`` desde un endpoint
    HTTP. Si lo lanzamos en un loop efímero
    (``asyncio.run(gateway.start())`` desde el supervisor), ese
    loop se cierra al retornar y el reader task se cancela.
    El síntoma en producción era
    ``RuntimeError: Reader task del worker persistente no esta vivo``
    al pulsar "Conectar" 10 s después del startup, aunque
    ``worker_alive=True``.

    **Shutdown (auditoría X2):**

    Tras el ``yield``, llama ``await gateway.disconnect()`` para
    que el worker persistente NO quede zombi (~200 MB con
    ``siemens_tia_scripting.pyd`` cargado) hasta que se cierre
    TIA o se mate el proceso manualmente.

    Solo aplica a gateways persistentes (modo web). Modo 1-shot
    (MCP) usa gateways ``persistent=False`` y ``disconnect()``
    lanzaría ``TIAConnectionError``; lo saltamos con un guard.

    Cubre el path canónico: ``python main.py --web`` y
    ``WebServiceSupervisor._serve_once`` (el supervisor también
    tiene su propia red de seguridad en el ``finally``).
    """
    import logging

    # ── Startup ───────────────────────────────────────────────
    # Arrancamos el worker persistente AQUÍ (no antes) para que
    # el reader task viva en el mismo loop que uvicorn. Ver
    # docstring para el razonamiento completo.
    gateway = getattr(app.state, "gateway", None)
    if gateway is not None and getattr(gateway, "persistent", False):
        try:
            await gateway.start()
        except Exception as exc:  # noqa: BLE001
            # No abortamos uvicorn: el operario podrá ver el
            # estado en la UI (``worker_alive=False``, circulo
            # gris) y diagnosticar desde ahi. Logueamos como
            # ERROR para que sea visible en el log file.
            logging.getLogger(__name__).error(
                "gateway.start() en lifespan fallo: %s: %s. "
                "El web server arranca igualmente, pero el worker "
                "permanente estara muerto. Revisa el log para mas "
                "detalle.",
                type(exc).__name__,
                exc,
            )

    yield

    # ── Shutdown (auditoría X2) ──────────────────────────────
    # ``gateway`` puede haber cambiado (no deberia, pero defensa):
    # lo re-leemos de ``app.state``.
    gateway = getattr(app.state, "gateway", None)
    if gateway is None:
        return
    if not getattr(gateway, "persistent", False):
        return
    try:
        await gateway.disconnect()
    except Exception as exc:  # noqa: BLE001
        # No enmascarar el motivo original del shutdown. Logueamos
        # y dejamos que uvicorn termine.
        logging.getLogger(__name__).warning(
            "gateway.disconnect() en lifespan fallo: %s", exc
        )


def create_app(gateway: TIAProcessGateway) -> FastAPI:
    """Crea la aplicación FastAPI con Composition Root explícito.

    Args:
        gateway: Única instancia de ``TIAProcessGateway`` (creada
            por el Composition Root externo, **NO** se re-instancia
            aquí para no duplicar el RCW de TIA Portal).
    """
    app = FastAPI(
        title="ZC Automation Suite - Web Server",
        lifespan=_tia_lifespan,
    )

    # ── 1. Inyección de estado (Composition Root → app.state) ─────
    # Todos los routers leen estas dependencias vía ``Depends``.
    app.state.gateway = gateway
    app.state.app_state = get_app_state()
    app.state.logger = get_log_buffer()
    # ``ProgressTracker`` Singleton: espejo del patrón de ``logger``.
    # Lo inyectamos en ``app.state`` para que los routers que lo
    # necesiten (excel, portal, diagnostics, sync) lo obtengan vía
    # ``Depends``. Los use cases lo reciben por constructor.
    app.state.progress_tracker = get_progress_tracker()
    # ``ConfigManager`` se construye aquí (Composition Root) y se
    # expone a los routers que lo necesiten (ej. ``sync.py`` que
    # lo pasa a ``DispSyncInstancesUseCase``). Sin ``config_path``
    # explícito: usa ``resolve_config_path`` (frozen: copia el
    # bundleado a ``<exe_dir>/config/`` en primera ejecución; dev:
    # usa el del repo).
    from core.infrastructure.config_manager import ConfigManager
    app.state.config_manager = ConfigManager()

    # ── 2. Routers comunes del core (orden estable, alfabético) ───
    # Estos routers son GENÉRICOS: no saben de áreas, viven en el
    # shell web. Las áreas aportan los suyos vía ``AreaRegistry``.
    app.include_router(area_manifests_router)
    app.include_router(areas_router)
    app.include_router(catalog_router)
    app.include_router(diagnostics_router)
    app.include_router(portal_router)
    # PR 5a: estado del worker OT persistente. La SPA hace polling
    # cada 2s contra ``GET /tia/connection`` y lanza ``POST
    # /tia/connect`` / ``POST /tia/disconnect`` al pulsar el
    # indicador del topbar. Logica reconnect/disconnect en PR 6.
    app.include_router(tia_connection_router)

    # ── 3. Routers aportados por las áreas (Bounded Contexts) ─────
    # Descubre cada ``AreaSpec`` registrada y, si declara
    # ``contributes_routers``, invoca su ``register_routers(app)``.
    # Así añadir un área nueva = crear paquete + AreaSpec, sin tocar
    # este archivo. El área "alimentación" monta aquí los routers
    # ``/api/v1/alimentacion/*``, ``/api/v1/sync/*``, ``/api/v1/excel/*``.
    AreaRegistry.discover().for_each("contributes_routers", app=app)

    # ── 4. Estáticos de las áreas ────────────────────────────────────
    # IMPORTANTE: este mount va ANTES del catch-all de la SPA. Si va
    # después, el ``app.mount("/", ...)`` captura todo y el manifest
    # queda shadowed. Starlette procesa los mounts en orden de
    # inserción: el último gana, pero el catch-all ``/`` siempre
    # captura si no hay match más específico antes.
    if AREAS_STATIC_DIR.exists():
        app.mount(
            "/static/areas",
            NoCacheStaticFiles(directory=str(AREAS_STATIC_DIR), html=False),
            name="areas-static",
        )

    # ── 5. SPA estática (Vue 3) ─────────────────────────────────────
    if STATIC_DIR.exists():
        app.mount(
            "/",
            NoCacheStaticFiles(directory=str(STATIC_DIR), html=True),
            name="static",
        )

    return app


__all__ = ["create_app"]
