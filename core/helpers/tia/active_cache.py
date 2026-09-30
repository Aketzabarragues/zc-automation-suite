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


__all__ = ["get_devices", "get_nmax"]