"""Fase 0.5 spike: router mínimo con /ping y /events (SSE).

Este router existe SOLO para validar que el ``StreamingResponse`` nativo
de FastAPI funciona dentro de un .exe de PyInstaller (ver
``PLC_IE_61131_GREENFIELD.md`` §4 Fase 0.5).

**NO usar ``sse-starlette``**: el plan lo prohíbe explícitamente. Si el
empaquetado falla con el SSE nativo, evaluar ``sse-starlette`` como
fallback antes de continuar a Fase 1.

Convenciones (.clinerules §6, §9):
  - Type hints en todas las firmas.
  - ``from __future__ import annotations``.
  - ``asyncio`` eficiente: ``await asyncio.sleep(1)`` NO bloquea el
    event loop principal.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse


router = APIRouter()


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Endpoint de smoke test: responde ``pong`` al ``ping``.

    Es el canario de "el servidor está vivo" — útil para diagnóstico
    rápido sin tener que abrir un EventSource.

    Returns:
        ``{"ping": "pong"}``.
    """
    return {"ping": "pong"}


# ── Constantes del stream SSE ────────────────────────────────────────────
# El primer evento (data) llega inmediato; los heartbeats (comentarios SSE,
# líneas que empiezan con ``:``) llegan cada ``_HEARTBEAT_EVERY`` ticks de
# 1 segundo. Documentado en el plan: la conexión debe aguantar >30s sin
# cerrarse (ver §4 Fase 0.5, criterio de cierre).
_HEARTBEAT_EVERY = 5  # ticks de 1s → heartbeat cada 5s
_TICK_SECONDS = 1.0


@router.get("/events")
async def events(max_events: int = 0) -> StreamingResponse:
    """SSE mínimo: un evento inicial + heartbeats periódicos.

    Query params:
        ``max_events``: si > 0, el stream se cierra tras emitir el evento
        inicial (modo test). Default 0 = infinito (modo produccion).

    Yields:
        Bytes en formato SSE. Primer chunk: ``data: {"ping": "pong"}\\n\\n``.
        Heartbeats cada 5s como comentarios SSE (no disparan eventos en el
        cliente, pero mantienen viva la conexión TCP).
    """
    async def event_stream() -> AsyncGenerator[bytes, None]:
        # Evento inicial — el HMI lo usa como snapshot de "estoy vivo".
        yield b'data: {"ping": "pong"}\n\n'
        # Modo test: cerrar tras el primer evento.
        if max_events > 0:
            return
        # Modo produccion: loop de keepalive.
        tick_count = 0
        while True:
            await asyncio.sleep(_TICK_SECONDS)
            tick_count += 1
            if tick_count % _HEARTBEAT_EVERY == 0:
                # Comentario SSE (línea ``:...``) — no es un ``message``
                # en el EventSource del cliente, pero evita timeouts de
                # proxies intermedios.
                yield b": heartbeat\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
