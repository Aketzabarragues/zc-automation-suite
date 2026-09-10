"""Tests de ``core.sse.tia_state_subscribe`` (paso 1.1.3).

Cubren:
  - Caso del plan: cuando cambia ``_connection_state``, el stream
    SSE emite un chunk con ``{"type": "tia_state", "state": "..."}``.
  - El setter de la property filtra asignaciones idempotentes
    (mismo estado → no se publica).
  - El glue ``hook_tia_gateway_to_bus`` conecta un gateway ya creado.
  - Backward compat: gateway sin ``on_state_change`` no rompe.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from core.infrastructure.gateway import TIAProcessGateway
from core.sse.event_bus import EventBus
from core.sse.stream import _stream
from core.sse.tia_state_subscribe import (
    hook_tia_gateway_to_bus,
    make_tia_state_publisher,
)


def _parse_sse_payload(raw: bytes) -> dict:
    text = raw.decode("utf-8")
    assert text.startswith("data: ")
    return json.loads(text[len("data: "):].rstrip("\n"))


@pytest.mark.asyncio
async def test_cambio_de_estado_publica_tia_state_en_stream() -> None:
    """Caso del plan: ``_connection_state`` cambia → chunk SSE con
    ``{"type": "tia_state", "state": "..."}``."""
    bus = EventBus()
    gateway = TIAProcessGateway(
        persistent=True,
        on_state_change=make_tia_state_publisher(bus),
    )
    try:
        gen = _stream(bus)
        try:
            await gen.__anext__()  # snapshot inicial

            async def trigger() -> None:
                await asyncio.sleep(0.01)
                gateway._connection_state = "connecting"  # setter dispara hook

            task = asyncio.create_task(trigger())
            try:
                event_raw = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
            finally:
                await task

            parsed = _parse_sse_payload(event_raw)
            assert parsed == {"type": "tia_state", "state": "connecting"}
        finally:
            await gen.aclose()
    finally:
        # El gateway persistente podría tener un worker; el test no
        # lo arranca, pero por simetría cerramos.
        pass


def test_setter_no_publica_si_el_estado_no_cambia() -> None:
    """Asignar el mismo estado NO dispara el callback (no spam)."""
    bus = EventBus()
    queue = bus.subscribe()
    gateway = TIAProcessGateway(
        persistent=True,
        on_state_change=make_tia_state_publisher(bus),
    )
    try:
        # El init ya pone _connection_state = "idle". Asignar "idle"
        # de nuevo NO debe disparar el callback.
        gateway._connection_state = "idle"
        assert queue.empty()
        # Un cambio real sí dispara.
        gateway._connection_state = "connecting"
        assert queue.get_nowait() == {"type": "tia_state", "state": "connecting"}
        # Otro cambio real.
        gateway._connection_state = "connected"
        assert queue.get_nowait() == {"type": "tia_state", "state": "connected"}
        # Idempotente: re-asignar "connected" no publica.
        gateway._connection_state = "connected"
        assert queue.empty()
    finally:
        bus.unsubscribe(queue)


def test_hook_tia_gateway_to_bus_conecta_gateway_existente() -> None:
    """``hook_tia_gateway_to_bus`` reconecta el on_state_change del gateway."""
    bus = EventBus()
    queue = bus.subscribe()
    gateway = TIAProcessGateway(persistent=True)  # sin hook inicial
    hook_tia_gateway_to_bus(gateway, bus)

    gateway._connection_state = "connecting"
    assert queue.get_nowait() == {"type": "tia_state", "state": "connecting"}
    bus.unsubscribe(queue)


def test_gateway_sin_on_state_change_no_publica_ni_falla() -> None:
    """Backward compat: gateway sin hook no rompe (sigue funcionando)."""
    gateway = TIAProcessGateway(persistent=True)  # sin hook
    # La property setter debe tolerar que _on_state_change no exista.
    gateway._connection_state = "connecting"
    assert gateway._connection_state == "connecting"
