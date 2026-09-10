"""core.sse.log_subscribe — wire ``LogBuffer`` → ``EventBus``.

Conecta un ``LogBuffer`` al bus para que cada mensaje publicado
(``info``/``success``/``warning``/``error``) se retransmita como
evento ``{"type": "log", "timestamp": ..., "level": ..., "message": ...}``
en el SSE stream, además de guardarse en el buffer circular.

El hook se inyecta al construir el ``LogBuffer`` (o via
``hook_log_buffer_to_bus`` para uno ya creado). El lock del buffer
NO se retiene durante la notificación: el callback se ejecuta tras
liberarlo para no bloquear otros publicadores.
"""
from __future__ import annotations

from collections.abc import Callable

from core.application.log_buffer import LogBuffer
from core.sse.event_bus import EventBus


def make_log_publisher(bus: EventBus) -> Callable[[dict], None]:
    """Devuelve un callback que publica cada entry como evento ``log``.

    Formato del evento:
        ``{"type": "log", "timestamp": "...", "level": "...", "message": "..."}``
    """

    def publish(entry: dict) -> None:
        bus.publish({"type": "log", **entry})

    return publish


def hook_log_buffer_to_bus(buffer: LogBuffer, bus: EventBus) -> None:
    """Conecta un ``LogBuffer`` ya creado a un ``EventBus``.

    Tras esta llamada, cada ``info``/``success``/``warning``/``error``
    publica un evento ``log`` en el bus. El buffer circular sigue
    funcionando idéntico.
    """
    buffer._on_publish = make_log_publisher(bus)
