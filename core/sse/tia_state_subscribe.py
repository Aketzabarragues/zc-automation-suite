"""core.sse.tia_state_subscribe — wire ``TIAProcessGateway._connection_state`` → ``EventBus``.

Conecta un gateway persistente al bus para que cada cambio de
``_connection_state`` (``"idle"`` → ``"connecting"`` → ``"connected"``
→ ``"error"``) se retransmita como evento
``{"type": "tia_state", "state": "..."}`` en el SSE stream.

Mecánica:
  - El gateway expone ``on_state_change: Callable[[str], None]`` en su
    constructor (1.1.3). El setter de ``_connection_state`` lo invoca
    con el nuevo estado SOLO si difiere del anterior (no spam).
  - Aquí creamos un callback que publica al bus.

Este módulo NO toca ``gateway.py``: solo aporta el wiring. El glue
real (``hook_tia_gateway_to_bus``) se llama en 1.1.5 cuando se monte
el router en la app.
"""
from __future__ import annotations

from collections.abc import Callable

from core.infrastructure.gateway import TIAProcessGateway
from core.sse.event_bus import EventBus


def make_tia_state_publisher(bus: EventBus) -> Callable[[str], None]:
    """Devuelve un callback que publica cada estado como evento ``tia_state``.

    Formato del evento: ``{"type": "tia_state", "state": "..."}``.
    El gateway ya garantiza que el callback solo se invoca cuando el
    estado CAMBIA (no en asignaciones idempotentes).
    """

    def publish(state: str) -> None:
        bus.publish({"type": "tia_state", "state": state})

    return publish


def hook_tia_gateway_to_bus(gateway: TIAProcessGateway, bus: EventBus) -> None:
    """Conecta un gateway (típicamente el Singleton) a un ``EventBus``.

    Reasigna ``gateway._on_state_change`` con un publisher al bus.
    Si el gateway no tiene ``_on_state_change`` (p. ej. modo 1-shot),
    no hace nada — los gateways 1-shot no exponen estado persistente.
    """
    on_change = getattr(gateway, "_on_state_change", None)
    if on_change is not None or getattr(gateway, "_persistent", False):
        gateway._on_state_change = make_tia_state_publisher(bus)  # type: ignore[assignment]
