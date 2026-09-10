"""core.sse.stream — endpoint SSE ``GET /api/v1/stream``.

Fase 1, paso 1.0.4: integra ``EventBus``. El endpoint se subscribe
al bus del app state (``app.state.event_bus``), emite el snapshot
inicial y luego retransmite cada evento del bus como
``data: <json>\\n\\n``.

El cliente cancela la response al desconectar; el generator
desuscribe del bus en ``finally``.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from core.sse.event_bus import EventBus


_SNAPSHOT_EVENT: dict[str, Any] = {"type": "snapshot", "dbs": {}, "fbs": {}}


def _format_sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


async def _stream(bus: EventBus) -> AsyncIterator[bytes]:
    queue = bus.subscribe()
    try:
        # 1) Snapshot inicial.
        yield _format_sse(_SNAPSHOT_EVENT)
        # 2) Loop de eventos del bus hasta cancelación del cliente.
        while True:
            event = await queue.get()
            yield _format_sse(event)
    finally:
        bus.unsubscribe(queue)


router = APIRouter(prefix="/api/v1", tags=["sse"])


@router.get("/stream")
async def get_stream(request: Request) -> StreamingResponse:
    """SSE stream. Snapshot inicial + retransmisión de ``EventBus``."""
    bus: EventBus = request.app.state.event_bus
    return StreamingResponse(
        _stream(bus),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
