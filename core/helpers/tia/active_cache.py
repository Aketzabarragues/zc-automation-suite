"""Lectura del cache activo del Excel (filtrado por PLC).

Los FB de alimentacion leen del ``excel_cache_active`` (cache ya
filtrado por ``selected_plc`` en ``parse_excel_to_cache`` /
``with_plc``).

Helpers publicos:
  - ``get_devices(state, hw, area_id)``: lista de devices del cache
    activo para el ``hw_type`` dado, del area indicada.
  - ``get_nmax(state, area_id)``: dict ``{N_Max_<X>: value}`` del PLC
    activo, del area indicada.
  - ``get_nmax_entidades(state, area_id)``: dict ``{"N_MAX_ENTIDAD":
    value}`` del PLC activo (la dimension del array ``ENT`` de
    ``DB6_ENT``), del area indicada.
  - ``get_entidades(state, plc_name, area_id)``: lista de entidades
    del cache activo filtradas por plc_name y area (la lista plana
    del cache activo incluye entidades de TODOS los PLCs).

Si el cache activo del area es ``None``, lanzan ``RuntimeError``
accionable. El caller es responsable de la precondicion (debe haber
Excel cargado y PLC seleccionado).

El ``state`` puede ser un ``AppState`` (compat legacy) o un objeto
con ``app_cache``; la lectura va via ``excel_get_active`` sobre
``app_cache`` con el ``area_id`` que el caller pasa.
"""
from __future__ import annotations

from typing import Any

from core.runtime.excel_cache import excel_get_active


def _resolve_active_cache(state: Any, area_id: str):
    """Lee el cache activo del ``app_cache`` del state para ``area_id``."""
    app_cache = getattr(state, "app_cache", None)
    if app_cache is None:
        return None
    return excel_get_active(app_cache, area_id)


def get_devices(state: Any, hw: str, area_id: str) -> list:
    """Devices del PLC activo para ``hw``, del area indicada.

    Args:
        state: objeto con ``app_cache`` (típicamente ``AppState``).
        hw: tipo de dispositivo (``"ed"``, ``"ea"``, ...).
        area_id: area del cache a leer. Obligatorio.

    Raises:
        RuntimeError: si el cache activo del area es ``None``.
    """
    cache = _resolve_active_cache(state, area_id)
    if cache is None:
        raise RuntimeError(
            "excel_cache_active es None. Cargue primero el Excel con "
            "POST /api/v1/excel/upload."
        )
    return list(cache.dispositivos.get(hw, ()))


def get_nmax(state: Any, area_id: str) -> dict[str, int]:
    """Dict ``{N_Max_<X>: value}`` del PLC activo, del area indicada.

    Si el cache activo tiene exactamente un ``DataDimensionesPLC``
    (caso normal cuando ``selected_plc`` esta seteado), devuelve sus
    ``extras``. Si tiene varios, los une por nombre de columna
    (caso "sin filtro", varios PLCs en cache activo).

    Args:
        state: objeto con ``app_cache`` (típicamente ``AppState``).
        area_id: area del cache a leer. Obligatorio.

    Raises:
        RuntimeError: si el cache activo del area es ``None`` o si
                      ``cache.n_max`` es ``None``.
    """
    cache = _resolve_active_cache(state, area_id)
    if cache is None:
        raise RuntimeError(
            "excel_cache_active es None. Cargue primero el Excel con "
            "POST /api/v1/excel/upload."
        )
    n_max = getattr(cache, "n_max", None)
    if n_max is None:
        raise RuntimeError(
            "excel_cache_active.n_max es None. Excel sin Tabla_Dispositivos."
        )
    por_plc = getattr(n_max, "por_plc", ())
    if len(por_plc) == 1:
        return dict(por_plc[0].extras)
    # Multi-PLC "sin filtro" (>1 PLC en cache activo). Union por
    # nombre de columna; si hay colision el primero gana (los
    # callers deben asumir plc_name del excel completo).
    merged: dict[str, int] = {}
    for plc_dim in por_plc:
        for k, v in plc_dim.extras.items():
            merged.setdefault(k, v)
    return merged


def get_nmax_entidades(state: Any, area_id: str) -> dict[str, int]:
    """Dict ``{"N_MAX_ENTIDAD": value}`` del PLC activo, del area indicada.

    La dimension del array ``ENT`` de ``DB6_ENT`` vive en el campo
    ``n_max_entidades`` del ``DataDimensionesPLC`` (separado del
    dict ``extras`` porque su entrada en ``n_max_catalog`` tiene
    ``hw_type=""``). Por eso ``get_nmax`` NO lo expone: hay un helper
    dedicado para el FB de entidades.

    Si el cache activo tiene exactamente un ``DataDimensionesPLC``
    (caso normal con ``selected_plc``), devuelve
    ``{"N_MAX_ENTIDAD": por_plc[0].n_max_entidades}``. Si tiene
    varios (>1 PLC sin filtro), toma el primero (mismo criterio que
    ``get_nmax``). Si ``por_plc`` esta vacio, devuelve ``{}`` (el
    PLC activo no tiene entrada en ``Tabla_Dimensiones``: el sync
    de entidades no podra comparar contra el Excel, solo contra
    TIA).

    Args:
        state: objeto con ``app_cache`` (típicamente ``AppState``).
        area_id: area del cache a leer. Obligatorio.

    Raises:
        RuntimeError: si el cache activo del area es ``None``.
    """
    cache = _resolve_active_cache(state, area_id)
    if cache is None:
        raise RuntimeError(
            "excel_cache_active es None. Cargue primero el Excel con "
            "POST /api/v1/excel/upload."
        )
    n_max = getattr(cache, "n_max", None)
    if n_max is None:
        return {}
    por_plc = getattr(n_max, "por_plc", ())
    if not por_plc:
        return {}
    return {"N_MAX_ENTIDAD": int(por_plc[0].n_max_entidades)}


def get_entidades(state: Any, plc_name: str, area_id: str) -> list:
    """Entidades del PLC activo filtradas por ``plc_name`` y ``area_id``.

    El cache activo expone ``cache.entidades`` como lista plana
    multi-PLC (``tuple[Entidad, ...]``). Esta funcion filtra por el
    ``plc_name`` del FB para que el diff en el FB
    ``entidades_generar_preview`` opere solo sobre las entidades
    del PLC activo.

    Args:
        state: objeto con ``app_cache`` (típicamente ``AppState``).
        plc_name: nombre del PLC destino (e.g. ``"PLC_S1500"``).
        area_id: area del cache a leer. Obligatorio.

    Raises:
        RuntimeError: si el cache activo del area es ``None``.

    Returns:
        Lista de ``Entidad`` del PLC ``plc_name`` en el area ``area_id``.
        Si el PLC no tiene entidades, devuelve ``[]``.
    """
    cache = _resolve_active_cache(state, area_id)
    if cache is None:
        raise RuntimeError(
            "excel_cache_active es None. Cargue primero el Excel con "
            "POST /api/v1/excel/upload."
        )
    all_entidades = getattr(cache, "entidades", ()) or ()
    return [e for e in all_entidades if getattr(e, "plc_name", "") == plc_name]


__all__ = [
    "get_devices",
    "get_nmax",
    "get_nmax_entidades",
    "get_entidades",
]