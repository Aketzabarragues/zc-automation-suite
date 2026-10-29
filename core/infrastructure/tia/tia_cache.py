"""core.infrastructure.tia.tia_cache - cache IT de bloques PLC + scan helper.

Helpers puros que operan sobre ``AppCache``. El dato vive en el
``AppCache``; este modulo solo expone ``plc_blocks_*`` (lectura / escritura
keyed por plc_name) y ``scan_plc_blocks`` (helper que despacha al
worker OT y reconstruye el ``DataBloqueCache``).

Restricciones arquitectonicas:
  - NO importa ``siemens_tia_scripting``.
  - Solo depende de ``tia_client`` (Singleton core) y ``AppCache``.
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import datetime
from typing import Any

from core.data.data_block_cache import DataBloqueCache
from core.data.data_block_plc import DataBloquePLC
from core.runtime.app_cache import AppCache

logger = logging.getLogger("zc.tia_loop")


# plc_blocks --------------------------------------------------------------

def plc_blocks_get(
    app_cache: AppCache,
    plc_name: str,
) -> DataBloqueCache | None:
    """Devuelve el cache de bloques para ``plc_name`` o ``None``."""
    return app_cache.get_state().plc_blocks.get(plc_name)


def plc_blocks_put(
    app_cache: AppCache,
    plc_name: str,
    cache: DataBloqueCache,
) -> None:
    """Reemplaza el cache de bloques de un PLC concreto.

    Loguea a INFO con el conteo de bloques y tablas para que el
    operario vea en el panel de logs cuando se llena el cache.
    """
    app_cache.mutate(
        lambda s: dataclasses.replace(
            s, plc_blocks={**s.plc_blocks, plc_name: cache},
        ),
        slot="plc_blocks",
    )
    logger.info(
        "Cache IT de bloques actualizado: PLC '%s' (%d bloques, %d tablas).",
        plc_name,
        len(cache.blocks),
        len(cache.tag_tables),
    )


def plc_blocks_clear(
    app_cache: AppCache,
    plc_name: str | None = None,
) -> None:
    """Invalida caches de bloques.

    - ``plc_name=None`` -> vacia TODOS los PLCs cacheados.
    - ``plc_name="X"`` -> borra solo el cache de ``X``.

    Loguea a INFO con el conteo antes de borrar.
    """
    state = app_cache.get_state()
    if plc_name is None:
        snapshot = list(state.plc_blocks.keys())
        total = len(state.plc_blocks)
        app_cache.mutate(lambda s: dataclasses.replace(s, plc_blocks={}), slot="plc_blocks")
        if total == 0:
            logger.info("Cache IT de bloques: vacio (nada que borrar).")
        else:
            logger.info(
                "Cache IT de bloques invalidado por completo (%d PLCs: %s).",
                total,
                ", ".join(snapshot),
            )
        return

    victim = state.plc_blocks.get(plc_name)
    if victim is None:
        logger.debug(
            "clear(plc_name=%r): no habia cache; no-op.",
            plc_name,
        )
        return

    def _clear(s: Any) -> Any:
        d = dict(s.plc_blocks)
        d.pop(plc_name, None)
        return dataclasses.replace(s, plc_blocks=d)

    app_cache.mutate(_clear, slot="plc_blocks")
    logger.info(
        "Invalidando cache de bloques para PLC '%s' (%d bloques, %d tablas)",
        plc_name,
        len(victim.blocks),
        len(victim.tag_tables),
    )


def plc_blocks_list(app_cache: AppCache) -> list[str]:
    """Devuelve los nombres de PLC con cache de bloques."""
    return list(app_cache.get_state().plc_blocks.keys())


def on_plc_change(
    app_cache: AppCache,
    old: str,
    new: str,
) -> None:
    """Invalida ``old`` cuando el operario cambia de PLC activo.

    Si ``old == new`` (caso tipico: el operario re-selecciona el mismo
    PLC en la UI), no hace nada: la cache vigente sigue siendo valida.
    """
    if old == new:
        return
    plc_blocks_clear(app_cache, old)


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


def scan_plc_blocks(
    plc_name: str,
    *,
    force_refresh: bool = False,
    tia_client: Any | None = None,
    app_cache: AppCache | None = None,
    timeout_s: float = 60.0,
) -> DataBloqueCache:
    """Escanea bloques/tag tables/UDTs de un PLC y devuelve el cache fresco.

    Args:
        plc_name: nombre del PLC a escanear.
        force_refresh: si True, invalida la entrada del PLC en el
            ``AppCache`` antes de escanear (cache IT limpio).
        tia_client: cliente TIA inyectado. Si None, usa el Singleton
            ``tia_client`` de ``core.infrastructure.tia.tia_loop``.
        app_cache: AppCache destino. Si None, usa ``get_app_cache()``.
        timeout_s: timeout para ``submit_and_wait`` (segundos).

    Returns:
        ``DataBloqueCache`` con los datos del escaneo. Tambien queda
        cacheado en ``AppCache.plc_blocks`` para lookups posteriores.

    Raises:
        RuntimeError: si el dispatch fallo (``resp.ok == False``).
        TimeoutError: si el worker OT no responde en ``timeout_s``.
    """
    # Importacion local para evitar ciclo: tia_cache -> tia_loop (lazy).
    from core.infrastructure.tia.tia_loop import tia_client as _default_tia_client
    from core.runtime.app_cache import get_app_cache

    client = tia_client if tia_client is not None else _default_tia_client
    cache = app_cache if app_cache is not None else get_app_cache()

    if force_refresh:
        plc_blocks_clear(cache, plc_name)

    # ``submit_and_wait`` es sync (bloquea el hilo que lo llama). El
    # comando OT 'scan_blocks' ya queda loggeado por el wrapper.
    logger.debug(
        f"helper[scan_plc_blocks] plc={plc_name!r} "
        f"force_refresh={force_refresh}"
    )
    resp = client.submit_and_wait(
        "scan_blocks",
        {"plc_name": plc_name},
        timeout=timeout_s,
    )

    if not resp.get("ok"):
        raise RuntimeError(resp.get("error", "scan_blocks failed"))

    bloques_cache = _reconstruct_cache(resp["result"])
    plc_blocks_put(cache, plc_name, bloques_cache)
    logger.debug(
        f"helper[scan_plc_blocks] {plc_name} OK: "
        f"{len(bloques_cache.blocks)} bloques, "
        f"{len(bloques_cache.tag_tables)} tablas, "
        f"{len(bloques_cache.udts)} UDTs"
    )
    return bloques_cache


__all__ = [
    "plc_blocks_get",
    "plc_blocks_put",
    "plc_blocks_clear",
    "plc_blocks_list",
    "on_plc_change",
    "scan_plc_blocks",
]