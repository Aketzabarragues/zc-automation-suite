"""core.runtime.excel_cache - funciones puras sobre app_cache para Excel.

API:
    - ``excel_get_full / excel_set_full / excel_clear_full``
    - ``excel_get_active / excel_set_active / excel_clear_active``
    - ``excel_needs_reload(path, mtime_ns)``
    - ``derive_excel_active(plc_name)`` aplica ``filter_cache_by_plc``
      sobre el cache completo y devuelve el derivado.

Las funciones operan sobre ``AppCache`` (no ``AppState``). Las areas
llaman con su ``area_id`` para acceder a su cache per-area
(``excel_full_by_area[area_id]``).

Los ``area_id`` admitidos son los declarados en ``AreaSpec`` (ej:
``"alimentacion"``). ``excel_clear_*`` acepta ``area_id=None`` para
borrar todos los entries (cabeza cuando el operario hace reset global).
"""
from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable

from core.data.data_excel_cache import DataExcelCache
from core.runtime.app_cache import AppCache
from core.runtime.filter_excel_cache import filter_cache_by_plc


_logger = logging.getLogger(__name__)


def excel_get_full(
    app_cache: AppCache,
    area_id: str,
) -> DataExcelCache | None:
    """Devuelve el cache completo del Excel para ``area_id`` o ``None``."""
    return app_cache.get_state().excel_full_by_area.get(area_id)


def excel_set_full(
    app_cache: AppCache,
    area_id: str,
    cache: DataExcelCache,
) -> None:
    """Almacena el cache completo del Excel para ``area_id``.

    No invalida ``excel_active_by_area``: el caller decide cuando
    rederivar el activo (normalmente ``with_plc`` al cambiar de PLC).
    """
    def _mutate(state):
        full = dict(state.excel_full_by_area)
        full[area_id] = cache
        return dataclasses.replace(state, excel_full_by_area=full)
    app_cache.mutate(_mutate)


def excel_clear_full(
    app_cache: AppCache,
    area_id: str | None = None,
) -> None:
    """Limpia el cache completo del Excel.

    Args:
        area_id: si se da, borra solo el de ese area. Si ``None``,
            borra TODOS los caches completos de todas las areas.
    """
    def _mutate(state):
        if area_id is None:
            return dataclasses.replace(state, excel_full_by_area={})
        full = dict(state.excel_full_by_area)
        full.pop(area_id, None)
        return dataclasses.replace(state, excel_full_by_area=full)
    app_cache.mutate(_mutate)


def excel_get_active(
    app_cache: AppCache,
    area_id: str,
) -> DataExcelCache | None:
    """Devuelve el cache activo (filtrado por PLC) o ``None``."""
    return app_cache.get_state().excel_active_by_area.get(area_id)


def excel_set_active(
    app_cache: AppCache,
    area_id: str,
    cache: DataExcelCache,
) -> None:
    """Almacena el cache activo (filtrado por PLC) para ``area_id``."""
    def _mutate(state):
        active = dict(state.excel_active_by_area)
        active[area_id] = cache
        return dataclasses.replace(state, excel_active_by_area=active)
    app_cache.mutate(_mutate)


def excel_clear_active(
    app_cache: AppCache,
    area_id: str | None = None,
) -> None:
    """Limpia el cache activo.

    Args:
        area_id: si se da, borra solo el de ese area. Si ``None``,
            borra TODOS los caches activos de todas las areas.
    """
    def _mutate(state):
        if area_id is None:
            return dataclasses.replace(state, excel_active_by_area={})
        active = dict(state.excel_active_by_area)
        active.pop(area_id, None)
        return dataclasses.replace(state, excel_active_by_area=active)
    app_cache.mutate(_mutate)


def excel_needs_reload(
    app_cache: AppCache,
    area_id: str,
    excel_path: str,
    mtime_ns: int,
) -> bool:
    """Decide si el cache del Excel esta stale sin escribir.

    Args:
        app_cache: contenedor del proceso.
        area_id: area del cache a inspeccionar.
        excel_path: ruta absoluta del Excel en disco.
        mtime_ns: ``st_mtime_ns`` del Excel en disco.

    Returns:
        ``True`` si el cache esta vacio, si el path difiere, o si el
        ``mtime_ns`` difiere. ``False`` solo si la tupla
        ``(path, mtime_ns)`` coincide exactamente con la cacheada.
    """
    cache = excel_get_full(app_cache, area_id)
    if cache is None:
        return True
    if cache.excel_path != excel_path:
        return True
    if cache.excel_mtime_ns != mtime_ns:
        return True
    return False


def derive_excel_active(
    app_cache: AppCache,
    area_id: str,
    plc_name: str,
) -> DataExcelCache | None:
    """Deriva el cache activo filtrando el completo por ``plc_name``.

    Si no hay cache completo, devuelve ``None``. Si ``plc_name`` es
    ``""``, devuelve el completo sin filtrar (modo "sin filtro").

    Args:
        app_cache: contenedor del proceso.
        area_id: area del cache.
        plc_name: nombre del PLC destino.

    Returns:
        Cache derivado (``DataExcelCache``) o ``None`` si no hay
        completo.
    """
    full = excel_get_full(app_cache, area_id)
    if full is None:
        return None
    return filter_cache_by_plc(full, plc_name)


__all__ = [
    "excel_get_full",
    "excel_set_full",
    "excel_clear_full",
    "excel_get_active",
    "excel_set_active",
    "excel_clear_active",
    "excel_needs_reload",
    "derive_excel_active",
]