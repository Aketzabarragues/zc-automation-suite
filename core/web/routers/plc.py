"""Router generico de PLC: arrancar FBs, desconectar, stream SSE.

Este router es **trasversal** y NO conoce FBs especificos (los busca
en ``ENGINE.fbs`` por nombre). Ver ``.clinerules`` §5 y
``AGENTS.md`` §3.

Endpoints:
  - ``POST /api/v1/plc/fb/{name}/start`` -> arranca un FB.
  - ``POST /api/v1/plc/fb/{name}/disconnect`` -> desconecta
    (solo si el FB expone ``disconnect()``).
  - ``GET /api/v1/plc/events`` -> stream SSE (snapshot inicial +
    eventos del Engine).

Convenciones (.clinerules §5, §6, §9; AGENTS.md):
  - Type hints en todas las firmas.
  - ``from __future__ import annotations``.
  - Los handlers devuelven ``dict`` (FastAPI serializa a JSON).
  - Sin polling: el frontend usa **solo** el SSE.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.plc.plc import ENGINE, FB_Base, sse_event_stream

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
#  POST /plc/fb/{name}/start
# ─────────────────────────────────────────────────────────────────────


@router.post("/plc/fb/{name}/start")
async def post_start_fb(name: str, request: Request) -> dict:
    """Arranca un FB por nombre. **Generico**: busca en ``ENGINE.fbs``.

    Args:
        name: nombre del FB registrado en ``ENGINE.fbs``.
        request: para leer el body JSON con los ``params`` del FB.
            Si el body esta vacio, se pasa ``{}``.

    Returns:
        ``{"started": name, "nStep": fb.nStep}``.

    Raises:
        HTTPException 404: si el FB no esta registrado.
        HTTPException 400: si los ``params`` no encajan con la
            firma de ``start()`` (lanza ``TypeError``).
        HTTPException 503: si el cliente cierra la conexion antes
            de que leamos el body (caso raro, pero posible).
    """
    fb = ENGINE.fbs.get(name)
    if fb is None:
        raise HTTPException(status_code=404, detail=f"FB '{name}' no registrado")

    # Leemos el body. Si esta vacio o no es JSON, ``params`` es
    # ``{}``. ``await request.body()`` puede lanzar ``ClientDisconnect``
    # si el cliente se va; lo dejamos propagar como 503 generico.
    try:
        raw = await request.body()
    except Exception:
        raise HTTPException(status_code=503, detail="cliente desconectado")
    params: dict = {}
    if raw:
        try:
            import json
            decoded = json.loads(raw.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise HTTPException(
                    status_code=400,
                    detail="el body debe ser un objeto JSON",
                )
            params = decoded
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"body JSON invalido: {exc}",
            )

    # ``start()`` es sincrono e idempotente. Si lanza ``TypeError``
    # es que los params no encajan: lo mapeamos a 400. Cualquier
    # otro error inesperado lo dejamos propagar (500).
    try:
        fb.start(**params)
    except TypeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"parametros incorrectos para FB '{name}': {exc}",
        )

    return {"started": name, "nStep": fb.nStep}


# ─────────────────────────────────────────────────────────────────────
#  POST /plc/fb/{name}/disconnect
# ─────────────────────────────────────────────────────────────────────


@router.post("/plc/fb/{name}/disconnect")
async def post_disconnect_fb(name: str) -> dict:
    """Desconecta un FB. **Solo** si el FB expone ``disconnect()``.

    Caso de uso principal: ``FB_ConexionTIA.disconnect()`` cuando
    el operario pulsa "Desconectar" en la UI. Otros FBs pueden
    o no tener este metodo; si no lo tienen, 404.

    Args:
        name: nombre del FB.

    Returns:
        ``{"disconnected": True, "nStep": fb.nStep}``.

    Raises:
        HTTPException 404: si el FB no esta registrado o si no
            expone ``disconnect()``.
    """
    fb = ENGINE.fbs.get(name)
    if fb is None:
        raise HTTPException(status_code=404, detail=f"FB '{name}' no registrado")
    if not hasattr(fb, "disconnect"):
        raise HTTPException(
            status_code=404,
            detail=f"FB '{name}' no soporta disconnect()",
        )
    # ``disconnect()`` puede ser sync o async (segun el FB).
    # ``inspect.iscoroutinefunction`` distingue los casos.
    import inspect
    result = fb.disconnect()  # type: ignore[attr-defined]
    if inspect.iscoroutine(result):
        await result
    return {"disconnected": True, "nStep": fb.nStep}


# ─────────────────────────────────────────────────────────────────────
#  GET /plc/events
# ─────────────────────────────────────────────────────────────────────


@router.get("/plc/events")
async def get_events(max_events: int = 0) -> StreamingResponse:
    """Stream SSE del Engine: snapshot inicial + eventos de FBs.

    Query params:
        ``max_events``: si ``> 0``, cierra el stream tras ``max_events``
            eventos (modo test). ``0`` = infinito (modo produccion).
            El snapshot inicial cuenta como 1.

    Yields:
        Chunks ``data: {json}\\n\\n`` UTF-8. Cada chunk es un
        evento: snapshot inicial (``type=snapshot``) o cambio
        de estado de un FB (``type=fb|done|error``).
    """
    async def event_stream() -> AsyncGenerator[bytes, None]:
        # ``sse_event_stream`` gestiona la suscripcion/desuscripcion
        # con ``try/finally``. Si el cliente cierra la conexion, el
        # ``yield`` siguiente lanza ``CancelledError`` o similar;
        # el ``finally`` desuscribe y la cola se vacia.
        async for chunk in sse_event_stream(ENGINE, max_events=max_events):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Evitar buffering en proxies intermedios; el HMI
            # necesita los eventos en tiempo real.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
