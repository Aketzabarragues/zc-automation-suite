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
# Cada ``_TICK_SECONDS`` segundos el endpoint emite un evento ``{"tick": N}``
# donde N es un contador que incrementa de 0 a ``_TICK_MAX`` y se resetea.
# En el frontend el HMI pinta el tick, lo que permite al operario VER
# visualmente cada cuanto tiempo se actualiza la web (cada 500ms con
# la config por defecto). Esto es un test vivo del push.
_TICK_SECONDS = 0.5
_TICK_MAX = 500


@router.get("/events")
async def events(max_events: int = 0) -> StreamingResponse:
    """SSE con un contador que incrementa cada ``_TICK_SECONDS`` segundos.

    Query params:
        ``max_events``: si > 0, el stream se cierra tras emitir el primer
        evento (modo test). Default 0 = infinito (modo demo del operario).

    Yields:
        Bytes en formato SSE. Cada chunk es ``data: {"tick": N}\\n\\n``
        con N incrementando. El frontend pinta N y se ve el refesco.
    """
    async def event_stream() -> AsyncGenerator[bytes, None]:
        # Primer evento inmediato.
        tick = 0
        yield f'data: {{"tick": {tick}}}\n\n'.encode()
        # Modo test: cerrar tras el primer evento.
        if max_events > 0:
            return
        # Modo demo: emitir ticks incrementales.
        while True:
            await asyncio.sleep(_TICK_SECONDS)
            tick = (tick + 1) % _TICK_MAX
            yield f'data: {{"tick": {tick}}}\n\n'.encode()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
