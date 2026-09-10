"""Tests de ``core.sse.progress_subscribe`` (paso 1.1.2).

Cubren:
  - Caso del plan: una llamada que actualiza el tracker
    (``begin``) → el stream SSE emite un chunk con
    ``{"type": "progress", "current": N, "total": M, "percent": P, ...}``.
  - ``hook_progress_tracker_to_bus`` conecta un tracker ya creado.
  - Ciclo completo ``begin`` → ``start_stage`` → ``finish_stage`` →
    ``finish`` emite 4 eventos con ``current`` y ``percent``
    crecientes.
  - Backward compat: sin hook, no se publica nada y el tracker se
    comporta idéntico al de antes.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from core.application.progress_buffer import ProgressTracker
from core.sse.event_bus import EventBus
from core.sse.progress_subscribe import (
    hook_progress_tracker_to_bus,
    make_progress_publisher,
)
from core.sse.stream import _stream


def _parse_sse_payload(raw: bytes) -> dict:
    text = raw.decode("utf-8")
    assert text.startswith("data: ")
    return json.loads(text[len("data: "):].rstrip("\n"))


@pytest.mark.asyncio
async def test_begin_publica_evento_progress_en_stream() -> None:
    """Caso del plan: ``tracker.begin(...)`` → chunk SSE con
    ``{"type": "progress", "current": 0, "total": 2, "percent": 0, ...}``."""
    bus = EventBus()
    tracker = ProgressTracker(on_publish=make_progress_publisher(bus))
    gen = _stream(bus)
    try:
        await gen.__anext__()  # snapshot

        async def trigger() -> None:
            await asyncio.sleep(0.01)
            tracker.begin("test_op", "Test op", ["s1", "s2"])

        task = asyncio.create_task(trigger())
        try:
            event_raw = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        finally:
            await task

        parsed = _parse_sse_payload(event_raw)
        assert parsed["type"] == "progress"
        assert parsed["operation"] == "test_op"
        assert parsed["label"] == "Test op"
        assert parsed["active"] is True
        assert parsed["current"] == 0
        assert parsed["total"] == 2
        assert parsed["percent"] == 0
        # Stages vienen como lista de dicts con id/label/status.
        assert len(parsed["stages"]) == 2
        assert {s["id"] for s in parsed["stages"]} == {"s1", "s2"}
        assert all(s["status"] == "pending" for s in parsed["stages"])
    finally:
        await gen.aclose()


def test_hook_a_tracker_existente_publica_eventos() -> None:
    """``hook_progress_tracker_to_bus`` conecta un tracker ya creado."""
    bus = EventBus()
    tracker = ProgressTracker()  # sin hook
    hook_progress_tracker_to_bus(tracker, bus)

    queue = bus.subscribe()
    tracker.begin("op", "Op", ["a"])
    event = queue.get_nowait()
    bus.unsubscribe(queue)

    assert event["type"] == "progress"
    assert event["operation"] == "op"
    assert event["total"] == 1
    assert event["active"] is True


@pytest.mark.asyncio
async def test_ciclo_completo_emite_4_eventos_con_current_creciente() -> None:
    """begin → start_stage → finish_stage → finish = 4 eventos."""
    bus = EventBus()
    tracker = ProgressTracker(on_publish=make_progress_publisher(bus))
    gen = _stream(bus)
    try:
        await gen.__anext__()  # snapshot inicial del stream

        async def lifecycle() -> None:
            await asyncio.sleep(0.01)
            tracker.begin("commit", "Commit", ["s1"])
            await asyncio.sleep(0.01)
            tracker.start_stage("s1")
            await asyncio.sleep(0.01)
            tracker.finish_stage("s1")
            await asyncio.sleep(0.01)
            tracker.finish(success=True)

        task = asyncio.create_task(lifecycle())

        received: list[dict] = []
        async def collect() -> None:
            for _ in range(4):
                raw = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
                received.append(_parse_sse_payload(raw))
        try:
            await collect()
        finally:
            await task

        # 4 eventos, todos de tipo progress.
        assert all(e["type"] == "progress" for e in received)
        # current sube de 0 a 1 a medida que se completa el stage.
        currents = [e["current"] for e in received]
        assert currents == [0, 0, 1, 1]
        # percent sube: 0, 0, 100, 100.
        percents = [e["percent"] for e in received]
        assert percents == [0, 0, 100, 100]
        # El último evento marca la operación como no activa.
        assert received[-1]["active"] is False
    finally:
        await gen.aclose()


def test_sin_hook_el_tracker_sigue_funcionando() -> None:
    """Backward compat: tracker sin hook se comporta idéntico al de antes."""
    tracker = ProgressTracker()  # sin on_publish
    tracker.begin("op", "Op", ["s1"])
    tracker.start_stage("s1")
    tracker.finish_stage("s1")
    snapshot = tracker.snapshot()
    assert snapshot.active is True
    assert snapshot.current == 1
    assert snapshot.total == 1
    assert snapshot.percent == 100


def test_sin_hook_el_tracker_no_publica_a_ningun_bus() -> None:
    """Sin hook, el tracker no intenta publicar (no hay crash, no hay leak)."""
    bus = EventBus()
    queue = bus.subscribe()
    tracker = ProgressTracker()  # sin hook
    tracker.begin("op", "Op", ["s1"])
    tracker.finish()
    # Cola vacía: nada se publicó.
    assert queue.empty()
    bus.unsubscribe(queue)
