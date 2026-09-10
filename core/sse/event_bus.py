"""core.sse.event_bus — bus pub/sub asíncrono para Server-Sent Events.

Fase 1 del refactor: backbone de los 3 canales (logs, progress,
tia_state) que consumirá ``/api/v1/stream``.

Cada suscriptor recibe su propia ``asyncio.Queue``. ``publish`` se
puede llamar desde un hilo sync (p. ej. callbacks de LogBuffer o
TIA Portal) sin corromper el bus.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any


class EventBus:
    """Bus pub/sub con colas asyncio por suscriptor.

    API:
      - ``subscribe()`` → ``asyncio.Queue`` nueva.
      - ``unsubscribe(queue)`` → retira la cola del bus.
      - ``publish(event)`` → encola el evento en TODAS las colas vivas.
      - ``subscriber_count()`` → diagnóstico / tests.

    Idempotente: ``publish`` siempre encola (no deduplica).
    Thread-safe: ``subscribe``, ``unsubscribe`` y ``publish`` usan un
    ``threading.Lock`` para proteger el set de suscriptores.
    """

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subs.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        # Snapshot atómico: cualquier subscribe/unsubscribe posterior
        # no afecta a esta entrega.
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Suscriptor lento con maxsize: descartamos. En SSE el
                # cliente se reconecta y recibe el snapshot inicial.
                pass

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)
