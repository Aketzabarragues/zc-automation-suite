"""Tests del Singleton ``AppState`` (multi-PLC).

El estado global expone 4 atributos:
  - ``excel_path``: ruta del Excel cacheado (str | None).
  - ``excel_cache_full``: cache completo (DataExcelCache o None).
  - ``excel_cache_active``: cache filtrado por ``selected_plc`` (o full).
  - ``selected_plc``: PLC activo (str, "" si ninguno).

No hay API ``set_devices`` / ``get_devices``: los FB leen directamente
del ``excel_cache_active``. Esto evita duplicar datos en el estado.
"""
from __future__ import annotations

from core.runtime.app_state import AppState, get_app_state


def test_defaults():
    """Defaults tras ``AppState()``: caches None, selected_plc vacio."""
    state = AppState()
    assert state.excel_path is None
    assert state.excel_cache_full is None
    assert state.excel_cache_active is None
    assert state.selected_plc == ""


def test_repr_no_filtra_datos_sensibles():
    """``__repr__`` expone solo el PLC y si hay Excel cargado."""
    state = AppState()
    r = repr(state)
    assert "selected_plc=" in r
    assert "excel_loaded=False" in r


def test_excel_cache_full_se_puebla_directamente():
    """``excel_cache_full`` se setea cuando se carga el Excel."""
    state = AppState()
    fake = object()
    state.excel_cache_full = fake
    assert state.excel_cache_full is fake
    # excel_cache_active sigue None hasta que el caller lo filtre.
    assert state.excel_cache_active is None


def test_excel_cache_active_es_distinto_de_full_si_hay_filtro():
    """Si hay PLC activo, el cache activo es la version filtrada
    (distinta instancia del completo)."""
    state = AppState()
    state.excel_cache_full = "FULL"
    state.selected_plc = "PLC1"
    state.excel_cache_active = "ACTIVE_FOR_PLC1"
    assert state.excel_cache_active == "ACTIVE_FOR_PLC1"
    assert state.excel_cache_full != state.excel_cache_active


def test_selected_plc_roundtrip():
    """``selected_plc`` es str plano; roundtrip basico OK."""
    state = AppState()
    state.selected_plc = "PLC1"
    assert state.selected_plc == "PLC1"
    state.selected_plc = ""
    assert state.selected_plc == ""


def test_get_app_state_es_singleton():
    """``get_app_state()`` devuelve siempre la misma instancia."""
    a = get_app_state()
    b = get_app_state()
    assert a is b
    assert isinstance(a, AppState)


def test_get_app_state_persiste_atributos():
    """Los atributos seteados via el Singleton persisten entre llamadas."""
    state = get_app_state()
    state.selected_plc = "PLC_PERSIST"
    state.excel_cache_full = "FULL_PERSIST"
    assert get_app_state().selected_plc == "PLC_PERSIST"
    assert get_app_state().excel_cache_full == "FULL_PERSIST"
    # Limpieza para no contaminar otros tests.
    state.selected_plc = ""
    state.excel_cache_full = None