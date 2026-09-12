"""App Flask sync para el modelo OB1 (Fase 4 / paso 4.4.1).

Factory ``create_app()`` retorna una ``Flask`` configurada con:
  - ``/ping``: health check (latencia directa, sin OB1).
  - ``/cycle_count``: lee engine.cycle_count del hilo OB1 principal.
  - ``/stream``: SSE basico emitiendo heartbeats cada 500ms (placeholder;
    se reemplaza por ``/api/v1/stream`` migrado en 4.4.x).

Trade-off aceptado (DA-014): Flask dev server es single-threaded, lo
que significa que requests HTTP serializan contra el OB1 main loop.
Esto elimina la complejidad de asyncio.subprocess + ProactorEventLoop
a costa de perder paralelismo I/O. Para la carga esperada (1 operario,
<10 req/s) es aceptable.

Estado de la migracion (sept-2026): skeleton minimo. Los 7 routers
existentes en ``interfaces/web_server/routers/`` siguen en FastAPI.
La migracion a Flask blueprints sera en pasos 4.4.2+ (futuras
conversaciones; este paso solo prueba que ``create_app`` arranca).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from flask import Flask, Response, jsonify

from core.infrastructure.tia_client import tia_client as default_tia_client
from core.plc.engine import Engine
from core.sse.event_bus_sync import EventBusSync

logger = logging.getLogger(__name__)


def create_app(
    tia_client: Any = None,
    engine: Engine | None = None,
    event_bus: EventBusSync | None = None,
) -> Flask:
    """Factory: retorna Flask app configurada para OB1.

    Args:
        tia_client: SyncTIAClient. Default: singleton global.
        engine: Engine. Default: se crea uno nuevo.
        event_bus: EventBusSync. Default: se crea uno nuevo.

    Inyeccion explicita para tests; production usa los singletons.
    """
    app = Flask(__name__)
    _tia = tia_client if tia_client is not None else default_tia_client
    _engine = engine if engine is not None else Engine()
    _bus = event_bus if event_bus is not None else EventBusSync()

    # Stash para que endpoints lo lean (sin globals para tests).
    app.config["TIA_CLIENT"] = _tia
    app.config["ENGINE"] = _engine
    app.config["EVENT_BUS"] = _bus

    # ----------------------------------------------------------- endpoints
    @app.get("/ping")
    def ping():
        """Health check: latencia directa, sin OB1."""
        return jsonify({"pong": True})

    @app.get("/cycle_count")
    def cycle_count():
        """Counter del engine del hilo OB1 principal.

        El engine es sync (4.2.1) pero se ticka desde otro thread;
        lectura cross-thread de un int es GIL-atomic en CPython.
        """
        return jsonify({"cycles": _engine.cycle_count})

    @app.get("/stream")
    def stream():
        """SSE basico: emite un heartbeat cada 500ms.

        Lee del EventBusSync del OB1 main loop. Si no hay eventos,
        emite ': keepalive\\n\\n' (comment line de SSE) para mantener
        la conexion viva (mitigacion equivalente al DA-012 SSE keepalive).
        """
        subscriber_queue = _bus.subscribe()
        keepalive_s = 0.5

        def gen():
            try:
                while True:
                    try:
                        event = subscriber_queue.get(timeout=keepalive_s)
                    except Exception:
                        # Timeout: emitimos keepalive (no genera evento).
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                _bus.unsubscribe(subscriber_queue)

        return Response(gen(), mimetype="text/event-stream")

    logger.info(
        "create_app: Flask OB1 inicializada (engine=%s, bus=%s)",
        type(_engine).__name__,
        type(_bus).__name__,
    )

    # Registrar blueprints migrados en pasos 4.4.2+.
    # Si la importacion falla (blueprint no migrado aun), seguimos sin
    # el — los endpoints viejos en FastAPI siguen disponibles mientras
    # la migracion no sea completa.
    try:
        from interfaces.web_server.routers.tia_connection_ob1 import (
            bp as tia_connection_bp,
        )
        app.register_blueprint(tia_connection_bp)
        logger.info("create_app: blueprint tia_connection_ob1 registrado.")
    except ImportError:
        logger.debug("create_app: blueprint tia_connection_ob1 no disponible.")

    return app


__all__ = ["create_app"]
