"""Tests de ``core.runtime.excel_cache`` (funciones puras sobre app_cache).

Cobertura:
  - ``excel_set_full`` + ``excel_get_full`` roundtrip per-area.
  - ``excel_clear_full`` con y sin ``area_id``.
  - ``excel_set_active`` + ``excel_get_active`` roundtrip per-area.
  - ``excel_clear_active`` con y sin ``area_id``.
  - ``excel_needs_reload`` retorna True/False segun la tupla
    ``(path, mtime_ns)``.
  - ``derive_excel_active`` con cache completo + plc_name.
  - ``derive_excel_active`` con cache completo + plc_name vacio ->
    cache sin filtrar.
  - ``derive_excel_active`` sin cache completo -> ``None``.
  - Aislamiento entre areas: el cache de un area no se ve desde otra.
  - Atomicidad: las mutaciones reemplazan el estado via ``mutate``.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from types import MappingProxyType

from core.data.data_excel_cache import DataExcelCache
from core.runtime.app_cache import AppCache
from core.runtime.excel_cache import (
    derive_excel_active,
    excel_clear_active,
    excel_clear_full,
    excel_get_active,
    excel_get_full,
    excel_needs_reload,
    excel_set_active,
    excel_set_full,
)


def _make_cache(
    path: str = "/tmp/a.xlsx",
    mtime_ns: int = 1,
) -> DataExcelCache:
    """Helper: cache minimo valido."""
    return DataExcelCache(
        excel_path=path,
        excel_mtime_ns=mtime_ns,
        parsed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        dispositivos={},
        n_max=type("NMax", (), {"to_api_dict": staticmethod(lambda: {}),
                                "por_plc": ()})(),
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )


# ── excel_get_full / set_full ─────────────────────────────────────────


def test_get_full_vacio_devuelve_none() -> None:
    """Sin ``set`` previo, ``get_full`` devuelve ``None``."""
    cache = AppCache()
    assert excel_get_full(cache, "alimentacion") is None


def test_set_full_roundtrip() -> None:
    """``set_full`` + ``get_full`` recuperan el mismo cache."""
    cache = AppCache()
    c = _make_cache()
    excel_set_full(cache, "alimentacion", c)
    assert excel_get_full(cache, "alimentacion") is c


def test_set_full_aisla_entre_areas() -> None:
    """El cache de un area no se ve desde otra."""
    cache = AppCache()
    c_alim = _make_cache(path="/alim.xlsx")
    c_otra = _make_cache(path="/otra.xlsx")
    excel_set_full(cache, "alimentacion", c_alim)
    excel_set_full(cache, "otra", c_otra)
    assert excel_get_full(cache, "alimentacion") is c_alim
    assert excel_get_full(cache, "otra") is c_otra
    assert excel_get_full(cache, "no_existe") is None


# ── excel_clear_full ─────────────────────────────────────────────────


def test_clear_full_solo_un_area() -> None:
    """``clear_full(area_id)`` borra solo el de ese area."""
    cache = AppCache()
    excel_set_full(cache, "alimentacion", _make_cache())
    excel_set_full(cache, "otra", _make_cache(path="/x.xlsx"))

    excel_clear_full(cache, "alimentacion")

    assert excel_get_full(cache, "alimentacion") is None
    assert excel_get_full(cache, "otra") is not None


def test_clear_full_sin_area_id_borra_todas() -> None:
    """``clear_full(None)`` borra TODOS los caches completos."""
    cache = AppCache()
    excel_set_full(cache, "alimentacion", _make_cache())
    excel_set_full(cache, "otra", _make_cache(path="/x.xlsx"))

    excel_clear_full(cache)

    assert excel_get_full(cache, "alimentacion") is None
    assert excel_get_full(cache, "otra") is None


def test_clear_full_area_inexistente_no_falla() -> None:
    """``clear_full`` sobre area inexistente es no-op (no ``KeyError``)."""
    cache = AppCache()
    excel_clear_full(cache, "no_existe")  # no raise
    assert excel_get_full(cache, "no_existe") is None


# ── excel_get_active / set_active ────────────────────────────────────


def test_get_active_vacio_devuelve_none() -> None:
    """Sin ``set`` previo, ``get_active`` devuelve ``None``."""
    cache = AppCache()
    assert excel_get_active(cache, "alimentacion") is None


def test_set_active_roundtrip() -> None:
    """``set_active`` + ``get_active`` recuperan el mismo cache."""
    cache = AppCache()
    c = _make_cache(path="/act.xlsx")
    excel_set_active(cache, "alimentacion", c)
    assert excel_get_active(cache, "alimentacion") is c


# ── excel_clear_active ───────────────────────────────────────────────


def test_clear_active_solo_un_area() -> None:
    """``clear_active(area_id)`` borra solo el de ese area."""
    cache = AppCache()
    excel_set_active(cache, "alimentacion", _make_cache())
    excel_set_active(cache, "otra", _make_cache(path="/x.xlsx"))

    excel_clear_active(cache, "alimentacion")

    assert excel_get_active(cache, "alimentacion") is None
    assert excel_get_active(cache, "otra") is not None


def test_clear_active_sin_area_id_borra_todas() -> None:
    """``clear_active(None)`` borra TODOS los caches activos."""
    cache = AppCache()
    excel_set_active(cache, "alimentacion", _make_cache())
    excel_set_active(cache, "otra", _make_cache(path="/x.xlsx"))

    excel_clear_active(cache)

    assert excel_get_active(cache, "alimentacion") is None
    assert excel_get_active(cache, "otra") is None


# ── excel_needs_reload ───────────────────────────────────────────────


def test_needs_reload_sin_cache_devuelve_true() -> None:
    """Sin cache cargado -> necesita reload."""
    cache = AppCache()
    assert excel_needs_reload(cache, "alimentacion", "/x.xlsx", 1) is True


def test_needs_reload_con_tupla_coincide_devuelve_false() -> None:
    """Si la tupla ``(path, mtime_ns)`` coincide, NO necesita reload."""
    cache = AppCache()
    excel_set_full(cache, "alimentacion", _make_cache(path="/x.xlsx", mtime_ns=42))
    assert excel_needs_reload(cache, "alimentacion", "/x.xlsx", 42) is False


def test_needs_reload_path_distinto_devuelve_true() -> None:
    """Path distinto -> necesita reload."""
    cache = AppCache()
    excel_set_full(cache, "alimentacion", _make_cache(path="/x.xlsx", mtime_ns=42))
    assert excel_needs_reload(cache, "alimentacion", "/otro.xlsx", 42) is True


def test_needs_reload_mtime_distinto_devuelve_true() -> None:
    """``mtime_ns`` distinto -> necesita reload."""
    cache = AppCache()
    excel_set_full(cache, "alimentacion", _make_cache(path="/x.xlsx", mtime_ns=42))
    assert excel_needs_reload(cache, "alimentacion", "/x.xlsx", 99) is True


# ── derive_excel_active ──────────────────────────────────────────────


def test_derive_sin_full_devuelve_none() -> None:
    """Sin cache completo, ``derive_excel_active`` devuelve ``None``."""
    cache = AppCache()
    assert derive_excel_active(cache, "alimentacion", "PLC1") is None


def test_derive_full_con_plc_name_vacio() -> None:
    """plc_name vacio -> cache sin filtrar (modo "sin filtro").

    Como nuestro cache minimo no tiene dispositivos, el resultado sera
    un cache vacio con los mismos campos informativos (path, mtime).
    """
    cache = AppCache()
    full = _make_cache(path="/x.xlsx", mtime_ns=1)
    excel_set_full(cache, "alimentacion", full)

    derived = derive_excel_active(cache, "alimentacion", "")

    assert derived is not None
    assert derived.excel_path == full.excel_path
    assert derived.excel_mtime_ns == full.excel_mtime_ns
    # Sin dispositivos en el cache minimo -> vacio.
    assert derived.dispositivos == full.dispositivos


# ── Atomicidad: snapshots no se afectan por mutaciones ──────────────


def test_snapshots_no_se_afectan_por_mutaciones() -> None:
    """Un snapshot de ``get_state`` no se ve mutado por ``set`` posterior."""
    cache = AppCache()
    c1 = _make_cache(path="/1.xlsx")
    excel_set_full(cache, "alimentacion", c1)

    snapshot = cache.get_state()
    assert snapshot.excel_full_by_area["alimentacion"] is c1

    c2 = _make_cache(path="/2.xlsx")
    excel_set_full(cache, "alimentacion", c2)

    assert snapshot.excel_full_by_area["alimentacion"] is c1
    assert excel_get_full(cache, "alimentacion") is c2