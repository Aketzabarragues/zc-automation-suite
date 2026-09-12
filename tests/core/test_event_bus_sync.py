"""Tests de EventBusSync (Fase 4 / paso 4.3.1)."""
from __future__ import annotations

import queue
import threading
import time

import pytest

from core.sse.event_bus_sync import EventBusSync


def test_subscribe_returns_queue_with_maxsize():
    bus = EventBusSync(maxsize_per_subscriber=42)
    q = bus.subscribe()
    assert q.maxsize == 42


def test_publish_delivers_to_all_subscribers():
    bus = EventBusSync()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    bus.publish({"type": "log", "msg": "hello"})
    assert q1.get_nowait() == {"type": "log", "msg": "hello"}
    assert q2.get_nowait() == {"type": "log", "msg": "hello"}


def test_unsubscribe_removes_queue():
    bus = EventBusSync()
    q = bus.subscribe()
    bus.unsubscribe(q)
    assert bus.subscriber_count() == 0
    bus.publish({"type": "log"})
    with pytest.raises(queue.Empty):
        q.get(timeout=0.1)


def test_subscriber_count_grows_and_shrinks():
    bus = EventBusSync()
    assert bus.subscriber_count() == 0
    q1 = bus.subscribe()
    assert bus.subscriber_count() == 1
    q2 = bus.subscribe()
    assert bus.subscriber_count() == 2
    bus.unsubscribe(q1)
    assert bus.subscriber_count() == 1


def test_publish_to_full_queue_drops_event_with_warning():
    """Suscriptores lentos: cola llena -> drop + warning."""
    bus = EventBusSync(maxsize_per_subscriber=1)
    q = bus.subscribe()
    bus.publish({"first": 1})  # ocupa el unico slot
    # El segundo no cabe -> debe dropear (sin raise).
    bus.publish({"second": 2})
    # Solo el primero esta en la cola.
    assert q.get_nowait() == {"first": 1}
    with pytest.raises(queue.Empty):
        q.get(timeout=0.1)


def test_publish_is_thread_safe_under_concurrent_access():
    """publish() desde N hilos concurrentes: no raise, todos los eventos
    llegan (al menos los que caben en la cola).
    """
    bus = EventBusSync(maxsize_per_subscriber=10_000)
    q = bus.subscribe()

    n_threads = 8
    n_events_per_thread = 50

    def producer(idx: int) -> None:
        for j in range(n_events_per_thread):
            bus.publish({"thread": idx, "j": j})

    threads = [
        threading.Thread(target=producer, args=(i,)) for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    # Todos los eventos deben haber llegado (la cola tiene 10_000 slots,
    # 8*50 = 400 eventos).
    received = [q.get_nowait() for _ in range(n_threads * n_events_per_thread)]
    assert len(received) == n_threads * n_events_per_thread
    with pytest.raises(queue.Empty):
        q.get(timeout=0.1)


def test_publish_to_dead_subscriber_does_not_affect_others():
    """Si un suscriptor hace cola llena, los demas siguen recibiendo."""
    # full_q: maxsize=1 (rapidamente lleno). live_q: maxsize=100 (cabe todo).
    bus = EventBusSync()
    full_q: queue.Queue = queue.Queue(maxsize=1)
    live_q: queue.Queue = queue.Queue(maxsize=100)
    bus._subs.add(full_q)
    bus._subs.add(live_q)

    bus.publish({"first": 1})  # cabe en ambos
    bus.publish({"second": 2})  # cabe en live_q, NO en full_q (descarta)

    assert full_q.get_nowait() == {"first": 1}
    live_msgs = [live_q.get(timeout=0.1) for _ in range(2)]
    assert live_msgs == [{"first": 1}, {"second": 2}]


def test_default_maxsize_is_1000():
    """maxsize por defecto = 1000 (suficiente para SSE buffer)."""
    bus = EventBusSync()
    q = bus.subscribe()
    assert q.maxsize == 1000


def test_subscriber_can_be_unsubscribed_multiple_times():
    """unsubscribe es idempotente."""
    bus = EventBusSync()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.unsubscribe(q)  # no raise
    bus.unsubscribe(q)  # no raise
    assert bus.subscriber_count() == 0


def test_event_bus_sync_is_independent_from_async_one():
    """Verifica que EventBusSync es una clase aparte, no comparte estado."""
    from core.sse.event_bus import EventBus

    sync_bus = EventBusSync()
    async_bus = EventBus()

    sq = sync_bus.subscribe()
    async_q = async_bus.subscribe()

    sync_bus.publish({"a": 1})
    async_bus.publish({"b": 2})

    # Cada bus entrega solo lo publicado en si mismo.
    assert sq.get_nowait() == {"a": 1}
    with pytest.raises(queue.Empty):
        sq.get(timeout=0.1)

    # El bus async se drena via get_nowait (no await porque ya hay eventos).
    assert async_q.get_nowait() == {"b": 2}
