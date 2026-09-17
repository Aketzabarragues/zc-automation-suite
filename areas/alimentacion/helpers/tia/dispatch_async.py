"""Helper compartido: despachar un comando al worker OT via
``submit_and_wait`` + ``asyncio.to_thread``.

El gateway (``SyncTIAClient``) no expone ``export_block``,
``export_plc_tags_xml``, ``execute_transactional_batch`` ni otros
comandos del worker OT como metodos directos. Solo expone
``submit_and_wait(command, args, timeout_s)``, que encola el comando
en el worker persistente y espera el resultado.

Este wrapper DRY-a el patron que antes vivia copiado en 4 lugares
(uno por cada helper de A.5 + A.6):
  - ``helpers/disp/disp_generate_preview.py``
  - ``helpers/disp/disp_Sincronizar.py``
  - ``helpers/proc/proc_generar_preview.py``
  - ``helpers/proc/proc_sincronizar.py``

El patron es IDENTICO en los 4 sitios (misma firma, misma logica),
asi que vive aqui como helper compartido y los 4 modulos lo
importan.

Uso:
    from areas.alimentacion.helpers.tia.dispatch_async import dispatch_async

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
    """Envia un comando al worker OT via ``submit_and_wait`` + ``to_thread``.

    El wrapper sync (``submit_and_wait``) se ejecuta en un thread
    separado via ``asyncio.to_thread`` para no bloquear el event loop
    mientras el worker OT procesa el comando (export/import puede
    tardar 1-3 min en PLCs grandes).
    """
    dispatch = partial(
        tia_client.submit_and_wait, command, args, timeout_s,
    )
    return await asyncio.to_thread(dispatch)


__all__ = ["dispatch_async"]
