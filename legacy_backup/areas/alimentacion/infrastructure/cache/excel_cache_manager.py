"""Singleton IT del cache del Excel corporativo del subdominio alimentación.

Este módulo aporta el ``ExcelCacheManager``, equivalente IT del
``BloqueCacheManager`` de ``core`` (ver ``core/infrastructure/cache/
bloque_cache_manager.py``) pero con tres diferencias clave:

  1. Cachea **una sola entrada** (``ExcelCache``) por proceso, no un
     ``dict[plc_name, cache]`` por PLC.
  2. Aporta ``wait_for_first_load(timeout)`` con ``asyncio.Event``
     (D4 del operario) para que coroutines puedan esperar al primer
     load del Excel sin polling.
  3. Invalida por ``(excel_path, mtime_ns)`` en vez de por nombre de
     PLC: el Excel es UNO y cambia cuando el operario lo edita o
     sube uno nuevo.

API:
    * ``get() -> ExcelCache | None``
    * ``put(cache) -> None``
    * ``clear() -> None``
    * ``needs_reload(excel_path, excel_mtime_ns) -> bool``
        (lectura atómica, no async — útil en hot paths del router).
    * ``on_excel_reload(excel_path, excel_mtime_ns) -> None``
        (limpia el cache si la tupla nueva difiere).
    * ``wait_for_first_load(timeout) -> ExcelCache | None``
        (bloquea hasta el primer ``put`` o hasta ``timeout``).

Restricción arquitectónica: este módulo NO importa
``siemens_tia_scripting``. Solo usa ``asyncio``, ``logging`` y el
DTO ``ExcelCache`` de ``areas.alimentacion.domain.models``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

from areas.alimentacion.domain.models.excel_cache import ExcelCache


_logger = logging.getLogger(__name__)


class ExcelCacheManager:
    """Singleton por proceso del cache IT del Excel corporativo."""

    _cache: ClassVar[ExcelCache | None] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()
    _first_load_event: ClassVar[asyncio.Event] = asyncio.Event()

    @classmethod
    async def get(cls) -> ExcelCache | None:
        """Devuelve el cache actual o ``None`` si está vacío.

        Returns:
            El ``ExcelCache`` cacheado o ``None`` si nunca se hizo
            un ``put``.
        """
        async with cls._lock:
            return cls._cache

    @classmethod
    async def put(cls, cache: ExcelCache) -> None:
        """Almacena un nuevo ``ExcelCache`` (reemplaza el anterior).

        Si el cache estaba vacío (``_first_load_event`` no estaba
        seteado), lo dispara para desbloquear a las coroutines
        esperando en ``wait_for_first_load``.

        Emite un ``INFO`` con las métricas del cache (procesos, PReal,
        PInt, alarmas, tipos de dispositivos, path).
        """
        async with cls._lock:
            cls._cache = cache
            was_empty = not cls._first_load_event.is_set()
        if was_empty:
            cls._first_load_event.set()
        _logger.info(
            "Cache IT del Excel actualizado: '%s' "
            "(%d procesos, %d PReal, %d PInt, %d alarmas, "
            "%d tipos de dispositivos).",
            cache.excel_path,
            len(cache.procesos),
            len(cache.parametros_real),
            len(cache.parametros_int),
            len(cache.alarmas),
            len(cache.dispositivos),
        )

    @classmethod
    async def clear(cls) -> None:
        """Invalida el cache.

        Si había un cache, emite un ``INFO`` con el path del Excel
        invalidado. Resetea el ``_first_load_event`` para que
        ``wait_for_first_load`` vuelva a bloquear hasta el próximo
        ``put``.
        """
        async with cls._lock:
            victim = cls._cache
            cls._cache = None
            cls._first_load_event.clear()
        if victim is not None:
            _logger.info(
                "Cache IT del Excel invalidado: '%s'.", victim.excel_path
            )

    @classmethod
    def needs_reload(cls, excel_path: str, excel_mtime_ns: int) -> bool:
        """Decide si el cache es stale sin adquirir el lock.

        Útil en hot paths del router (no bloquea el event loop). La
        lectura de referencias atómicas en CPython es segura sin
        lock; el peor caso es leer un valor ligeramente stale, lo
        cual solo afecta a esta decisión y se corrige en el próximo
        ``on_excel_reload``.

        Returns:
            ``True`` si el cache está vacío, si el path difiere, o
            si el ``mtime_ns`` difiere. ``False`` solo si la tupla
            ``(path, mtime_ns)`` coincide exactamente.
        """
        cache = cls._cache  # lectura directa, no async
        if cache is None:
            return True
        if cache.excel_path != excel_path:
            return True
        if cache.excel_mtime_ns != excel_mtime_ns:
            return True
        return False

    @classmethod
    async def on_excel_reload(cls, excel_path: str, excel_mtime_ns: int) -> None:
        """Invalida el cache si la nueva tupla difiere de la cacheada.

        Si la tupla ``(excel_path, excel_mtime_ns)`` coincide con
        la cacheada, es un no-op (el cache sigue siendo válido).
        Si difiere (o el cache está vacío), llama a ``clear()``.
        """
        if cls.needs_reload(excel_path, excel_mtime_ns):
            await cls.clear()

    @classmethod
    async def wait_for_first_load(
        cls, timeout: float | None = None
    ) -> ExcelCache | None:
        """Bloquea hasta que el primer load se complete o expire el timeout.

        Args:
            timeout: segundos a esperar. ``None`` = espera
                indefinida. ``0`` = no espera (testea estado actual).

        Returns:
            El cache actual si el primer ``put`` ocurrió durante la
            espera, o ``None`` si expiró el ``timeout`` o si el
            ``put`` aún no se hizo.
        """
        try:
            await asyncio.wait_for(cls._first_load_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return await cls.get()


__all__ = ["ExcelCacheManager"]
