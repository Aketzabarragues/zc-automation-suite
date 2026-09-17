"""Helper IT para escanear bloques de un PLC y cachear el resultado.

Encapsula la logica comun que cualquier FB o caller usa para
disparar un scan contra TIA Portal y obtener un ``DataBloqueCache``
fresco. Delega en ``tia_client.submit_and_wait("scan_blocks", ...)``
(recibe un dict primitivo desde el worker OT) y reconstruye el
``DataBloqueCache`` a partir del resultado.

El cache de proceso vive en ``TIADataBloqueCache`` (Singleton en
``tia_bloque_cache.py``), accesible via ``.get/.put/.clear``.

Restricciones arquitectonicas:
  - NO importa ``siemens_tia_scripting``.
  - Solo depende de ``tia_client`` (Singleton core) y
    ``TIADataBloqueCache`` (Singleton core).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from functools import partial
from typing import Any

from core.data.data_block_cache import DataBloqueCache
from core.data.data_block_plc import DataBloquePLC
from core.infrastructure.tia.tia_bloque_cache import TIADataBloqueCache
from core.infrastructure.tia.tia_loop import tia_client as _default_tia_client

logger = logging.getLogger("zc.tia_loop")


def _reconstruct_cache(result: dict[str, Any]) -> DataBloqueCache:
    """Reconstruye un ``DataBloqueCache`` desde el dict que devuelve el worker.

    El handler ``_h_scan_blocks`` devuelve un dict con listas de
    ``DataBloquePLC.to_dict()``. Reconstruimos los dataclasses y
    los indexamos por ``normalize_name`` para que los lookups
    case/space-insensitive funcionen.
    """
    return DataBloqueCache(
        plc_name=result["plc_name"],
        blocks={
            DataBloquePLC.normalize_name(b["nombre"]): DataBloquePLC(**b)
            for b in result.get("blocks", [])
        },
        tag_tables={
            DataBloquePLC.normalize_name(t["nombre"]): DataBloquePLC(**t)
            for t in result.get("tag_tables", [])
        },
        udts={
            DataBloquePLC.normalize_name(u["nombre"]): DataBloquePLC(**u)
            for u in result.get("udts", [])
        },
        scanned_at=datetime.fromisoformat(result["scanned_at"]),
    )


async def scan_plc_blocks(
    plc_name: str,
    *,
    force_refresh: bool = False,
    tia_client: Any | None = None,
    timeout_s: float = 60.0,
) -> DataBloqueCache:
    """Escanea bloques/tag tables/UDTs de un PLC y devuelve el cache fresco.

    Args:
        plc_name: nombre del PLC a escanear.
        force_refresh: si True, invalida la entrada del PLC en
            ``TIADataBloqueCache`` antes de escanear (cache IT limpio).
        tia_client: cliente TIA inyectado. Si None, usa el Singleton
            ``tia_client`` de ``core.infrastructure.tia.tia_loop``.
        timeout_s: timeout para ``submit_and_wait`` (segundos).

    Returns:
        ``DataBloqueCache`` con los datos del escaneo. Tambien queda
        cacheado en ``TIADataBloqueCache`` para lookups posteriores.

    Raises:
        RuntimeError: si el dispatch fallo (``resp.ok == False``).
        TimeoutError: si el worker OT no responde en ``timeout_s``.
    """
    client = tia_client if tia_client is not None else _default_tia_client

    if force_refresh:
        await TIADataBloqueCache.clear(plc_name)

    # ``submit_and_wait`` es sync (bloquea el thread). Lo envolvemos
    # en ``to_thread`` para no bloquear el event loop de asyncio.
    # El comando OT 'scan_blocks' ya queda loggeado por el decorador
    # ``@log_ot_command`` en ``tia_handlers._h_scan_blocks``. Aqui
    # loggeamos solo el wrapper IT (force_refresh, reconstruct, put).
    logger.debug(
        f"helper[scan_plc_blocks] plc={plc_name!r} "
        f"force_refresh={force_refresh}"
    )
    dispatch = partial(
        client.submit_and_wait,
        "scan_blocks",
        {"plc_name": plc_name},
        timeout_s,
    )
    resp = await asyncio.to_thread(dispatch)

    if not resp.get("ok"):
        raise RuntimeError(resp.get("error", "scan_blocks failed"))

    cache = _reconstruct_cache(resp["result"])
    await TIADataBloqueCache.put(plc_name, cache)
    logger.debug(
        f"helper[scan_plc_blocks] {plc_name} OK: "
        f"{len(cache.blocks)} bloques, {len(cache.tag_tables)} tablas, "
        f"{len(cache.udts)} UDTs"
    )
    return cache


__all__ = ["scan_plc_blocks"]
