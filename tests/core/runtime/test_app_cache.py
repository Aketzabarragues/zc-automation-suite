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
    """``reset()`` limpia el estado y reemplaza cada area con su ``reset()``."""

    class _FakeArea:
        def __init__(self) -> None:
            self.reset_called = False

        def reset(self) -> "_FakeArea":
            self.reset_called = True
            return self

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
        def reset(self) -> "_Area":
            return self

    cache = AppCache()
    cache.register_area("test", _Area())
    with pytest.raises(ValueError, match="ya registrada"):
        cache.register_area("test", _Area())


def test_area_lanza_keyerror_si_no_existe() -> None:
    """``area(area_id)`` retorna el area o ``KeyError``."""
    cache = AppCache()
    with pytest.raises(KeyError):
        cache.area("nope")


def test_area_retorna_el_objeto_registrado() -> None:
    """``area(area_id)`` retorna el mismo objeto que se registro."""

    class _Area:
        def reset(self) -> "_Area":
            return self

    cache = AppCache()
    fake = _Area()
    cache.register_area("test", fake)
    assert cache.area("test") is fake


def test_mutate_area_reemplaza_atomicamente() -> None:
    """``mutate_area`` aplica ``fn`` y reemplaza la instancia bajo lock."""

    class _Area:
        def __init__(self, value: int = 0) -> None:
            self.value = value

        def reset(self) -> "_Area":
            return _Area()

    cache = AppCache()
    area = _Area(value=7)
    cache.register_area("test", area)

    def _incr(current: _Area) -> _Area:
        return _Area(value=current.value + 3)

    cache.mutate_area("test", _incr)

    assert cache.area("test").value == 10


def test_mutate_area_lanza_keyerror_si_no_existe() -> None:
    """``mutate_area`` sobre area inexistente -> ``KeyError``."""

    class _Area:
        def reset(self) -> "_Area":
            return self

    cache = AppCache()
    with pytest.raises(KeyError):
        cache.mutate_area("nope", lambda a: a)


def test_reset_no_pierde_las_areas_registradas() -> None:
    """Tras ``reset()`` las areas siguen registradas (accesibles)."""

    class _Area:
        def reset(self) -> "_Area":
            return _Area()

    cache = AppCache()
    cache.register_area("test", _Area())
    cache.reset()
    # ``area`` debe seguir accesible: el reset no la elimina.
    assert cache.area("test") is not None


def test_clear_wipes_state_areas_and_on_change() -> None:
    """``clear()`` es el fin-de-sesion del supervisor.

    Complementa a ``reset()``: ``reset()`` mantiene las keys de las
    areas y solo limpia valores; ``clear()`` borra TODO (state +
    areas + on_change) para que el siguiente ``start()`` del
    supervisor arranque limpio.
    """
    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    cache = AppCache()

    def callback(slot, area_id, plc_name, value):
        pass

    cache.on_change(callback)
    cache.register_area("alimentacion", AlimentacionAreaCache())
    cache.mutate(lambda s: dataclasses.replace(s, selected_plc="S7-1500"))

    # Sanity: state + area + on_change registrados.
    state = cache.get_state()
    assert state.selected_plc == "S7-1500"
    assert "alimentacion" in list(cache._areas)  # noqa: SLF001
    assert cache._on_change is not None  # noqa: SLF001

    cache.clear()

    # Tras ``clear()`` todo vuelve a defaults: sin state, sin areas,
    # sin callback. El siguiente ``register_area`` con el mismo id
    # NO debe lanzar ``ValueError``.
    state_after = cache.get_state()
    assert state_after.selected_plc == ""
    assert state_after.plc_blocks == {}
    assert state_after.plc_list == ()
    assert cache._areas == {}  # noqa: SLF001
    assert cache._on_change is None  # noqa: SLF001

    # Re-registrar tras ``clear()`` debe funcionar (el bug original
    # del supervisor: "area 'alimentacion' ya registrada" en el 2do
    # start).
    cache.register_area("alimentacion", AlimentacionAreaCache())
    assert cache.area("alimentacion") is not None


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