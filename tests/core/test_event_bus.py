"""Tests unitarios de ``core.sse.event_bus.EventBus``.

Cubren:
  - publish/subscribe básico (1 suscriptor).
  - multi-subscriber.
  - unsubscribe.
  - publish sin suscriptores (noop).
  - publish no deduplica eventos iguales.
  - thread-safety desde hilos sync.
  - coexistencia sync + async.
  - ``await q.get()`` desde una coroutine.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from core.sse.event_bus import EventBus


def test_publish_llega_a_un_subscriber() -> None:
    bus = EventBus()
    q = bus.subscribe()
    bus.publish({"type": "log", "message": "hola"})
    assert q.get_nowait() == {"type": "log", "message": "hola"}


def test_multiples_subscribers_reciben_todos() -> None:
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    q3 = bus.subscribe()
    bus.publish({"k": "v"})
    expected = {"k": "v"}
    assert q1.get_nowait() == expected
    assert q2.get_nowait() == expected
    assert q3.get_nowait() == expected


def test_unsubscribe_deja_de_recibir() -> None:
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    bus.unsubscribe(q1)
    bus.publish({"k": "v"})
    assert q2.get_nowait() == {"k": "v"}
    assert q1.empty()


def test_unsubscribe_desconocido_es_noop() -> None:
    bus = EventBus()
    other = asyncio.Queue()
    bus.unsubscribe(other)  # no falla
    assert bus.subscriber_count() == 0


def test_publish_sin_subscribers_no_falla() -> None:
    bus = EventBus()
    bus.publish({"k": "v"})  # noop
    assert bus.subscriber_count() == 0


def test_publish_no_deduplica_eventos_iguales() -> None:
    """Idempotencia: dos publish con el mismo dict publican 2 eventos."""
    bus = EventBus()
    q = bus.subscribe()
    bus.publish({"k": "v"})
    bus.publish({"k": "v"})
    assert q.qsize() == 2
    assert q.get_nowait() == {"k": "v"}
    assert q.get_nowait() == {"k": "v"}


def test_subscriber_count_refleja_estado() -> None:
    bus = EventBus()
    assert bus.subscriber_count() == 0
    q1 = bus.subscribe()
    assert bus.subscriber_count() == 1
    q2 = bus.subscribe()
    assert bus.subscriber_count() == 2
    bus.unsubscribe(q1)
    assert bus.subscriber_count() == 1


def test_publish_es_thread_safe() -> None:
    """``publish`` desde un hilo sync no rompe el estado del bus.

    No asumimos orden FIFO entre hilos (es interleaving). Lo que
    importa: 100 eventos publicados, 100 recibidos, sin pérdida ni
    duplicación.
    """
    bus = EventBus()
    q = bus.subscribe()

    def worker(n: int) -> None:
        for i in range(n):
            bus.publish({"i": i})

    t1 = threading.Thread(target=worker, args=(50,), daemon=True)
    t2 = threading.Thread(target=worker, args=(50,), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    received = [q.get_nowait() for _ in range(100)]
    assert len(received) == 100
    assert {e["i"] for e in received} == set(range(50))


def test_publish_desde_sync_y_async_coexisten() -> None:
    """Publicar desde un hilo sync y desde el event loop async al
    mismo tiempo no corrompe las colas."""
    bus = EventBus()
    q = bus.subscribe()

    def sync_worker() -> None:
        for i in range(20):
            bus.publish({"src": "sync", "i": i})

    async def async_worker() -> None:
        for i in range(20):
            bus.publish({"src": "async", "i": i})
            await asyncio.sleep(0)

    t = threading.Thread(target=sync_worker, daemon=True)
    t.start()
    asyncio.run(async_worker())
    t.join()

    received = [q.get_nowait() for _ in range(40)]
    sync_events = [e for e in received if e["src"] == "sync"]
    async_events = [e for e in received if e["src"] == "async"]
    assert sorted(e["i"] for e in sync_events) == list(range(20))
    assert sorted(e["i"] for e in async_events) == list(range(20))


@pytest.mark.asyncio
async def test_subscriber_puede_await_eventos() -> None:
    """El suscriptor hace ``await q.get()`` y recibe el evento."""
    bus = EventBus()
    q = bus.subscribe()

    async def producer() -> None:
        await asyncio.sleep(0.01)
        bus.publish({"type": "log"})

    asyncio.create_task(producer())
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event == {"type": "log"}
