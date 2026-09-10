"""Tests de ``core.sse.log_subscribe`` (paso 1.1.1).

Cubren:
  - Caso del plan: ``log_buffer.info("test")`` → el stream SSE emite
    ``{"type": "log", "level": "info", "message": "test", "timestamp": ...}``.
  - ``hook_log_buffer_to_bus`` conecta un ``LogBuffer`` ya creado.
  - Los 4 niveles (``info``/``success``/``warning``/``error``) se
    retransmiten correctamente.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from core.application.log_buffer import LogBuffer
from core.sse.event_bus import EventBus
from core.sse.log_subscribe import hook_log_buffer_to_bus, make_log_publisher
from core.sse.stream import _stream


def _parse_sse_payload(raw: bytes) -> dict:
    text = raw.decode("utf-8")
    assert text.startswith("data: ")
    return json.loads(text[len("data: "):].rstrip("\n"))


@pytest.mark.asyncio
async def test_log_buffer_info_publica_evento_log_en_stream() -> None:
    """Caso del plan: ``log_buffer.info("test")`` → chunk SSE con
    ``{"type": "log", "level": "info", "message": "test"}``."""
    bus = EventBus()
    log_buffer = LogBuffer(on_publish=make_log_publisher(bus))
    gen = _stream(bus)
    try:
        await gen.__anext__()  # snapshot

        async def trigger() -> None:
            await asyncio.sleep(0.01)
            log_buffer.info("test")

        task = asyncio.create_task(trigger())
        try:
            event_raw = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        finally:
            await task

        parsed = _parse_sse_payload(event_raw)
        assert parsed["type"] == "log"
        assert parsed["level"] == "info"
        assert parsed["message"] == "test"
        assert "timestamp" in parsed
    finally:
        await gen.aclose()


def test_hook_a_log_buffer_existente_publica_eventos() -> None:
    """``hook_log_buffer_to_bus`` conecta un LogBuffer ya creado (sin hook)."""
    bus = EventBus()
    log_buffer = LogBuffer()  # sin hook inicial
    hook_log_buffer_to_bus(log_buffer, bus)

    queue = bus.subscribe()
    log_buffer.info("hola")
    event = queue.get_nowait()
    bus.unsubscribe(queue)

    assert event["type"] == "log"
    assert event["level"] == "info"
    assert event["message"] == "hola"
    assert "timestamp" in event


def test_todos_los_niveles_se_publican_al_bus() -> None:
    """info / success / warning / error → 4 eventos con su level."""
    bus = EventBus()
    log_buffer = LogBuffer(on_publish=make_log_publisher(bus))

    queue = bus.subscribe()
    log_buffer.info("i")
    log_buffer.success("s")
    log_buffer.warning("w")
    log_buffer.error("e")
    bus.unsubscribe(queue)

    levels = [queue.get_nowait()["level"] for _ in range(4)]
    assert levels == ["info", "success", "warning", "error"]


def test_sin_hook_el_buffer_sigue_funcionando() -> None:
    """Backward compat: LogBuffer sin hook funciona como antes."""
    log_buffer = LogBuffer()
    log_buffer.info("hola")
    log_buffer.warning("cuidado")
    snapshot = log_buffer.snapshot()
    assert [e["level"] for e in snapshot] == ["info", "warning"]
    assert [e["message"] for e in snapshot] == ["hola", "cuidado"]
