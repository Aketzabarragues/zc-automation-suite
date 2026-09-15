"""Factory Flask para el modelo OB1.

Retorna una ``Flask`` configurada con:
  - 3 endpoints base (``/ping``, ``/cycle_count``, ``/stream``).
  - 7 blueprints del shell (``/api/v1/...``).
  - SPA estática servida en ``/`` (catch-all a ``index.html`` para
    rutas client-side).
  - Estáticos de áreas en ``/static/areas/<area>/...`` (apunta a
    ``<repo_root>/areas/<area>/...``).

El werkzeug se levanta con ``threaded=True`` desde
``core.launcher.main_supervisor``: el SSE de larga vida no bloquea
las demás requests HTTP. OK para 1 operario (<10 req/s).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, send_from_directory

from core.infrastructure.config.config_manager import ConfigManager
from core.infrastructure.tia.tia_loop import tia_client as default_tia_client
from core.composition.plc_engine import Engine
from core.runtime.sse.sse_event_bus_sync import EventBusSync

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
AREAS_STATIC_DIR = Path(__file__).parent.parent.parent / "areas"  # <repo_root>/areas


def create_app(
    tia_client: Any = None,
    engine: Engine | None = None,
    event_bus: EventBusSync | None = None,
    app_state: Any = None,
    config_manager: Any = None,
    log_buffer: Any = None,
    progress_tracker: Any = None,
) -> Flask:
    """Crea la Flask app con endpoints base + blueprints + SPA estática.

    Args:
        tia_client: SyncTIAClient. Default: singleton global.
        engine: Engine. Default: se crea uno nuevo.
        event_bus: EventBusSync. Default: se crea uno nuevo.
        app_state / config_manager / log_buffer / progress_tracker:
            legacy singletons. Si None, lazy al primer uso desde
            los endpoints (sin forzar import en ``create_app``).
    """
    app = Flask(__name__, static_folder=None)  # servimos manualmente
    # Preservar el orden de insercion de los dicts al serializar a JSON.
    # Flask 3.x tiene app.json.sort_keys = True por defecto, lo que rompe
    # el orden del sidebar (manifest de areas: landing / def / disp / proc
    # se serializaba como def / disp / landing / proc). Tambien afecta a
    # progress events, log buffer, TIA state, etc. — todos deberian
    # respetar el orden natural del codigo Python.
    app.json.sort_keys = False
    _tia = tia_client if tia_client is not None else default_tia_client
    _engine = engine if engine is not None else Engine()
    _bus = event_bus if event_bus is not None else EventBusSync()

    # Resolucion lazy: si no se inyectan, los resolvemos al primer
    # acceso desde un endpoint. Asi create_app() no fuerza la carga
    # de modulos legacy si el caller solo quiere los endpoints OB1.
    def _resolve_lazy(provided, import_path, factory_name):
        if provided is not None:
            return provided
        from importlib import import_module
        mod = import_module(import_path)
        return getattr(mod, factory_name)()

    app.config["TIA_CLIENT"] = _tia
    app.config["ENGINE"] = _engine
    app.config["EVENT_BUS"] = _bus
    # ConfigManager: eager. Si no se inyecta, se crea uno nuevo (singleton
    # de ConfigManager se evita a proposito para que tests y supervisor
    # tengan control explicito de la instancia).
    if config_manager is None:
        config_manager = ConfigManager()
    app.config["CONFIG_MANAGER"] = config_manager
    app.config["_LAZY_APP_STATE"] = lambda: _resolve_lazy(
        app_state, "core.runtime.app_state", "get_app_state"
    )
    app.config["_LAZY_LOG_BUFFER"] = lambda: _resolve_lazy(
        log_buffer,
        "core.runtime.log_buffer",
        "get_log_buffer",
    )
    app.config["_LAZY_PROGRESS_TRACKER"] = lambda: _resolve_lazy(
        progress_tracker,
        "core.runtime.progress_buffer",
        "get_progress_tracker",
    )

    @app.get("/ping")
    def ping():
        """Health check: latencia directa, sin OB1."""
        return jsonify({"pong": True})

    @app.get("/cycle_count")
    def cycle_count():
        """Counter del engine del main loop.

        Lectura cross-thread de un int es GIL-atomic en CPython.
        """
        return jsonify({"cycles": _engine.cycle_count})

    @app.get("/stream")
    def stream():
        """SSE: eventos del main loop + keepalive cada 500ms."""
        subscriber_queue = _bus.subscribe()
        keepalive_s = 0.5

        def gen():
            try:
                while True:
                    try:
                        event = subscriber_queue.get(timeout=keepalive_s)
                    except Exception:
                        # Timeout: keepalive (comment line de SSE).
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                _bus.unsubscribe(subscriber_queue)

        return Response(gen(), mimetype="text/event-stream")

    # ── Estáticos de áreas (Vue components del área) ───────────
    # El manifest del área devuelve URLs ``/static/areas/<area>/frontend/...``
    # que apuntan a ``<repo_root>/areas/<area>/frontend/...``.
    if AREAS_STATIC_DIR.is_dir():
        @app.get("/static/areas/<area>/<path:filename>")
        def area_static(area: str, filename: str):
            """Sirve los estáticos del área (manifest, components, lib)."""
            target = AREAS_STATIC_DIR / area / filename
            if target.is_file():
                return send_from_directory(str(AREAS_STATIC_DIR / area), filename)
            from flask import abort
            abort(404)

    # ── SPA estática (Vue 3) ─────────────────────────────────────
    if STATIC_DIR.is_dir():
        @app.get("/<path:filename>")
        def spa_static(filename: str):
            """Sirve estáticos de la SPA o cae a index.html para rutas SPA.

            Reglas:
              - ``/api/...``: 404 (blueprints cubren las válidas).
              - Path con extension (``/styles.css``, ``/js/main.js``):
                404 si no existe.
              - Path sin extension (``/dashboard``, ``/login``): cae a
                ``index.html`` (Vue Router resuelve en el cliente).
            """
            if filename.startswith("api/"):
                from flask import abort
                abort(404)
            target = STATIC_DIR / filename
            if target.is_file():
                return send_from_directory(STATIC_DIR, filename)
            # SPA fallback solo para paths sin extension.
            if "." not in filename.rsplit("/", 1)[-1]:
                return send_from_directory(STATIC_DIR, "index.html")
            from flask import abort
            abort(404)

        @app.get("/")
        def spa_root():
            return send_from_directory(STATIC_DIR, "index.html")
    else:
        logger.warning("create_app: STATIC_DIR no existe; SPA no servida.")

    # ── Blueprints del shell ────────────────────────────────────
    _register_blueprints(app)

    # ── Routers aportados por las areas (AreaSpec.contributes_routers)
    # Cada area registra su blueprint aqui (ej. alimentacion expone
    # /api/v1/state/dispositivos desde su ``dispositivos_router``).
    # El shell no sabe que areas concretas existen; el AreaRegistry
    # las descubre y les pasa la ``app``.
    from core.composition.app_area_registry import AreaRegistry
    AreaRegistry.discover().for_each("contributes_routers", app=app)

    logger.info(
        "create_app: Flask OB1 inicializada (engine=%s, bus=%s)",
        type(_engine).__name__, type(_bus).__name__,
    )
    return app


def _register_blueprints(app: Flask) -> None:
    """Registra los blueprints del shell. Si alguno no esta disponible
    (migracion en curso), lo loggea y sigue.

    Algunos modulos exponen mas de un blueprint (``plc`` tiene ``bp``
    para FBs y ``bp_blocks`` para cache de bloques del PLC). Aqui
    se registran todos los que exporten (``__all__``); los demas se
    saltan sin error.
    """
    blueprint_modules = [
        "tia_connection",
        "diagnostics",
        "area_manifests",
        "catalog",
        "portal",
        "plc",
        "areas",
    ]
    for name in blueprint_modules:
        try:
            from importlib import import_module
            mod = import_module(f"core.web_server.routers.{name}")
            for attr in getattr(mod, "__all__", ["bp"]):
                bp = getattr(mod, attr, None)
                if bp is not None:
                    app.register_blueprint(bp)
                    logger.info(
                        "create_app: blueprint %s.%s registrado.",
                        name, attr,
                    )
        except ImportError as exc:
            logger.warning(
                "create_app: blueprint %s no disponible (%s).", name, exc
            )


__all__ = ["create_app"]
