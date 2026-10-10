"""Tests del helper ``validate_plc_in_excel``.

Cobertura:
  - ``plc_name=""`` -> ValueError claro.
  - Sin Excel cargado (cache completo ``None``) -> ValueError claro.
  - PLC en Excel -> OK, no raise.
  - PLC NO en Excel -> ValueError con lista de PLCs disponibles.
  - ``state`` con ``app_cache`` explicito y como ``AppState``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from core.data.data_excel_cache import DataExcelCache
from core.helpers.tia.validate_plc_in_excel import validate_plc_in_excel
from core.runtime.app_cache import AppCache
from core.runtime.app_state import AppState
from core.runtime.excel_cache import excel_set_full


@dataclass(frozen=True)
class _FakePLC:
    plc: str
    uid: int = 0


def _make_cache(plcs: tuple) -> DataExcelCache:
    return DataExcelCache(
        excel_path="/x.xlsx",
        excel_mtime_ns=1,
        parsed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        dispositivos={},
        n_max=type("NMax", (), {"por_plc": ()})(),
        plcs=plcs,
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )


def _make_state(plcs: tuple | None = None) -> AppState:
    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    state = AppState()
    state.app_cache.register_area("alimentacion", AlimentacionAreaCache())
    if plcs is not None:
        excel_set_full(state.app_cache, "alimentacion", _make_cache(plcs))
    return state


def test_plc_name_vacio_lanza_value_error():
    """plc_name='' -> ValueError claro."""
    state = _make_state(plcs=("PLC1",))
    with pytest.raises(ValueError, match="plc_name vacio"):
        validate_plc_in_excel(state, "")


def _make_app_cache_with_alim() -> AppCache:
    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    cache = AppCache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    return cache


def test_sin_excel_lanzado_lanza_value_error():
    """Si excel completo es None -> ValueError claro."""
    state = _make_state(plcs=None)
    with pytest.raises(ValueError, match="No hay Excel cargado"):
        validate_plc_in_excel(state, "PLC1")


def test_plc_en_excel_ok():
    """PLC en Excel -> no raise."""
    state = _make_state(plcs=(
        _FakePLC(plc="PLC1", uid=0),
        _FakePLC(plc="PLC2", uid=1),
    ))
    validate_plc_in_excel(state, "PLC1")
    validate_plc_in_excel(state, "PLC2")


def test_plc_no_en_excel_lanza_value_error():
    """PLC NO en Excel -> ValueError con lista de PLCs disponibles."""
    state = _make_state(plcs=(
        _FakePLC(plc="PLC1", uid=0),
        _FakePLC(plc="PLC2", uid=1),
    ))
    with pytest.raises(ValueError) as exc_info:
        validate_plc_in_excel(state, "PLC_FANTASMA")
    msg = str(exc_info.value)
    assert "PLC_FANTASMA" in msg
    assert "PLC1" in msg
    assert "PLC2" in msg
    assert "no esta en el Excel" in msg


def test_strict_equality_no_normaliza():
    """Strict equality (D11): 'plc1' != 'PLC1'."""
    state = _make_state(plcs=(_FakePLC(plc="PLC1", uid=0),))
    with pytest.raises(ValueError, match="no esta en el Excel"):
        validate_plc_in_excel(state, "plc1")


def test_excel_con_plcs_vacias_lanza():
    """Excel con Tabla_PLC vacia -> cualquier plc_name falla."""
    state = _make_state(plcs=())
    with pytest.raises(ValueError, match=r"\[\]"):
        validate_plc_in_excel(state, "PLC1")


def test_acepta_app_cache_directo():
    """El helper tambien acepta un ``AppCache`` directo (legacy)."""
    cache = _make_app_cache_with_alim()
    excel_set_full(cache, "alimentacion", _make_cache(
        (_FakePLC(plc="PLC1", uid=0),),
    ))
    validate_plc_in_excel(cache, "PLC1")