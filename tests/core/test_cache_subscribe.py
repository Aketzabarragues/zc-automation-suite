"""Tests de ``core.sse.cache_subscribe`` (paso 1.1.4).

Cubren:
  - Caso del plan (plcs): ``get_plcs()`` actualiza el cache → el
    stream SSE emite ``{"type": "plcs", "data": [...]}``.
  - Caso del plan (project_info): ``get_project_info()`` actualiza
    el cache → emite ``{"type": "project_info", "data": {...}}``.
  - Cache hit (segunda llamada sin ``force_refresh``) NO publica.
  - ``hook_tia_gateway_cache_to_bus`` conecta un gateway ya creado.
  - Keys desconocidas (p. ej. ``"blocks::..."``) se ignoran.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from core.infrastructure.gateway import TIAProcessGateway
from core.sse.cache_subscribe import (
    hook_tia_gateway_cache_to_bus,
    make_cache_publisher,
)
from core.sse.event_bus import EventBus
from core.sse.stream import _stream


def _parse_sse_payload(raw: bytes) -> dict:
    text = raw.decode("utf-8")
    assert text.startswith("data: ")
    return json.loads(text[len("data: "):].rstrip("\n"))


def _make_gateway(bus: EventBus) -> TIAProcessGateway:
    """Crea un gateway persistente con el hook de cache cableado al bus.
    ``_dispatch_worker`` queda sin tocar; cada test lo monkey-patchea."""
    return TIAProcessGateway(
        persistent=True,
        on_cache_update=make_cache_publisher(bus),
    )


@pytest.mark.asyncio
async def test_get_plcs_publica_evento_plcs_en_stream() -> None:
    """Caso del plan: ``get_plcs()`` → chunk SSE con
    ``{"type": "plcs", "data": [...]}``."""
    bus = EventBus()
    gateway = _make_gateway(bus)
    gateway._dispatch_worker = AsyncMock(return_value=[
        {"name": "PLC1", "short_designation": "CPU 1518-4 PN/DP"},
        {"name": "PLC2", "short_designation": None},
    ])

    gen = _stream(bus)
    try:
        await gen.__anext__()  # snapshot

        async def trigger() -> None:
            await asyncio.sleep(0.01)
            await gateway.get_plcs()

        task = asyncio.create_task(trigger())
        try:
            event_raw = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        finally:
            await task

        parsed = _parse_sse_payload(event_raw)
        assert parsed["type"] == "plcs"
        assert parsed["data"] == [
            {"name": "PLC1", "short_designation": "CPU 1518-4 PN/DP"},
            {"name": "PLC2", "short_designation": None},
        ]
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_get_project_info_publica_evento_en_stream() -> None:
    """Caso del plan: ``get_project_info()`` → chunk SSE con
    ``{"type": "project_info", "data": {...}}``."""
    bus = EventBus()
    gateway = _make_gateway(bus)
    gateway._dispatch_worker = AsyncMock(return_value={
        "name": "MiProyecto",
        "path": "C:/proys/mi.zap15",
        "author": "Aketza",
    })

    gen = _stream(bus)
    try:
        await gen.__anext__()  # snapshot

        async def trigger() -> None:
            await asyncio.sleep(0.01)
            await gateway.get_project_info()

        task = asyncio.create_task(trigger())
        try:
            event_raw = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        finally:
            await task

        parsed = _parse_sse_payload(event_raw)
        assert parsed["type"] == "project_info"
        assert parsed["data"] == {
            "name": "MiProyecto",
            "path": "C:/proys/mi.zap15",
            "author": "Aketza",
        }
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_cache_hit_no_publica() -> None:
    """Segunda llamada con el cache lleno NO debe publicar (no hay update)."""
    bus = EventBus()
    queue = bus.subscribe()
    gateway = _make_gateway(bus)
    gateway._dispatch_worker = AsyncMock(return_value=[
        {"name": "PLC1", "short_designation": None},
    ])

    # Primera llamada: cache miss → publish + cache fill.
    await gateway.get_plcs()
    first = queue.get_nowait()
    bus.unsubscribe(queue)
    assert first["type"] == "plcs"
    assert gateway._dispatch_worker.await_count == 1

    # Segunda llamada: cache hit → NO publish, NO nueva dispatch.
    queue2 = bus.subscribe()
    result = await gateway.get_plcs()
    bus.unsubscribe(queue2)
    assert result == [{"name": "PLC1", "short_designation": None}]
    assert queue2.empty()
    assert gateway._dispatch_worker.await_count == 1  # sin re-llamada


def test_hook_tia_gateway_cache_to_bus_conecta_gateway_existente() -> None:
    """``hook_tia_gateway_cache_to_bus`` cablea un gateway sin hook."""
    bus = EventBus()
    queue = bus.subscribe()
    gateway = TIAProcessGateway(persistent=True)  # sin hook
    hook_tia_gateway_cache_to_bus(gateway, bus)

    # Disparar manualmente el hook con la firma esperada.
    gateway._on_cache_update("plcs", [{"name": "X"}])
    bus.unsubscribe(queue)
    assert queue.get_nowait() == {"type": "plcs", "data": [{"name": "X"}]}


def test_keys_desconocidas_se_ignoran() -> None:
    """Keys de cache fuera del mapeo (``"blocks::..."``) NO publican."""
    bus = EventBus()
    queue = bus.subscribe()
    publisher = make_cache_publisher(bus)

    publisher("blocks::PLC1::", ["B1", "B2"])
    publisher("otro_cache", {"foo": "bar"})
    bus.unsubscribe(queue)
    assert queue.empty()


def test_gateway_non_persistent_no_se_cablea() -> None:
    """``hook_tia_gateway_cache_to_bus`` no actúa en gateways 1-shot."""
    bus = EventBus()
    gateway = TIAProcessGateway(persistent=False)  # 1-shot
    # El atributo no existe (no hay init en modo 1-shot).
    assert not hasattr(gateway, "_on_cache_update")
    hook_tia_gateway_cache_to_bus(gateway, bus)
    # Sigue sin existir.
    assert not hasattr(gateway, "_on_cache_update")
