"""core.runtime.app_cache - contenedor unico de caches del proceso.

Modelo: ``app_cache`` es un DB de PLC. Se accede con
``app_cache.plc_blocks``, ``app_cache.areas[<area>].excel_full``, etc.
No hay referencias a singletons externos: los datos viven dentro.

Regla de actualizacion: el ``_state`` se REEMPLAZA entero atomicamente
bajo ``self._lock``. Los lectores reciben siempre un snapshot consistente.
Las areas registradas se REEMPLAZAN tambien atomicamente, llamando al
metodo ``reset()`` del Protocol para producir una nueva instancia con
defaults. El lock es re-entrante para casos como ``reset()`` anidados.

Regla de inicializacion: las areas se registran en boot desde
``AreaSpec.contributes_caches``; viven en ``self._areas``, separado del
``_state`` reemplazable, porque el reset no debe perder las areas.
"""
from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from core.data.data_block_cache import DataBloqueCache
from core.data.data_plc_info import PlcInfo, PlcProject


@runtime_checkable
class AreaCacheProtocol(Protocol):
    """Contrato que cumple cada cache per-area.

    ``reset`` retorna una NUEVA instancia con defaults. La sustitucion
    atomica es responsabilidad de ``AppCache`` (bajo lock); este
    metodo NO muta in-place.
    """

    def reset(self) -> "AreaCacheProtocol":
        """Nueva instancia con todos los campos en default."""
        ...


@dataclass(frozen=True)
class _AppCacheState:
    """Estado mutable, reemplazable atomicamente. El lock esta fuera."""
    # Capa 1: Datos del PLC (proceso-wide, keyed por plc_name).
    plc_blocks: dict[str, DataBloqueCache] = field(default_factory=dict)
    plc_list: tuple[PlcInfo, ...] = ()
    plc_user_constants: dict[str, Mapping[str, int]] = field(
        default_factory=dict,
    )
    plc_project: dict[str, PlcProject] = field(default_factory=dict)
    selected_plc: str = ""


class AppCache:
    """Contenedor de todos los caches del proceso."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = _AppCacheState()
        self._areas: dict[str, AreaCacheProtocol] = {}

    def get_state(self) -> _AppCacheState:
        """Snapshot consistente del estado."""
        with self._lock:
            return self._state

    def mutate(
        self,
        fn: Callable[[_AppCacheState], _AppCacheState],
    ) -> None:
        """Aplica ``fn`` al estado y reemplaza atomicamente."""
        with self._lock:
            self._state = fn(self._state)

    def reset(self) -> None:
        """Limpia TODO el estado. Llamado al desconectar TIA o cambiar proyecto.

        El ``_state`` se reemplaza entero. Cada area se reemplaza llamando
        a su ``reset()`` del Protocol bajo el lock; las areas registradas
        siguen apuntando al mismo ``area_id``.
        """
        with self._lock:
            self._state = _AppCacheState()
            d = dict(self._areas)
            for area_id in d:
                d[area_id] = d[area_id].reset()
            self._areas = d

    def register_area(
        self,
        area_id: str,
        area_cache: AreaCacheProtocol,
    ) -> None:
        """Boot-only. Registra un area en el cache."""
        with self._lock:
            if area_id in self._areas:
                raise ValueError(
                    f"area {area_id!r} ya registrada",
                )
            self._areas[area_id] = area_cache

    def area(self, area_id: str) -> AreaCacheProtocol:
        """Devuelve el cache del area o ``KeyError``.

        El retorno es la instancia bajo lock; los lectores deben tratarla
        como inmutable (los ``AreaCache`` son frozen dataclass).
        """
        with self._lock:
            if area_id not in self._areas:
                raise KeyError(area_id)
            return self._areas[area_id]

    def mutate_area(
        self,
        area_id: str,
        fn: Callable[[AreaCacheProtocol], AreaCacheProtocol],
    ) -> None:
        """Aplica ``fn`` al area y reemplaza atomicamente.

        ``fn`` recibe el area actual y DEBE retornar un reemplazo
        (típicamente via ``dataclasses.replace(area, ...)``). La
        sustituccion es atomica bajo ``self._lock``.
        """
        with self._lock:
            if area_id not in self._areas:
                raise KeyError(area_id)
            current = self._areas[area_id]
            d = dict(self._areas)
            d[area_id] = fn(current)
            self._areas = d


_app_cache: AppCache | None = None
_app_cache_lock = threading.Lock()


def get_app_cache() -> AppCache:
    """Devuelve la instancia Singleton de ``AppCache`` (thread-safe)."""
    global _app_cache
    if _app_cache is None:
        with _app_cache_lock:
            if _app_cache is None:
                _app_cache = AppCache()
    return _app_cache


__all__ = [
    "AppCache",
    "AreaCacheProtocol",
    "get_app_cache",
]
