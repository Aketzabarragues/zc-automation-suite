"""Tests del Singleton ``AppState``.

``AppState`` solo expone ``app_cache`` (el contenedor del proceso).
Los caches del Excel (full + active) y ``selected_plc`` viven en
``app_cache``. Ver ``tests/core/runtime/test_app_cache.py`` y
``tests/core/runtime/test_excel_cache.py`` para la cobertura del
contenido.
"""
from __future__ import annotations

from core.runtime.app_cache import AppCache
from core.runtime.app_state import AppState, get_app_state


def test_defaults():
    """Defaults tras ``AppState()``: solo ``app_cache`` accesible."""
    state = AppState()
    assert state.app_cache is not None
    assert isinstance(state.app_cache, AppCache)


def test_repr_no_filtra_datos_sensibles():
    """``__repr__`` expone el ``app_cache``."""
    state = AppState()
    r = repr(state)
    assert "app_cache" in r


def test_get_app_state_es_singleton():
    """``get_app_state()`` devuelve siempre la misma instancia."""
    a = get_app_state()
    b = get_app_state()
    assert a is b
    assert isinstance(a, AppState)


def test_get_app_state_persiste_atributos():
    """El ``app_cache`` del Singleton persiste entre llamadas."""
    state = get_app_state()
    cache = state.app_cache
    assert get_app_state().app_cache is cache