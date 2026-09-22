"""core.infrastructure.tia.tia_cache - cache IT de bloques PLC + scan helper.

Fusion de los antiguos ``tia_bloque_cache.py`` (Singleton TIADataBloqueCache)
y ``scan_plc_blocks.py`` (wrapper async que dispara ``scan_blocks`` contra
el worker OT y reconstruye el ``DataBloqueCache``).

Dominio unico: estado IT de bloques PLC (memoria de proceso, no toca
TIA directamente). Coexiste en core/ porque:

  - El cache es estado de proceso (acceden routers, FBs, scanners).
  - El scan helper es el unico consumidor canonico del cache: dispara
    el comando ``scan_blocks`` del worker OT, reconstruye el dataclass
    desde el dict primitivo y guarda en el cache.

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
from typing import TYPE_CHECKING, Any, ClassVar

from core.data.data_block_cache import DataBloqueCache
from core.data.data_block_plc import DataBloquePLC

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


# ---------------------------------------------------------------------------
# Singleton IT: cache de bloques por PLC
# ---------------------------------------------------------------------------
class TIADataBloqueCache:
    """Singleton por proceso del cache IT de bloques de PLC."""

    _caches: ClassVar[dict[str, DataBloqueCache]] = {}
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    @classmethod
    async def get(cls, plc_name: str) -> DataBloqueCache | None:
        """Devuelve el cache para ``plc_name`` o ``None`` si no existe."""
        async with cls._lock:
            return cls._caches.get(plc_name)

    @classmethod
    async def put(cls, plc_name: str, cache: DataBloqueCache) -> None:
        """Reemplaza el cache de un PLC concreto.

        Loguea a INFO con el conteo de bloques y tablas para que el
        operario vea en el panel de logs cuando se llena el cache.
        """
        async with cls._lock:
            cls._caches[plc_name] = cache
        logger.info(
            "Cache IT de bloques actualizado: PLC '%s' (%d bloques, %d tablas).",
            plc_name,
            len(cache.blocks),
            len(cache.tag_tables),
        )

    @classmethod
    async def clear(cls, plc_name: str | None = None) -> None:
        """Invalida caches.

        - ``plc_name=None`` → vacía TODOS los PLCs cacheados.
        - ``plc_name="X"``  → borra solo el cache de ``X``.

        Loguea a INFO con el conteo antes de borrar.
        """
        async with cls._lock:
            if plc_name is None:
                # Snapshot de nombres antes de mutar.
                snapshot = list(cls._caches.keys())
                total = len(cls._caches)
                cls._caches.clear()
                if total == 0:
                    logger.info("Cache IT de bloques: vacio (nada que borrar).")
                else:
                    logger.info(
                        "Cache IT de bloques invalidado por completo (%d PLCs: %s).",
                        total,
                        ", ".join(snapshot),
                    )
                return

            if plc_name in cls._caches:
                victim = cls._caches.pop(plc_name)
                logger.info(
                    "Invalidando caché de bloques para PLC '%s' (%d bloques, %d tablas)",
                    plc_name,
                    len(victim.blocks),
                    len(victim.tag_tables),
                )
            else:
                logger.debug(
                    "clear(plc_name=%r): no había cache; no-op.",
                    plc_name,
                )

    @classmethod
    async def on_plc_change(cls, old: str, new: str) -> None:
        """Invalida ``old`` cuando el operario cambia de PLC activo.

        Si ``old == new`` (caso típico: el operario re-selecciona el
        mismo PLC en la UI), no hace nada: la cache vigente sigue
        siendo válida.
        """
        if old == new:
            return
        await cls.clear(old)


# ---------------------------------------------------------------------------
# Scan helper: dispara el comando ``scan_blocks`` contra el worker OT y
# reconstruye el dataclass desde el dict primitivo.
# ---------------------------------------------------------------------------
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
    # Importacion local para evitar ciclo: tia_cache -> tia_loop (solo TYPE_CHECKING).
    from core.infrastructure.tia.tia_loop import tia_client as _default_tia_client

    client = tia_client if tia_client is not None else _default_tia_client

    if force_refresh:
        await TIADataBloqueCache.clear(plc_name)

    # ``submit_and_wait`` es sync (bloquea el thread). Lo envolvemos
    # en ``to_thread`` para no bloquear el event loop de asyncio.
    # El comando OT 'scan_blocks' ya queda loggeado por el wrapper.
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


__all__ = ["TIADataBloqueCache", "scan_plc_blocks"]