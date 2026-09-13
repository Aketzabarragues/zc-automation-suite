"""core.sse.cache_subscribe — wire ``TIAProcessGateway`` cache → ``EventBus``.

Conecta un gateway persistente al bus para que cada actualización
del cache IT (``"plcs"`` y ``"project_info"``) se retransmita como
evento en el SSE stream.

Mapeo cache-key → event-type:
    ``"plcs"``         → ``{"type": "plcs", "data": [...]}``
    ``"project_info"`` → ``{"type": "project_info", "data": {...}}``

Cualquier otra key de cache (p. ej. ``"blocks::<plc>::<folder>"``) se
ignora silenciosamente: este módulo solo conoce los dos casos que
el plan 1.1.4 quiere exponer al frontend. Si en el futuro se añade
otro cache público, se amplía este mapeo.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.infrastructure.gateway import TIAProcessGateway
from core.sse.event_bus import EventBus


# Mapeo cache-key → event-type. Mantenido como dict del módulo para
# que sea trivial extenderlo (un test verifica que las keys conocidas
# emiten y las desconocidas se ignoran).
_KEY_TO_TYPE: dict[str, str] = {
    "plcs": "plcs",
    "project_info": "project_info",
}


def make_cache_publisher(bus: EventBus) -> Callable[[str, Any], None]:
    """Devuelve un callback que publica cada actualización de cache
    como evento ``plcs`` o ``project_info`` según la key.

    Keys desconocidas se ignoran (no publican nada). El gateway ya
    garantiza que el callback solo se invoca en updates reales
    (no en cache hits).
    """

    def publish(key: str, value: Any) -> None:
        event_type = _KEY_TO_TYPE.get(key)
        if event_type is None:
            return
        bus.publish({"type": event_type, "data": value})

    return publish


def hook_tia_gateway_cache_to_bus(gateway: TIAProcessGateway, bus: EventBus) -> None:
    """Conecta un gateway (típicamente el Singleton) a un ``EventBus``
    para la publicación de updates de cache.

    Reasigna ``gateway._on_cache_update`` con un publisher al bus.
    Si el gateway no es persistente, no hace nada (el atributo no
    existe en modo 1-shot).
    """
    if not getattr(gateway, "_persistent", False):
        return
    gateway._on_cache_update = make_cache_publisher(bus)  # type: ignore[assignment]
