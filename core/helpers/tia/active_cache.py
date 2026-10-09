"""Lectura del cache activo del Excel (filtrado por PLC).

Los FB de alimentacion leen del ``excel_cache_active`` (cache ya
filtrado por ``selected_plc`` en ``dump_cache_to_state`` /
``with_plc``). Antes cada FB tenia sus propios helpers
``_devices_from_active_cache`` / ``_nmax_from_active_cache``
duplicados, con fallbacks "tests legacy" que ahora ya no aplican
(el ``AppState`` limpio no expone atributos legacy).

Helpers publicos:
  - ``get_devices(state, hw)``: lista de devices del cache activo
    para el ``hw_type`` dado.
  - ``get_nmax(state)``: dict ``{N_Max_<X>: value}`` del PLC activo.
  - ``get_nmax_entidades(state)``: dict ``{"N_MAX_ENTIDAD": value}``
    del PLC activo (la dimension del array ``ENT`` de ``DB6_ENT``).
  - ``get_entidades(state, plc_name)``: lista de entidades del cache
    activo filtradas por plc_name (la lista plana del cache activo
    incluye entidades de TODOS los PLCs).

Si el cache activo es ``None``, lanzan ``RuntimeError`` accionable.
El caller es responsable de la precondicion (debe haber Excel
cargado y PLC seleccionado).
"""
from __future__ import annotations

from typing import Any


def get_devices(state: Any, hw: str) -> list:
    """Devices del PLC activo para ``hw``.

    Lee de ``state.excel_cache_active.dispositivos[hw]``. Cache
    activo es el cache completo filtrado por ``selected_plc`` en
    ``dump_cache_to_state`` / ``with_plc``.

    Raises:
        RuntimeError: si ``state.excel_cache_active`` es ``None``.
    """
    cache = state.excel_cache_active
    if cache is None:
        raise RuntimeError(
            "excel_cache_active es None. Cargue primero el Excel con "
            "POST /api/v1/excel/upload."
        )
    return list(cache.dispositivos.get(hw, ()))


def get_nmax(state: Any) -> dict[str, int]:
    """Dict ``{N_Max_<X>: value}`` del PLC activo.

    Si el cache activo tiene exactamente un ``DataDimensionesPLC``
    (caso normal cuando ``selected_plc`` esta seteado), devuelve sus
    ``extras``. Si tiene varios, los une por nombre de columna
    (caso "sin filtro", varios PLCs en cache activo).

    Raises:
        RuntimeError: si ``state.excel_cache_active`` es ``None``
                      o si ``cache.n_max`` es ``None``.
    """
    cache = state.excel_cache_active
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


def get_nmax_entidades(state: Any) -> dict[str, int]:
    """Dict ``{"N_MAX_ENTIDAD": value}`` del PLC activo.

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

    Raises:
        RuntimeError: si ``state.excel_cache_active`` es ``None``.
    """
    cache = state.excel_cache_active
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


def get_entidades(state: Any, plc_name: str) -> list:
    """Entidades del PLC activo filtradas por ``plc_name``.

    El cache activo expone ``cache.entidades`` como lista plana
    multi-PLC (``tuple[Entidad, ...]``). Esta funcion filtra por el
    ``plc_name`` del FB para que el diff en el FB
    ``entidades_generar_preview`` opere solo sobre las entidades
    del PLC activo.

    Args:
        state: AppState (debe tener ``excel_cache_active``).
        plc_name: nombre del PLC destino (e.g. ``"PLC_S1500"``).

    Raises:
        RuntimeError: si ``state.excel_cache_active`` es ``None``.

    Returns:
        Lista de ``Entidad`` del PLC ``plc_name``. Si el PLC no
        tiene entidades, devuelve ``[]``.
    """
    cache = state.excel_cache_active
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