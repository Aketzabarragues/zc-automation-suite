"""Manager Singleton del cache IT de bloques PLC en memoria.

Mantiene ``dict[plc_name, BloqueCache]`` a nivel de proceso (estado
clase, NO instancia) para que cualquier consumidor (gateway, use case,
router) vea la misma vista.

API:
  - ``get(plc_name)``: recupera el cache; ``None`` si no hay.
  - ``put(plc_name, cache)``: reemplaza el cache para un PLC.
  - ``clear(plc_name=None)``: borra un PLC concreto (``None`` = todos).
  - ``on_plc_change(old, new)``: invalida ``old`` si difiere de ``new``;
    deja ``new`` intacto (el caller asume que ``new`` acaba de escanearse).

Concurrencia: ``asyncio.Lock`` para serializar ``get/put/clear`` dentro
del event loop. NO usa threading (el cache es IT-side y vive en el
proceso asyncio principal; los workers OT son subprocesos efímeros que
no comparten memoria).

Lifecycle: el manager se reinicia al recargar el proceso (.clinerules §8:
nunca persistir estado entre reinicios). El gateway invalida
explícitamente en ``open_project`` / ``close_project``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

from core.models.bloque_cache import BloqueCache


_logger = logging.getLogger(__name__)


class BloqueCacheManager:
    """Singleton por proceso del cache IT de bloques de PLC."""

    _caches: ClassVar[dict[str, BloqueCache]] = {}
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    @classmethod
    async def get(cls, plc_name: str) -> BloqueCache | None:
        """Devuelve el cache para ``plc_name`` o ``None`` si no existe."""
        async with cls._lock:
            return cls._caches.get(plc_name)

    @classmethod
    async def put(cls, plc_name: str, cache: BloqueCache) -> None:
        """Reemplaza el cache de un PLC concreto.

        Loguea a INFO con el conteo de bloques y tablas para que el
        operario vea en el panel de logs cuando se llena el cache.
        """
        async with cls._lock:
            cls._caches[plc_name] = cache
        _logger.info(
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
                    _logger.info("Cache IT de bloques: vacio (nada que borrar).")
                else:
                    _logger.info(
                        "Cache IT de bloques invalidado por completo (%d PLCs: %s).",
                        total,
                        ", ".join(snapshot),
                    )
                return

            if plc_name in cls._caches:
                victim = cls._caches.pop(plc_name)
                _logger.info(
                    "Invalidando caché de bloques para PLC '%s' (%d bloques, %d tablas)",
                    plc_name,
                    len(victim.blocks),
                    len(victim.tag_tables),
                )
            else:
                _logger.debug(
                    "clear(plc_name=%r): no había cache; no-op.", plc_name
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
