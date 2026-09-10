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
from core.sse.event_bus import EventBus
from core.sse.stream import router as sse_router
from interfaces.web_server.routers import (
    area_manifests_router,
    areas_router,
    catalog_router,
    diagnostics_router,
    portal_router,
    tia_connection_router,
)
from interfaces.web_server.routers.plc import router as plc_router


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
    """Lifespan del web server: arranca el worker persistente al
    startup y lo cierra al shutdown.

    El ``gateway.start()`` crea un reader task que debe vivir en el
    mismo event loop que uvicorn, por eso va aquí y no en el
    supervisor. Al shutdown se llama ``disconnect()`` para liberar
    los ~200 MB del ``.pyd`` cargado.

    Solo aplica a gateways ``persistent=True`` (modo web); en modo
    1-shot (MCP) se omite con un guard.

    Fase 3, DA-005.5 — además arranca el ``Engine`` (OB1) con los
    7 FBs del área de alimentación. El ``plc_router`` (HTTP) lo
    monta ``create_app`` (no el ``register`` del área) porque
    Starlette matchea rutas en orden de inserción: si el router
    se incluye DESPUÉS del catch-all ``app.mount("/", ...)``,
    el mount intercepta todas las requests y devuelve 404. Si
    el wiring falla, el web server arranca sin FBs activos (los
    endpoints ``/api/v1/plc/fb/...`` devolverán 404); el operario
    verá el error en el log file.
    """
    import logging

    _logger = logging.getLogger(__name__)

    gateway = getattr(app.state, "gateway", None)
    if gateway is not None and getattr(gateway, "persistent", False):
        try:
            await gateway.start()
        except Exception as exc:  # noqa: BLE001
            # No abortamos uvicorn: el operario podrá ver el
            # estado en la UI (``worker_alive=False``, circulo
            # gris) y diagnosticar desde ahi. Logueamos como
            # ERROR para que sea visible en el log file.
            _logger.error(
                "gateway.start() en lifespan fallo: %s: %s. "
                "El web server arranca igualmente, pero el worker "
                "permanente estara muerto. Revisa el log para mas "
                "detalle.",
                type(exc).__name__,
                exc,
            )

    # ── Engine + 7 FBs (DA-005.5) ─────────────────────────────
    # Crea el OB1 y cablea los 7 FBs del área de alimentación
    # (``areas.alimentacion.register``) con sus deps de
    # ``app.state``. La mitad HTTP del wiring (``plc_router``) ya
    # está montada en ``create_app`` ANTES del catch-all de
    # estáticos; aquí solo se ocupa del runtime de los FBs.
    # Si el register falla, los endpoints ``/plc/fb/...`` existirán
    # pero los FBs no estarán registrados (404 por nombre); el
    # resto de la app sigue funcionando (gateway, SSE, áreas, etc.).
    # Defensivo: si ``app.state.event_bus`` falta (típico de tests
    # que usan ``FastAPI()`` directo, sin ``create_app``), se salta
    # el wiring — el lifespan ya era defensivo con ``gateway`` y
    # ahora también con el resto de deps.
    event_bus = getattr(app.state, "event_bus", None)
    if event_bus is not None:
        from core.plc.engine import Engine
        app.state.engine = Engine(
            tick_period_s=0.1, event_bus=event_bus
        )
        from areas.alimentacion import register as register_alimentacion
        try:
            register_alimentacion(app.state.engine, app)
            await app.state.engine.start_loop()
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "Engine/FBs wiring fallo en lifespan: %s: %s. "
                "El web server arranca sin FBs activos; "
                "/api/v1/plc/fb/... daran 404. Revisa el log.",
                type(exc).__name__, exc,
            )
    else:
        _logger.debug(
            "Engine wiring saltado: app.state.event_bus no esta seteado "
            "(tests o paths sin create_app)."
        )

    yield

    # ── Shutdown: parar el loop del Engine. ──────────────────────
    # Idempotente (``stop_loop`` ya lo es). Si el wiring falló en
    # startup y el loop nunca arrancó, esto es un no-op.
    engine = getattr(app.state, "engine", None)
    if engine is not None:
        try:
            await engine.stop_loop()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("engine.stop_loop() fallo: %s", exc)

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
        _logger.warning(
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
    # ── 6. Bus de eventos SSE ──────────────────────────────────────
    # El endpoint ``/api/v1/stream`` (router SSE) lee ``app.state.event_bus``
    # en cada conexión. El wiring de los Singletons (LogBuffer,
    # ProgressTracker, gateway persistente) al bus es responsabilidad
    # del Composition Root externo (1.1.6); aquí solo creamos el bus
    # y lo exponemos para que el endpoint no 500ee.
    app.state.event_bus = EventBus()

    # ── 2. Routers comunes del core (orden estable, alfabético) ───
    # Estos routers son GENÉRICOS: no saben de áreas, viven en el
    # shell web. Las áreas aportan los suyos vía ``AreaRegistry``.
    app.include_router(area_manifests_router)
    app.include_router(areas_router)
    app.include_router(catalog_router)
    app.include_router(diagnostics_router)
    app.include_router(portal_router)
    # Estado del worker OT persistente. La SPA hace polling cada 2s
    # contra ``GET /tia/connection`` y lanza ``POST /tia/connect`` /
    # ``POST /tia/disconnect`` al pulsar el indicador del topbar.
    app.include_router(tia_connection_router)
    # ── 2b. Router SSE (Fase 1 del refactor) ──────────────────────
    # ``GET /api/v1/stream``: Server-Sent Events para reemplazar el
    # polling de logs / progress / tia_state en pasos posteriores.
    # El router ya define ``prefix="/api/v1"`` (1.0.3).
    app.include_router(sse_router)

    # ── 3. Routers aportados por las áreas (Bounded Contexts) ─────
    # Descubre cada ``AreaSpec`` registrada y, si declara
    # ``contributes_routers``, invoca su ``register_routers(app)``.
    # Así añadir un área nueva = crear paquete + AreaSpec, sin tocar
    # este archivo. El área "alimentación" monta aquí los routers
    # ``/api/v1/alimentacion/*``, ``/api/v1/sync/*``, ``/api/v1/excel/*``.
    AreaRegistry.discover().for_each("contributes_routers", app=app)

    # ── 3b. Router PLC FBs (DA-005.5) ─────────────────────────────
    # ``POST/GET /api/v1/plc/fb/{name}/...`` — arranca y consulta el
    # estado de los FBs del Engine. Se monta AQUÍ (entre los routers
    # del área y los estáticos) y NO en el lifespan, porque Starlette
    # matchea rutas en orden de inserción: si se incluye DESPUÉS del
    # catch-all ``app.mount("/", ...)``, el mount intercepta todas
    # las requests y devuelve 404 (causa del bug que el wiring del
    # DA-005.5 descubrió).
    app.include_router(plc_router)

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
