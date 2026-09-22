"""Wrappers async para enviar comandos al worker OT.

``SyncTIAClient`` (``core/infrastructure/tia/tia_loop.py``) expone
``submit_and_wait`` como metodo sync. Estos wrappers lo ejecutan en
un hilo separado via ``asyncio.to_thread`` para no bloquear el
event loop mientras el worker OT procesa el comando (los
export/import pueden tardar 1-3 min en PLCs grandes).

Dos APIs publicas:

  - dispatch_async:        1 comando suelto, sin transaccion.
  - dispatch_batch_async:  N comandos en 1 transaccion TIA (atomica
                           con rollback si uno revienta).

Uso::

    from core.helpers.tia.tia_dispatch_async import (
        dispatch_async, dispatch_batch_async,
    )

    # 1 comando sin transaccion
    result = await dispatch_async(
        tia_client,
        "export_block",
        {"plc_name": plc_name, "block_name": db_name, "target_dir": target_dir},
        timeout_s=120.0,
    )

    # N comandos en 1 transaccion TIA (via ``execute_transactional_batch``)
    result = await dispatch_batch_async(
        tia_client,
        [
            {"command": "update_user_constant_value", "args": {...}},
            {"command": "update_user_constant_value", "args": {...}},
        ],
        timeout_s=300.0,
    )

Args:
    tia_client: ``SyncTIAClient`` (o mock en tests).
    command: nombre del comando registrado en el worker OT.
    args: argumentos del comando (dict).
    operations: lista de ``{"command": str, "args": dict}``.
    timeout_s: timeout del dispatch en segundos. Default 60s (1 op)
        o 300s (batch).

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
    """Envia ``command`` al worker OT via ``submit_and_wait`` + ``to_thread``.

    1 comando suelto, sin transaccion. Para N comandos en transaccion
    ver `dispatch_batch_async`.
    """
    dispatch = partial(
        tia_client.submit_and_wait, command, args, timeout_s,
    )
    return await asyncio.to_thread(dispatch)


async def dispatch_batch_async(
    tia_client: Any,
    operations: list[dict[str, Any]],
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Envia ``operations`` al worker OT bajo 1 transaccion TIA atomica.

    Implementacion: dispatcha ``execute_transactional_batch`` (handler
    generico del worker) con la lista de operaciones. Si cualquier
    sub-comando falla, TIA hace rollback de toda la cadena.

    Args:
        tia_client: ``SyncTIAClient`` (o mock en tests).
        operations: lista de ``{"command": str, "args": dict}``.
            Equivalente al input del handler ``execute_transactional_batch``.
        timeout_s: timeout del batch en segundos. Default 300s
            (los batches pueden tardar varios minutos).

    Returns:
        El ``result`` del batch (dict con ``success``, ``details``,
        ``operations_executed``).
    """
    dispatch = partial(
        tia_client.submit_and_wait,
        "execute_transactional_batch",
        {"operations": operations},
        timeout_s,
    )
    return await asyncio.to_thread(dispatch)


__all__ = ["dispatch_async", "dispatch_batch_async"]
