"""Wrapper async para enviar un comando al worker OT.

``SyncTIAClient`` (``core/infrastructure/tia/tia_loop.py``) expone
``submit_and_wait`` como metodo sync. Este wrapper lo ejecuta en
un hilo separado via ``asyncio.to_thread`` para no bloquear el
event loop mientras el worker OT procesa el comando (los
export/import pueden tardar 1-3 min en PLCs grandes).

Uso::

    from core.helpers.tia.tia_dispatch_async import dispatch_async

    result = await dispatch_async(
        tia_client,
        "export_block",
        {"plc_name": plc_name, "block_name": db_name, "target_dir": target_dir},
        timeout_s=120.0,
    )

Args:
    tia_client: ``SyncTIAClient`` (o mock en tests).
    command: nombre del comando registrado en el worker OT.
    args: argumentos del comando (dict).
    timeout_s: timeout del dispatch en segundos. Default 60s.

Returns:
    El ``result`` del worker OT (dict). En tests, lo que devuelva
    el mock.
"""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Any


async def dispatch_async(
    tia_client: Any,
    command: str,
    args: dict[str, Any],
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Envia ``command`` al worker OT via ``submit_and_wait`` + ``to_thread``."""
    dispatch = partial(
        tia_client.submit_and_wait, command, args, timeout_s,
    )
    return await asyncio.to_thread(dispatch)


__all__ = ["dispatch_async"]
