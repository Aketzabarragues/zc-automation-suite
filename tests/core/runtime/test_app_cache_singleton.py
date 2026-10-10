"""Verifica que ``AppState.app_cache`` es el mismo Singleton que ``get_app_cache()``.

Contrato: ``state.app_cache is get_app_cache()``. Si esto falla, los
FBs (que reciben ``app_cache`` por wiring) escriben en una instancia
distinta de la que el supervisor usa para registrar areas en boot.
Resultado: ``KeyError(area_id)`` al primer ``excel_set_full()``.
"""
from __future__ import annotations

import pytest

from core.runtime.app_cache import get_app_cache
from core.runtime.app_state import AppState, get_app_state


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Aislamiento entre tests: reset de ambos Singletons."""
    import core.runtime.app_cache as _cache_mod
    import core.runtime.app_state as _state_mod
    _cache_mod._app_cache = None
    _state_mod._state = None
    yield
    _cache_mod._app_cache = None
    _state_mod._state = None


def test_get_app_state_app_cache_is_same_as_get_app_cache():
    """``AppState().app_cache is get_app_cache()`` (Singleton unico)."""
    state = get_app_state()
    cache = get_app_cache()
    assert state.app_cache is cache, (
        "AppCache singleton mismatch: state.app_cache y get_app_cache() "
        "deben ser la misma instancia."
    )


def test_app_state_constructor_shares_singleton():
    """``AppState()`` (no via Singleton) tambien comparte el Singleton."""
    state = AppState()
    assert state.app_cache is get_app_cache()


def test_two_app_states_share_singleton():
    """Dos ``AppState()`` apuntan al mismo ``AppCache`` Singleton."""
    s1 = AppState()
    s2 = AppState()
    assert s1.app_cache is s2.app_cache is get_app_cache()
