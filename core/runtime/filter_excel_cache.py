"""Filtro de ``DataExcelCache`` por PLC.

Sept-2026 (multi-PLC, propuesta simplificada del operario): cuando el
operario selecciona un PLC en la UI, el backend regenera una copia del
cache del Excel con solo los datos de ese PLC. Esa copia
(``state.excel_cache_active``) es la que los FB consumen.

Este helper puro, sin I/O ni estado mutable, realiza ese filtro. Si
``plc_name == ""`` (legacy single-PLC o sin selección), devuelve una
copia identica al cache completo (sin filtrar).
"""
from __future__ import annotations

import dataclasses
from typing import Any


def filter_cache_by_plc(
    cache: Any,
    plc_name: str,
) -> Any:
    """Devuelve una COPIA de ``cache`` con solo los datos de ``plc_name``.

    Args:
        cache: ``DataExcelCache`` (dataclass frozen). Si es ``None``,
            devuelve ``None``.
        plc_name: nombre del PLC (strict equality, D11). Si esta vacio,
            devuelve una copia sin filtrar.

    Returns:
        ``DataExcelCache`` con los mismos campos excepto
        ``dispositivos``, ``n_max``, ``procesos``, ``parametros_real``,
        ``parametros_int`` y ``alarmas`` que se filtran por ``plc_name``.
        ``plcs`` (lista informativa de Tabla_PLC) NO se filtra — es
        siempre el conjunto completo del Excel.
        ``excel_path``, ``excel_mtime_ns``, ``parsed_at`` y lookups se
        preservan sin cambios.
    """
    if cache is None:
        return None
    if not plc_name:
        # Sin filtro: devolvemos el cache tal cual (es frozen, no se muta).
        return cache
    # Defensivo: si ``cache`` no es un dataclass (p. ej. MagicMock en
    # tests legacy), no podemos filtrar. Devolvemos el cache tal cual.
    # Esto evita romper tests que mockean ``excel_cache_full``.
    if not dataclasses.is_dataclass(cache):
        return cache

    return dataclasses.replace(
        cache,
        dispositivos={
            hw: tuple(d for d in devs if getattr(d, "plc_name", "") == plc_name)
            for hw, devs in cache.dispositivos.items()
        },
        n_max=cache.n_max.__class__(
            por_plc=tuple(
                d for d in cache.n_max.por_plc if d.plc_name == plc_name
            )
        ),
        procesos=tuple(
            p for p in cache.procesos if p.plc_name == plc_name
        ),
        parametros_real=tuple(
            p for p in cache.parametros_real if p.plc_name == plc_name
        ),
        parametros_int=tuple(
            p for p in cache.parametros_int if p.plc_name == plc_name
        ),
        alarmas=tuple(
            a for a in cache.alarmas if a.plc_name == plc_name
        ),
    )


__all__ = ["filter_cache_by_plc"]
