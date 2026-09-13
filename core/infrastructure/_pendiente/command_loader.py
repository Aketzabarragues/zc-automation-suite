"""Command loader: punto de extensión del worker OT para áreas.

Las áreas registran comandos transaccionales adicionales al
``COMMAND_REGISTRY`` del worker mediante ``AreaSpec.contributes_tia_commands``.
El worker los invoca al import del módulo, antes de aceptar el
primer payload.

**Restricción arquitectónica (`.clinerules` §1):** el worker es el
ÚNICO proceso que importa ``siemens_tia_scripting``. Las áreas NO
importan la DLL directamente: solo aportan ``Callable`` con firma
``(portal, ts, args) -> Any`` que el worker invocará dentro de su
proceso, bajo la misma transacción atómica que cualquier otro
comando del lote.
"""
from __future__ import annotations

from typing import Callable

from core.application.area_registry import AreaRegistry


def load_extra_commands(registry: dict[str, Callable[[object, object, dict], object]]) -> None:
    """Pide a cada área registrada que aporte sus comandos al registry.

    Muta ``registry`` in-place. Es seguro llamar varias veces (los
    handlers se machacan por nombre si dos áreas aportan el mismo
    key; el primero gana, como en un dict literal).

    Args:
        registry: El ``COMMAND_REGISTRY`` del worker, mutable.
    """
    for spec in AreaRegistry.discover().all():
        if spec.contributes_tia_commands is not None:
            spec.contributes_tia_commands(registry)


__all__ = ["load_extra_commands"]
