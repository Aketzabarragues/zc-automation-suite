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

import json
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from core.plc.engine import Engine
from core.sse.event_bus import EventBus


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
    queue = bus.subscribe()
    try:
        # 1) Snapshot inicial (engine real o placeholder defensivo).
        yield _format_sse(_build_snapshot(engine))
        # 2) Loop de eventos del bus hasta cancelación del cliente.
        while True:
            event = await queue.get()
            yield _format_sse(event)
    finally:
        bus.unsubscribe(queue)


router = APIRouter(prefix="/api/v1", tags=["sse"])


@router.get("/stream")
async def get_stream(request: Request) -> StreamingResponse:
    """SSE stream. Snapshot inicial (engine) + retransmisión de ``EventBus``."""
    bus: EventBus = request.app.state.event_bus
    engine = getattr(request.app.state, "engine", None)
    return StreamingResponse(
        _stream(bus, engine),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
