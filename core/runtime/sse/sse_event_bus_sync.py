"""EventBusSync - bus pub/sub sync para el modelo OB1.

Version thread-safe del ``EventBus`` original (basado en ``asyncio.Queue``).
El OB1 main loop usa este; los consumidores SSE migraran a sync cuando
sea necesario.

API equivalente a ``EventBus`` pero con ``queue.Queue`` thread-safe:
  - subscribe()             : queue.Queue nueva (size configurable).
  - unsubscribe(q)          : retira la cola del bus.
  - publish(event)          : encola en TODAS las colas vivas.
  - subscriber_count()      : diagnostico / tests.

Idempotente: ``publish`` siempre encola (no deduplica).
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any

logger = logging.getLogger(__name__)


class EventBusSync:
    """Bus pub/sub con colas ``queue.Queue`` thread-safe por suscriptor."""

    def __init__(self, maxsize_per_subscriber: int = 1000) -> None:
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._maxsize = maxsize_per_subscriber

    def subscribe(self) -> queue.Queue:
        """Crea y registra una cola nueva. Thread-safe."""
        q: queue.Queue = queue.Queue(maxsize=self._maxsize)
        with self._lock:
            self._subs.add(q)
        logger.debug(
            "EventBusSync.subscribe: queue id=%s subscribers_now=%d",
            id(q),
            len(self._subs),
        )
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        """Retira la cola del bus. Idempotente. Thread-safe."""
        with self._lock:
            self._subs.discard(q)
        logger.debug(
            "EventBusSync.unsubscribe: queue id=%s subscribers_now=%d",
            id(q),
            len(self._subs),
        )

    def publish(self, event: dict[str, Any]) -> None:
        """Encola el evento en TODAS las colas vivas.

        Suscriptores lentos con cola llena: descartamos el evento y
        hacemos log warning (mismo contrato que el EventBus async).
        """
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                logger.warning(
                    "EventBusSync.publish: queue id=%s FULL, evento descartado",
                    id(q),
                )

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)


__all__ = ["EventBusSync"]
