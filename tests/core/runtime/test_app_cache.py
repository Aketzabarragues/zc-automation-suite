"""Tests del contenedor unico ``AppCache``.

Cubre:
  - ``_AppCacheState`` es frozen (no se puede mutar in-place).
  - ``mutate(fn)`` reemplaza el estado atomicamente bajo lock.
  - ``reset()`` limpia ``_state`` y todas las areas registradas.
  - ``register_area`` lanza ``ValueError`` si el area ya esta registrada.
  - ``area(area_id)`` lanza ``KeyError`` si el area no existe.
  - ``get_app_cache()`` retorna el mismo Singleton en llamadas
    consecutivas (thread-safe).
"""
from __future__ import annotations

import dataclasses
from threading import Thread

import pytest

from core.data.data_block_cache import DataBloqueCache
from core.data.data_plc_info import PlcInfo, PlcProject
from core.runtime.app_cache import (
    AppCache,
    _AppCacheState,  # noqa: PLC2701 (test del modulo interno)
    get_app_cache,
)
from core.runtime.app_state import AppState


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset del Singleton ``get_app_cache()`` antes de cada test.

    El factory mantiene estado global; sin reset, los tests se contaminan.
    """
    import core.runtime.app_cache as _mod
    _mod._app_cache = None
    yield
    _mod._app_cache = None


def test_state_is_frozen_no_mutation_in_place() -> None:
    """Los dataclass frozen no aceptan ``__setattr__``."""
    cache = AppCache()
    state = cache.get_state()
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.selected_plc = "forzado"  # type: ignore[misc]


def test_state_starts_empty() -> None:
    """El estado recien creado esta vacio."""
    cache = AppCache()
    state = cache.get_state()
    assert state.plc_blocks == {}
    assert state.plc_list == ()
    assert state.plc_user_constants == {}
    assert state.plc_project == {}
    assert state.selected_plc == ""
    assert state.excel_full_by_area == {}
    assert state.excel_active_by_area == {}


def test_mutate_replaces_state_atomically() -> None:
    """``mutate(fn)`` ejecuta ``fn`` sobre el estado viejo y reemplaza."""
    cache = AppCache()

    def add_block(state: _AppCacheState) -> _AppCacheState:
        bloques = DataBloqueCache(
            plc_name="S7-1500",
            blocks={},
            tag_tables={},
            udts={},
            scanned_at=None,  # type: ignore[arg-type]
        )
        return dataclasses.replace(
            state, plc_blocks={"S7-1500": bloques},
        )

    cache.mutate(add_block)
    state = cache.get_state()
    assert "S7-1500" in state.plc_blocks
    assert state.plc_blocks["S7-1500"].plc_name == "S7-1500"


def test_get_state_returns_snapshot() -> None:
    """``get_state()`` retorna un snapshot consistente; los siguientes
    ``mutate`` no afectan al snapshot ya entregado."""
    cache = AppCache()
    snapshot1 = cache.get_state()
    cache.mutate(
        lambda s: dataclasses.replace(
            s, plc_list=(PlcInfo(name="X", type="S7", ip=""),),
        ),
    )
    assert snapshot1.plc_list == ()
    snapshot2 = cache.get_state()
    assert snapshot2.plc_list == (PlcInfo(name="X", type="S7", ip=""),)


def test_reset_clears_state_and_areas() -> None:
    """``reset()`` limpia el estado y dispara ``reset()`` en cada area."""

    class _FakeArea:
        def __init__(self) -> None:
            self.reset_called = False

        def reset(self) -> None:
            self.reset_called = True

    cache = AppCache()
    fake = _FakeArea()
    cache.register_area("test", fake)
    cache.mutate(
        lambda s: dataclasses.replace(
            s, plc_list=(PlcInfo(name="X", type="S7", ip=""),),
        ),
    )
    assert cache.get_state().plc_list != ()

    cache.reset()

    assert cache.get_state().plc_list == ()
    assert fake.reset_called is True


def test_register_area_lanza_valueerror_si_duplicado() -> None:
    """``register_area`` con mismo ``area_id`` -> ``ValueError``."""

    class _Area:
        def reset(self) -> None:
            pass

    cache = AppCache()
    cache.register_area("test", _Area())
    with pytest.raises(ValueError, match="ya registrada"):
        cache.register_area("test", _Area())


def test_area_lanza_keyerror_si_no_existe() -> None:
    """``area(area_id)`` retorna el area o ``KeyError``."""
    cache = AppCache()
    with pytest.raises(KeyError):
        cache.area("nope")


def test_get_app_cache_retorna_singleton() -> None:
    """``get_app_cache()`` devuelve la misma instancia siempre."""
    c1 = get_app_cache()
    c2 = get_app_cache()
    assert c1 is c2


def test_get_app_cache_thread_safe() -> None:
    """Multiples hilos llamando ``get_app_cache`` reciben la misma
    instancia."""

    results: list[AppCache] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(get_app_cache())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(results) == 8
    assert all(r is results[0] for r in results)


def test_app_state_tiene_app_cache() -> None:
    """``AppState.app_cache`` existe como atributo de clase y de instancia."""
    # Class-level (MagicMock spec= lo necesita).
    assert "app_cache" in dir(AppState)
    state = AppState()
    assert state.app_cache is not None
    assert isinstance(state.app_cache, AppCache)


def test_app_state_no_comparte_app_cache_entre_instancias() -> None:
    """Cada ``AppState()`` recibe su propia ``AppCache``."""
    s1 = AppState()
    s2 = AppState()
    assert s1.app_cache is not s2.app_cache


def test_plc_info_y_plc_project_son_frozen() -> None:
    """Los dataclass PlcInfo y PlcProject son inmutables."""
    p = PlcInfo(name="X", type="S7", ip="")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.name = "Y"  # type: ignore[misc]

    proj = PlcProject(name="p", path="/x", version="V15.1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        proj.name = "q"  # type: ignore[misc]


def test_estado_per_plc_set_get_clear() -> None:
    """``plc_list_get/set/clear`` opera correctamente."""
    from core.infrastructure.tia.tia_state_cache import (
        plc_list_clear,
        plc_list_get,
        plc_list_set,
        plc_project_clear,
        plc_project_get,
        plc_project_set,
        plc_user_constants_clear,
        plc_user_constants_get,
        plc_user_constants_set,
    )

    cache = AppCache()
    assert plc_list_get(cache) == ()

    plc_list_set(cache, [PlcInfo("A", "S7-1500", "192.168.0.1")])
    assert len(plc_list_get(cache)) == 1
    assert plc_list_get(cache)[0].name == "A"

    plc_list_clear(cache)
    assert plc_list_get(cache) == ()

    # plc_project
    plc_project_set(
        cache, "A", PlcProject(name="proj", path="/p", version="V15"),
    )
    assert plc_project_get(cache, "A").name == "proj"
    assert plc_project_get(cache, "Z") is None

    plc_project_clear(cache, "A")
    assert plc_project_get(cache, "A") is None
    plc_project_set(
        cache, "B", PlcProject(name="proj2", path="/p2", version="V16"),
    )
    plc_project_clear(cache)  # clear all
    assert plc_project_get(cache, "B") is None

    # plc_user_constants
    plc_user_constants_set(cache, "A", {"N_MAX_1": 10, "N_MAX_2": 20})
    assert plc_user_constants_get(cache, "A") == {"N_MAX_1": 10, "N_MAX_2": 20}
    assert plc_user_constants_get(cache, "Z") == {}

    plc_user_constants_clear(cache, "A")
    assert plc_user_constants_get(cache, "A") == {}
    plc_user_constants_set(cache, "B", {"N_MAX_X": 99})
    plc_user_constants_clear(cache)
    assert plc_user_constants_get(cache, "B") == {}