"""core.sse.progress_subscribe — wire ``ProgressTracker`` → ``EventBus``.

Conecta un ``ProgressTracker`` al bus para que cada cambio de
estado (``begin``/``start_stage``/``finish_stage``/``error_stage``/
``finish``/``clear``) se retransmita como evento
``{"type": "progress", "current": ..., "total": ..., "percent": ..., ...}``
en el SSE stream.

El lock interno del tracker NO se retiene durante la notificación:
el callback se ejecuta tras soltarlo (mismo patrón que
``log_subscribe``).
"""
from __future__ import annotations

from collections.abc import Callable

from core.application.progress_buffer import ProgressSnapshot, ProgressTracker
from core.sse.event_bus import EventBus


def make_progress_publisher(bus: EventBus) -> Callable[[ProgressSnapshot], None]:
    """Devuelve un callback que publica cada snapshot como evento ``progress``.

    El payload incluye el ``ProgressSnapshot.to_dict()`` completo
    (active, operation, label, current, total, percent, stages,
    started_at, finished_at, error) para que la SPA tenga TODO el
    contexto en un solo evento.
    """

    def publish(snapshot: ProgressSnapshot) -> None:
        bus.publish({"type": "progress", **snapshot.to_dict()})

    return publish


def hook_progress_tracker_to_bus(tracker: ProgressTracker, bus: EventBus) -> None:
    """Conecta un ``ProgressTracker`` ya creado a un ``EventBus``."""
    tracker._on_publish = make_progress_publisher(bus)  # type: ignore[assignment]
