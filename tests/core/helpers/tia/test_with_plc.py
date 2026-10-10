"""Tests del helper ``with_plc`` (multi-PLC).

``with_plc(app_cache, plc_name, area_id="alimentacion")``:
  - setea ``app_cache.selected_plc = plc_name``.
  - regenera ``excel_active_by_area[area_id]`` filtrado por ese PLC.
  - es idempotente: si el PLC ya esta activo Y hay cache activo, no
    hace nada.

Si ``plc_name`` es vacio, emite un warning y NO modifica nada (el
caller deberia pasar un plc_name valido). Si no hay ``excel_full``,
NO falla: simplemente deja el cache activo tal como estaba.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from core.data.data_excel_cache import DataExcelCache
from core.helpers.tia.with_plc import with_plc
from core.runtime.app_cache import AppCache
from core.runtime.excel_cache import excel_set_full


def _make_full(path: str = "/x.xlsx") -> DataExcelCache:
    return DataExcelCache(
        excel_path=path,
        excel_mtime_ns=1,
        parsed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        dispositivos={"ed": (), "ea": ()},
        n_max=_NMaxStub(),
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )


class _NMaxStub:
    def __init__(self, por_plc: tuple = ()) -> None:
        self.por_plc = por_plc


def test_with_plc_setea_selected_plc_y_regenera_cache():
    """Caso feliz: setea selected_plc y regenera el cache activo."""
    cache = AppCache()
    excel_set_full(cache, "alimentacion", _make_full())

    with_plc(cache, "PLC1")

    state = cache.get_state()
    assert state.selected_plc == "PLC1"
    active = state.excel_active_by_area["alimentacion"]
    assert active is not None


def test_with_plc_idempotente_si_mismo_plc():
    """Llamar dos veces con el mismo PLC no regenera el cache."""
    cache = AppCache()
    excel_set_full(cache, "alimentacion", _make_full())
    with_plc(cache, "PLC1")

    # Capturar la instancia actual del cache activo.
    first = cache.get_state().excel_active_by_area["alimentacion"]
    with_plc(cache, "PLC1")
    second = cache.get_state().excel_active_by_area["alimentacion"]

    # La misma instancia (no se regenera).
    assert first is second


def test_with_plc_cambia_de_plc_regenera_cache():
    """Cambiar de PLC regenera el cache activo."""
    cache = AppCache()
    excel_set_full(cache, "alimentacion", _make_full())
    with_plc(cache, "PLC1")
    first = cache.get_state().excel_active_by_area["alimentacion"]

    with_plc(cache, "PLC2")
    second = cache.get_state().excel_active_by_area["alimentacion"]

    assert cache.get_state().selected_plc == "PLC2"
    # El cache activo se rederiva: instancia nueva.
    assert second is not first or second is None


def test_with_plc_sin_full_no_regenera():
    """Si no hay cache completo, no regenera (no falla)."""
    cache = AppCache()
    with_plc(cache, "PLC1")
    state = cache.get_state()
    assert state.selected_plc == "PLC1"
    assert state.excel_active_by_area == {}


def test_with_plc_plc_vacio_no_modifica():
    """plc_name vacio: warning y return, sin tocar el estado."""
    cache = AppCache()
    excel_set_full(cache, "alimentacion", _make_full())
    with_plc(cache, "PLC_PREV")

    with_plc(cache, "")

    state = cache.get_state()
    assert state.selected_plc == "PLC_PREV"
    # El cache activo queda intacto.
    assert "alimentacion" in state.excel_active_by_area