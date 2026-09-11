"""core.sse.stream — endpoint SSE ``GET /api/v1/stream``.

Fase 1, paso 1.0.4: integra ``EventBus``. El endpoint se subscribe
al bus del app state (``app.state.event_bus``), emite el snapshot
inicial y luego retransmite cada evento del bus como
``data: <json>\\n\\n``.

El cliente cancela la response al desconectar; el generator
desuscribe del bus en ``finally``.

DA-011: el snapshot inicial ya no es un placeholder hardcodeado;
se construye con ``Engine.snapshot()`` (registros de FBs +
``nStep``/``error_msg`` actuales). Defensivo: si no hay engine
en ``app.state`` (tests sin lifespan, paths sin ``create_app``),
devuelve el placeholder histórico.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from core.plc.engine import Engine
from core.sse.event_bus import EventBus

_dbg = logging.getLogger("zc.debug.da012")

# DA-012: keepalive SSE. Patron estandar de SSE en produccion.
# Yield un comentario ':' cada N segundos para forzar a uvicorn a
# flushear bytes al socket TCP. Sin esto, en Windows con un subprocess
# worker con PIPE handles, uvicorn retiene el PRIMER chunk del
# streaming response en su buffer interno (quirk documentado del
# ProactorEventLoop + multiples PIPE handles) y el cliente recibe
# 0 bytes durante 10-30s hasta que el buffer drena o se cierra la
# conexion. Override por env: ZC_SSE_KEEPALIVE_SECONDS (default 15).
KEEPALIVE_SECONDS = float(os.environ.get("ZC_SSE_KEEPALIVE_SECONDS", "15.0"))


def _format_sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


def _build_snapshot(engine: Optional[Engine]) -> dict[str, Any]:
    """Snapshot inicial del SSE. Defensivo: si no hay engine
    (tests sin lifespan, o la app se monta sin ``create_app``),
    devuelve el placeholder vacío histórico para no romper.

    El ``type`` se añade SIEMPRE (sea real o placeholder) para
    que el cliente pueda ramificar el handler sin None-checks.
    """
    if engine is None:
        return {"type": "snapshot", "dbs": {}, "fbs": {}}
    snap = engine.snapshot()
    snap["type"] = "snapshot"
    return snap


async def _stream(
    bus: EventBus, engine: Optional[Engine] = None
) -> AsyncIterator[bytes]:
    _dbg.debug("_stream entry: suscribiendo a bus")
    queue = bus.subscribe()
    _dbg.debug(
        "_stream: subscribed OK (queue id=%s, subscribers=%d)",
        id(queue),
        bus.subscriber_count(),
    )
    try:
        # 1) Snapshot inicial (engine real o placeholder defensivo).
        snapshot = _build_snapshot(engine)
        _dbg.debug(
            "_stream: snapshot construido (fbs=%d dbs=%d)",
            len(snapshot.get("fbs", {})),
            len(snapshot.get("dbs", {})),
        )
        yield _format_sse(snapshot)
        _dbg.debug(
            "_stream: PRIMER yield snapshot enviado al cliente (post-yield)"
        )
        # 2) Loop de eventos del bus. DA-012: si el bus esta vacio
        # durante mas de KEEPALIVE_SECONDS, emitimos un comentario SSE
        # ':keepalive' (clientes EventSource lo ignoran) para forzar
        # a uvicorn a flushear bytes al socket TCP. Sin esto, en
        # Windows con subprocess worker PIPE handles, uvicorn retiene
        # el chunk del snapshot en su buffer interno y el cliente
        # recibe 0 bytes. Ver commit DA-012 para el diagnostico.
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=KEEPALIVE_SECONDS
                )
                _dbg.debug(
                    "_stream: queue.get() retorno event type=%r", event.get("type")
                )
                yield _format_sse(event)
            except asyncio.TimeoutError:
                # No hay eventos en KEEPALIVE_SECONDS: emitimos un
                # comentario SSE para forzar el flush del transport.
                _dbg.debug(
                    "_stream: keepalive (no eventos en %.1fs)", KEEPALIVE_SECONDS
                )
                yield b": keepalive\n\n"
    finally:
        bus.unsubscribe(queue)
        _dbg.debug("_stream: finally, queue unsubscribed")


router = APIRouter(prefix="/api/v1", tags=["sse"])


@router.get("/stream")
async def get_stream(request: Request) -> StreamingResponse:
    """SSE stream. Snapshot inicial (engine) + retransmisión de ``EventBus``."""
    bus: EventBus = request.app.state.event_bus
    engine = getattr(request.app.state, "engine", None)
    _dbg.debug(
        "get_stream entry: client=%s bus=%s engine=%s",
        request.client,
        id(bus),
        type(engine).__name__ if engine else None,
    )
    return StreamingResponse(
        _stream(bus, engine),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
