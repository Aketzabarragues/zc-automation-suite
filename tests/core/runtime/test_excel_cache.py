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
  - Atomicidad: las mutaciones del area reemplazan via ``mutate_area``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType

import pytest

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


@pytest.fixture
def cache_with_alim() -> AppCache:
    """AppCache con ``AlimentacionAreaCache`` registrado en ``alimentacion``."""
    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    cache = AppCache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    return cache


@pytest.fixture
def cache_with_two_areas() -> AppCache:
    """AppCache con dos areas registradas (``alimentacion`` + ``otra``).

    ``otra`` usa una subclase minima con los atributos ``excel_full`` /
    ``excel_active`` para validar el aislamiento.
    """
    from dataclasses import dataclass
    from typing import Any

    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    @dataclass(frozen=True)
    class _OtraCache:
        excel_full: Any = None
        excel_active: Any = None

        def reset(self) -> "_OtraCache":
            return _OtraCache()

    cache = AppCache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    cache.register_area("otra", _OtraCache())
    return cache


# ── excel_get_full / set_full ─────────────────────────────────────────


def test_get_full_vacio_devuelve_none(cache_with_alim: AppCache) -> None:
    """Sin ``set`` previo, ``get_full`` devuelve ``None``."""
    assert excel_get_full(cache_with_alim, "alimentacion") is None


def test_get_full_area_no_registrada_devuelve_none() -> None:
    """``get_full`` sobre area no registrada devuelve ``None`` (no ``KeyError``)."""
    cache = AppCache()
    assert excel_get_full(cache, "no_existe") is None


def test_set_full_roundtrip(cache_with_alim: AppCache) -> None:
    """``set_full`` + ``get_full`` recuperan el mismo cache."""
    c = _make_cache()
    excel_set_full(cache_with_alim, "alimentacion", c)
    assert excel_get_full(cache_with_alim, "alimentacion") is c


def test_set_full_aisla_entre_areas(cache_with_two_areas: AppCache) -> None:
    """El cache de un area no se ve desde otra."""
    c_alim = _make_cache(path="/alim.xlsx")
    c_otra = _make_cache(path="/otra.xlsx")
    excel_set_full(cache_with_two_areas, "alimentacion", c_alim)
    excel_set_full(cache_with_two_areas, "otra", c_otra)
    assert excel_get_full(cache_with_two_areas, "alimentacion") is c_alim
    assert excel_get_full(cache_with_two_areas, "otra") is c_otra
    assert excel_get_full(cache_with_two_areas, "no_existe") is None


# ── excel_clear_full ─────────────────────────────────────────────────


def test_clear_full_solo_un_area(cache_with_two_areas: AppCache) -> None:
    """``clear_full(area_id)`` borra solo el de ese area."""
    excel_set_full(cache_with_two_areas, "alimentacion", _make_cache())
    excel_set_full(cache_with_two_areas, "otra", _make_cache(path="/x.xlsx"))

    excel_clear_full(cache_with_two_areas, "alimentacion")

    assert excel_get_full(cache_with_two_areas, "alimentacion") is None
    assert excel_get_full(cache_with_two_areas, "otra") is not None


def test_clear_full_sin_area_id_borra_todas(cache_with_two_areas: AppCache) -> None:
    """``clear_full(None)`` borra TODOS los caches completos."""
    excel_set_full(cache_with_two_areas, "alimentacion", _make_cache())
    excel_set_full(cache_with_two_areas, "otra", _make_cache(path="/x.xlsx"))

    excel_clear_full(cache_with_two_areas)

    assert excel_get_full(cache_with_two_areas, "alimentacion") is None
    assert excel_get_full(cache_with_two_areas, "otra") is None


def test_clear_full_area_inexistente_no_falla() -> None:
    """``clear_full`` sobre area inexistente es no-op (no ``KeyError``)."""
    cache = AppCache()
    excel_clear_full(cache, "no_existe")  # no raise


# ── excel_get_active / set_active ────────────────────────────────────


def test_get_active_vacio_devuelve_none(cache_with_alim: AppCache) -> None:
    """Sin ``set`` previo, ``get_active`` devuelve ``None``."""
    assert excel_get_active(cache_with_alim, "alimentacion") is None


def test_set_active_roundtrip(cache_with_alim: AppCache) -> None:
    """``set_active`` + ``get_active`` recuperan el mismo cache."""
    c = _make_cache(path="/act.xlsx")
    excel_set_active(cache_with_alim, "alimentacion", c)
    assert excel_get_active(cache_with_alim, "alimentacion") is c


# ── excel_clear_active ───────────────────────────────────────────────


def test_clear_active_solo_un_area(cache_with_two_areas: AppCache) -> None:
    """``clear_active(area_id)`` borra solo el de ese area."""
    excel_set_active(cache_with_two_areas, "alimentacion", _make_cache())
    excel_set_active(cache_with_two_areas, "otra", _make_cache(path="/x.xlsx"))

    excel_clear_active(cache_with_two_areas, "alimentacion")

    assert excel_get_active(cache_with_two_areas, "alimentacion") is None
    assert excel_get_active(cache_with_two_areas, "otra") is not None


def test_clear_active_sin_area_id_borra_todas(cache_with_two_areas: AppCache) -> None:
    """``clear_active(None)`` borra TODOS los caches activos."""
    excel_set_active(cache_with_two_areas, "alimentacion", _make_cache())
    excel_set_active(cache_with_two_areas, "otra", _make_cache(path="/x.xlsx"))

    excel_clear_active(cache_with_two_areas)

    assert excel_get_active(cache_with_two_areas, "alimentacion") is None
    assert excel_get_active(cache_with_two_areas, "otra") is None


# ── excel_needs_reload ───────────────────────────────────────────────


def test_needs_reload_sin_cache_devuelve_true(
    cache_with_alim: AppCache,
) -> None:
    """Sin cache cargado -> necesita reload."""
    assert excel_needs_reload(cache_with_alim, "alimentacion", "/x.xlsx", 1) is True


def test_needs_reload_con_tupla_coincide_devuelve_false(
    cache_with_alim: AppCache,
) -> None:
    """Si la tupla ``(path, mtime_ns)`` coincide, NO necesita reload."""
    excel_set_full(
        cache_with_alim, "alimentacion",
        _make_cache(path="/x.xlsx", mtime_ns=42),
    )
    assert excel_needs_reload(
        cache_with_alim, "alimentacion", "/x.xlsx", 42,
    ) is False


def test_needs_reload_path_distinto_devuelve_true(
    cache_with_alim: AppCache,
) -> None:
    """Path distinto -> necesita reload."""
    excel_set_full(
        cache_with_alim, "alimentacion",
        _make_cache(path="/x.xlsx", mtime_ns=42),
    )
    assert excel_needs_reload(
        cache_with_alim, "alimentacion", "/otro.xlsx", 42,
    ) is True


def test_needs_reload_mtime_distinto_devuelve_true(
    cache_with_alim: AppCache,
) -> None:
    """``mtime_ns`` distinto -> necesita reload."""
    excel_set_full(
        cache_with_alim, "alimentacion",
        _make_cache(path="/x.xlsx", mtime_ns=42),
    )
    assert excel_needs_reload(
        cache_with_alim, "alimentacion", "/x.xlsx", 99,
    ) is True


# ── derive_excel_active ──────────────────────────────────────────────


def test_derive_sin_full_devuelve_none(cache_with_alim: AppCache) -> None:
    """Sin cache completo, ``derive_excel_active`` devuelve ``None``."""
    assert derive_excel_active(cache_with_alim, "alimentacion", "PLC1") is None


def test_derive_full_con_plc_name_vacio(
    cache_with_alim: AppCache,
) -> None:
    """plc_name vacio -> cache sin filtrar (modo "sin filtro").

    Como nuestro cache minimo no tiene dispositivos, el resultado sera
    un cache vacio con los mismos campos informativos (path, mtime).
    """
    full = _make_cache(path="/x.xlsx", mtime_ns=1)
    excel_set_full(cache_with_alim, "alimentacion", full)

    derived = derive_excel_active(cache_with_alim, "alimentacion", "")

    assert derived is not None
    assert derived.excel_path == full.excel_path
    assert derived.excel_mtime_ns == full.excel_mtime_ns
    # Sin dispositivos en el cache minimo -> vacio.
    assert derived.dispositivos == full.dispositivos


# ── Atomicidad: snapshots no se afectan por mutaciones ──────────────


def test_snapshots_no_se_afectan_por_mutaciones(
    cache_with_alim: AppCache,
) -> None:
    """Un snapshot del area no se ve mutado por ``set`` posterior."""
    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    c1 = _make_cache(path="/1.xlsx")
    excel_set_full(cache_with_alim, "alimentacion", c1)

    snapshot = cache_with_alim.area("alimentacion")
    assert isinstance(snapshot, AlimentacionAreaCache)
    assert snapshot.excel_full is c1

    c2 = _make_cache(path="/2.xlsx")
    excel_set_full(cache_with_alim, "alimentacion", c2)

    assert snapshot.excel_full is c1
    assert excel_get_full(cache_with_alim, "alimentacion") is c2


# ── slot= emite on_change ───────────────────────────────────────────────


def test_set_full_emite_on_change_con_slot_excel_full(
    cache_with_alim: AppCache,
) -> None:
    """``excel_set_full`` dispara ``on_change`` con ``slot="excel_full"``."""
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache_with_alim.on_change(cb)
    try:
        c = _make_cache(path="/x.xlsx")
        excel_set_full(cache_with_alim, "alimentacion", c)
    finally:
        cache_with_alim.on_change(None)

    assert len(captured) == 1
    slot, area_id, plc_name, value = captured[0]
    assert slot == "excel_full"
    assert area_id == "alimentacion"
    assert plc_name is None
    assert value is c


def test_clear_full_emite_on_change_con_slot_excel_full(
    cache_with_two_areas: AppCache,
) -> None:
    """``excel_clear_full(area_id)`` dispara ``on_change(slot="excel_full")``."""
    excel_set_full(cache_with_two_areas, "alimentacion", _make_cache())

    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache_with_two_areas.on_change(cb)
    try:
        excel_clear_full(cache_with_two_areas, "alimentacion")
    finally:
        cache_with_two_areas.on_change(None)

    assert any(c[0] == "excel_full" for c in captured)


def test_set_active_emite_on_change_con_slot_excel_active(
    cache_with_alim: AppCache,
) -> None:
    """``excel_set_active`` dispara ``on_change`` con ``slot="excel_active"``."""
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache_with_alim.on_change(cb)
    try:
        c = _make_cache(path="/act.xlsx")
        excel_set_active(cache_with_alim, "alimentacion", c)
    finally:
        cache_with_alim.on_change(None)

    assert len(captured) == 1
    slot, area_id, plc_name, value = captured[0]
    assert slot == "excel_active"
    assert area_id == "alimentacion"
    assert plc_name is None
    assert value is c


def test_clear_active_emite_on_change_con_slot_excel_active(
    cache_with_two_areas: AppCache,
) -> None:
    """``excel_clear_active(area_id)`` dispara ``on_change(slot="excel_active")``."""
    excel_set_active(cache_with_two_areas, "alimentacion", _make_cache())

    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache_with_two_areas.on_change(cb)
    try:
        excel_clear_active(cache_with_two_areas, "alimentacion")
    finally:
        cache_with_two_areas.on_change(None)

    assert any(c[0] == "excel_active" for c in captured)
