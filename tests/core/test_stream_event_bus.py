"""Tests de integración ``core.sse.stream._stream`` + ``EventBus``.

El plan (paso 1.0.4) pide: "test que publica 1 evento y verifica
que el stream lo emite". Lo verificamos a nivel de generador
async con ``__anext__`` — más simple y determinista que un test
HTTP contra un server en marcha.

Cubre:
  - 1 evento publicado → 1 item tras el snapshot.
  - N eventos publicados → N items en orden.
  - Sin publicaciones, el generator queda esperando (cliente
    controla la desconexión).
  - El generator se desuscribe del bus al cerrarse.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from core.sse.event_bus import EventBus
from core.sse.stream import _stream


def _parse_sse_payload(raw: bytes) -> dict:
    """Decodifica un chunk ``data: <json>\\n\\n`` a dict."""
    text = raw.decode("utf-8")
    assert text.startswith("data: ")
    return json.loads(text[len("data: "):].rstrip("\n"))


@pytest.mark.asyncio
async def test_publicar_un_evento_lo_emite_en_el_stream() -> None:
    """Caso del plan: 1 publicación → 1 item tras el snapshot."""
    bus = EventBus()
    gen = _stream(bus)
    try:
        # 1) Snapshot.
        snapshot = await gen.__anext__()
        assert _parse_sse_payload(snapshot) == {
            "type": "snapshot", "dbs": {}, "fbs": {}
        }

        # 2) Publicar un evento tras un pequeño delay (da tiempo a
        # que el generator esté esperando en ``queue.get()``).
        async def publisher() -> None:
            await asyncio.sleep(0.01)
            bus.publish({"type": "log", "message": "hola"})

        pub_task = asyncio.create_task(publisher())
        try:
            event = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        finally:
            await pub_task

        assert _parse_sse_payload(event) == {"type": "log", "message": "hola"}
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_multiples_eventos_se_emiten_en_orden() -> None:
    """Varios eventos llegan en el orden publicado."""
    bus = EventBus()
    gen = _stream(bus)
    try:
        await gen.__anext__()  # snapshot

        async def publisher() -> None:
            await asyncio.sleep(0.01)
            for i in range(3):
                bus.publish({"type": "x", "i": i})

        pub_task = asyncio.create_task(publisher())
        try:
            received = [
                _parse_sse_payload(await asyncio.wait_for(gen.__anext__(), timeout=1.0))
                for _ in range(3)
            ]
        finally:
            await pub_task

        assert received == [{"type": "x", "i": i} for i in range(3)]
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_close_desuscribe_del_bus() -> None:
    """Al cerrar el generator, la cola sale del bus (no leak)."""
    bus = EventBus()
    gen = _stream(bus)
    await gen.__anext__()  # snapshot
    assert bus.subscriber_count() == 1
    await gen.aclose()
    assert bus.subscriber_count() == 0


@pytest.mark.asyncio
async def test_sin_publicaciones_el_generator_queda_esperando() -> None:
    """Si nadie publica, ``__anext__`` queda esperando hasta timeout
    o hasta que el cliente cierre. (Comportamiento esperado: el server
    mantiene la conexión abierta.)"""
    bus = EventBus()
    gen = _stream(bus)
    try:
        await gen.__anext__()  # snapshot
        # El siguiente __anext__ debe bloquearse (no hay eventos).
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(gen.__anext__(), timeout=0.05)
    finally:
        await gen.aclose()
