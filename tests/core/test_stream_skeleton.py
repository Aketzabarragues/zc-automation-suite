"""Tests del generador ``core.sse.stream._stream`` (snapshot inicial).

Verifica que el primer item emitido por el generador es el snapshot
vacío definido en el plan (``data: {"type": "snapshot", ...}``),
sin tocar la capa HTTP. La integración HTTP se valida en pasos
posteriores cuando el router se monte en la app real.
"""
from __future__ import annotations

import json

import pytest

from core.sse.event_bus import EventBus
from core.sse.stream import _stream


@pytest.mark.asyncio
async def test_primer_item_es_snapshot_vacio_del_plan() -> None:
    bus = EventBus()
    gen = _stream(bus)
    try:
        first = await gen.__anext__()
    finally:
        await gen.aclose()
    assert first == b'data: {"type": "snapshot", "dbs": {}, "fbs": {}}\n\n'


@pytest.mark.asyncio
async def test_snapshot_json_parseable() -> None:
    bus = EventBus()
    gen = _stream(bus)
    try:
        first = await gen.__anext__()
    finally:
        await gen.aclose()
    text = first.decode("utf-8")
    assert text.startswith("data: ")
    payload = text[len("data: "):].rstrip("\n")
    assert json.loads(payload) == {"type": "snapshot", "dbs": {}, "fbs": {}}


@pytest.mark.asyncio
async def test_close_del_generator_desuscribe_del_bus() -> None:
    """Al cerrar el generador, la cola se desuscribe del bus (limpieza)."""
    bus = EventBus()
    gen = _stream(bus)
    # Consumir el snapshot para que el generator esté dentro del
    # ``try`` y cualquier ``finally`` esté listo para ejecutarse.
    await gen.__anext__()
    assert bus.subscriber_count() == 1
    await gen.aclose()
    assert bus.subscriber_count() == 0
