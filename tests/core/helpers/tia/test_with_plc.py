"""Tests del helper ``with_plc`` (multi-PLC).

``with_plc(app_cache, plc_name, area_id="alimentacion")``:
  - setea ``app_cache.selected_plc = plc_name``.
  - regenera ``excel_active`` del ``AreaCache`` de ``area_id`` filtrado
    por ese PLC.
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

from areas.alimentacion.state.area_cache import AlimentacionAreaCache
from core.data.data_excel_cache import DataExcelCache
from core.helpers.tia.with_plc import with_plc
from core.runtime.app_cache import AppCache
from core.runtime.excel_cache import excel_set_full


@pytest.fixture
def app_cache() -> AppCache:
    """AppCache con el area ``alimentacion`` registrada."""
    cache = AppCache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    return cache


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


def test_with_plc_setea_selected_plc_y_regenera_cache(app_cache: AppCache):
    """Caso feliz: setea selected_plc y regenera el cache activo."""
    excel_set_full(app_cache, "alimentacion", _make_full())

    with_plc(app_cache, "PLC1")

    state = app_cache.get_state()
    assert state.selected_plc == "PLC1"
    active = app_cache.area("alimentacion").excel_active
    assert active is not None


def test_with_plc_idempotente_si_mismo_plc(app_cache: AppCache):
    """Llamar dos veces con el mismo PLC no regenera el cache."""
    excel_set_full(app_cache, "alimentacion", _make_full())
    with_plc(app_cache, "PLC1")

    # Capturar la instancia actual del cache activo.
    first = app_cache.area("alimentacion").excel_active
    with_plc(app_cache, "PLC1")
    second = app_cache.area("alimentacion").excel_active

    # La misma instancia (no se regenera).
    assert first is second


def test_with_plc_cambia_de_plc_regenera_cache(app_cache: AppCache):
    """Cambiar de PLC regenera el cache activo."""
    excel_set_full(app_cache, "alimentacion", _make_full())
    with_plc(app_cache, "PLC1")
    first = app_cache.area("alimentacion").excel_active

    with_plc(app_cache, "PLC2")
    second = app_cache.area("alimentacion").excel_active

    assert app_cache.get_state().selected_plc == "PLC2"
    # El cache activo se rederiva: instancia nueva.
    assert second is not first or second is None


def test_with_plc_sin_full_no_regenera(app_cache: AppCache):
    """Si no hay cache completo, no regenera (no falla)."""
    with_plc(app_cache, "PLC1")
    state = app_cache.get_state()
    assert state.selected_plc == "PLC1"
    assert app_cache.area("alimentacion").excel_active is None


def test_with_plc_plc_vacio_no_modifica(app_cache: AppCache):
    """plc_name vacio: warning y return, sin tocar el estado."""
    excel_set_full(app_cache, "alimentacion", _make_full())
    with_plc(app_cache, "PLC_PREV")

    with_plc(app_cache, "")

    state = app_cache.get_state()
    assert state.selected_plc == "PLC_PREV"
    # El cache activo queda intacto.
    assert app_cache.area("alimentacion").excel_active is not None
