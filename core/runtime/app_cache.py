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
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from core.data.data_block_cache import DataBloqueCache
from core.data.data_block_plc import DataBloquePLC
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

    # Capa 2: Slots de feature (FBs core que cachean por plc).
    # Llave externa = plc_name. Llave interna = path de bloque.
    block_edit_prepared: dict[str, dict[str, DataBloquePLC]] = field(
        default_factory=dict,
    )


class AppCache:
    """Contenedor de todos los caches del proceso."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = _AppCacheState()
        self._areas: dict[str, AreaCacheProtocol] = {}
        self._on_change: (
            Callable[[str, str | None, str | None, Any], None] | None
        ) = None

    def on_change(
        self,
        callback: Callable[[str, str | None, str | None, Any], None] | None,
    ) -> None:
        """Registra el callback invocado tras cada mutacion.

        Firma: ``callback(slot, area_id, plc_name, value)``. ``area_id``
        y ``plc_name`` son ``None`` para slots globales; ``value`` es
        el dict nuevo del slot cuando aplica (o ``None`` para resets).
        Usado por el publisher SSE ``cache_changed`` para emitir un
        delta al frontend.
        """
        with self._lock:
            self._on_change = callback

    def get_state(self) -> _AppCacheState:
        """Snapshot consistente del estado."""
        with self._lock:
            return self._state

    def mutate(
        self,
        fn: Callable[[_AppCacheState], _AppCacheState],
        *,
        slot: str | None = None,
    ) -> None:
        """Aplica ``fn`` al estado y reemplaza atomicamente.

        ``slot`` identifica el campo mutado (clave publica del
        AppCache, p.ej. ``"plc_blocks"``). Si se pasa y hay un
        ``on_change`` registrado, se invoca tras el reemplazo bajo el
        mismo lock con ``(slot, None, None, nuevo_valor)``.
        """
        with self._lock:
            new_state = fn(self._state)
            self._state = new_state
            if slot is not None and self._on_change is not None:
                value = getattr(new_state, slot, None)
                self._on_change(slot, None, None, value)

    # ------------------------------------------------------------------
    # Slots de feature (block-editor): block_edit_prepared
    # Cacheado por FB block_edit_prepare y consumido por
    # block_edit_apply + el router GET /prepared. Sustituye el antiguo
    # slot ad-hoc que se creaba con hasattr + setattr.
    # ------------------------------------------------------------------
    def set_block_edit_prepared(
        self,
        plc_name: str,
        blocks_dict: dict[str, DataBloquePLC],
    ) -> None:
        """Reemplaza atomicamente los bloques preparados para ``plc_name``.

        ``blocks_dict`` keyed por path completo (jerarquia + nombre,
        separador ``/``). ``mutate(slot="block_edit_prepared", ...)``
        garantiza consistencia bajo el lock.
        """
        def _replace(state: _AppCacheState) -> _AppCacheState:
            new_dict = dict(state.block_edit_prepared)
            new_dict[plc_name] = dict(blocks_dict)
            return dataclasses.replace(state, block_edit_prepared=new_dict)
        self.mutate(_replace, slot="block_edit_prepared")

    def get_block_edit_prepared(
        self,
        plc_name: str,
    ) -> dict[str, DataBloquePLC]:
        """Snapshot de los bloques preparados para ``plc_name``. Vacio si no hay."""
        with self._lock:
            return dict(self._state.block_edit_prepared.get(plc_name, {}))

    def clear_block_edit_prepared(self, plc_name: str) -> None:
        """Limpia los bloques preparados para ``plc_name``.

        Llamado por el FB ``block_edit_apply`` despues de un commit
        exitoso para forzar re-lectura en el proximo ``block_edit_prepare``.
        """
        def _remove(state: _AppCacheState) -> _AppCacheState:
            new_dict = dict(state.block_edit_prepared)
            new_dict.pop(plc_name, None)
            return dataclasses.replace(state, block_edit_prepared=new_dict)
        self.mutate(_remove, slot="block_edit_prepared")

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

    def clear(self) -> None:
        """Limpia TODO: state + areas + on_change.

        Llamado por ``MainServiceSupervisor.stop()`` para que el siguiente
        ``start()`` arranque con estado limpio (las areas se re-registran
        via ``AreaSpec.contributes_caches``).

        Complementa a ``reset()``: ``reset()`` mantiene las areas y solo
        limpia sus valores (pensado para desconexion TIA dentro de la
        misma sesion); ``clear()`` borra todo (fin de sesion del
        supervisor).

        Thread-safe bajo ``self._lock``.
        """
        with self._lock:
            self._state = _AppCacheState()
            self._areas = {}
            self._on_change = None

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
        *,
        slot: str | None = None,
    ) -> None:
        """Aplica ``fn`` al area y reemplaza atomicamente.

        ``fn`` recibe el area actual y DEBE retornar un reemplazo
        (típicamente via ``dataclasses.replace(area, ...)``). La
        sustituccion es atomica bajo ``self._lock``.

        ``slot`` identifica el campo del area mutado (p.ej.
        ``"preview_disp"``). Si se pasa y hay un ``on_change``
        registrado, se invoca tras el reemplazo bajo el mismo lock
        con ``(slot, area_id, None, nuevo_valor)``.
        """
        with self._lock:
            if area_id not in self._areas:
                raise KeyError(area_id)
            current = self._areas[area_id]
            d = dict(self._areas)
            d[area_id] = fn(current)
            self._areas = d
            if slot is not None and self._on_change is not None:
                value = getattr(d[area_id], slot, None)
                self._on_change(slot, area_id, None, value)

    def to_api_dict(self) -> dict[str, Any]:
        """Snapshot JSON-serializable del AppCache completo.

        Se envia al frontend en el SSE ``cache_snapshot`` al
        suscribirse. Compone 2 capas:

        - Capa global (PLC): ``selected_plc``, ``plc_list``,
          ``plc_blocks`` (keyed por plc_name), ``plc_project``,
          ``plc_user_constants``.
        - Capa por area: ``areas[<area_id>]`` con todos los slots
          del ``AreaCacheProtocol`` concreto. Si el dataclass del
          area expone ``to_dict()`` o ``to_api_dict()``, se usa;
          si no, ``dataclasses.asdict``. Los ``datetime`` se
          serializan en ISO-8601.
        """
        with self._lock:
            state = self._state
            areas_snapshot = dict(self._areas)

        plc_blocks = {
            name: (
                cache.to_dict() if hasattr(cache, "to_dict")
                else dataclasses.asdict(cache)
            )
            for name, cache in state.plc_blocks.items()
        }
        plc_project = {
            name: (
                proj.to_dict() if hasattr(proj, "to_dict")
                else dataclasses.asdict(proj)
            )
            for name, proj in state.plc_project.items()
        }
        plc_list = [
            info.to_dict() if hasattr(info, "to_dict")
            else dataclasses.asdict(info)
            for info in state.plc_list
        ]

        areas_payload: dict[str, dict[str, Any]] = {}
        for area_id, area in areas_snapshot.items():
            fields = dataclasses.fields(area)
            row: dict[str, Any] = {}
            for f in fields:
                v = getattr(area, f.name)
                if isinstance(v, datetime):
                    row[f.name] = v.isoformat()
                elif hasattr(v, "to_dict"):
                    row[f.name] = v.to_dict()
                elif hasattr(v, "to_api_dict"):
                    row[f.name] = v.to_api_dict()
                else:
                    row[f.name] = v
            areas_payload[area_id] = row

        return {
            "selected_plc": state.selected_plc,
            "plc_list": plc_list,
            "plc_blocks": plc_blocks,
            "plc_project": plc_project,
            "plc_user_constants": {
                name: dict(v) for name, v in state.plc_user_constants.items()
            },
            "areas": areas_payload,
        }


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
