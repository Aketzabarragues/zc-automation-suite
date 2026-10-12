"""Tests de ``core.infrastructure.tia.tia_state_cache``.

Cubre:
  - ``plc_list_get/set/clear``.
  - ``plc_project_get/set/clear`` keyed por plc_name.
  - ``plc_user_constants_get/set/clear`` keyed por plc_name.
  - ``slot=`` en cada mutacion (dispara ``on_change`` con el slot correcto).
"""
from __future__ import annotations

import pytest

from core.data.data_plc_info import PlcInfo, PlcProject
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
from core.runtime.app_cache import AppCache


@pytest.fixture
def cache() -> AppCache:
    return AppCache()


# ── plc_list ──────────────────────────────────────────────────────────


def test_plc_list_set_y_get(cache: AppCache) -> None:
    """``plc_list_set`` reemplaza la lista; ``plc_list_get`` la retorna."""
    assert plc_list_get(cache) == ()
    plcs = (PlcInfo("A", "S7-1500", "192.168.0.1"),
            PlcInfo("B", "S7-1500", "192.168.0.2"))
    plc_list_set(cache, plcs)
    assert plc_list_get(cache) == plcs


def test_plc_list_set_acepta_list(cache: AppCache) -> None:
    """``plc_list_set`` acepta ``list`` (la convierte a ``tuple``)."""
    plc_list_set(cache, [PlcInfo("A", "S7", "")])
    assert isinstance(plc_list_get(cache), tuple)
    assert len(plc_list_get(cache)) == 1


def test_plc_list_clear(cache: AppCache) -> None:
    """``plc_list_clear`` vacia la lista."""
    plc_list_set(cache, [PlcInfo("A", "S7", "")])
    plc_list_clear(cache)
    assert plc_list_get(cache) == ()


# ── plc_project ───────────────────────────────────────────────────────


def test_plc_project_set_get_roundtrip(cache: AppCache) -> None:
    """``set`` + ``get`` recuperan el mismo proyecto keyed por plc_name."""
    proj = PlcProject(name="proj", path="/x.ap16", version="V16")
    plc_project_set(cache, "A", proj)
    assert plc_project_get(cache, "A") is proj
    assert plc_project_get(cache, "OTHER") is None


def test_plc_project_clear_un_plc(cache: AppCache) -> None:
    """``clear(plc_name="A")`` borra solo el de A."""
    plc_project_set(cache, "A", PlcProject("a", "/a", "V15"))
    plc_project_set(cache, "B", PlcProject("b", "/b", "V15"))
    plc_project_clear(cache, "A")
    assert plc_project_get(cache, "A") is None
    assert plc_project_get(cache, "B") is not None


def test_plc_project_clear_todos(cache: AppCache) -> None:
    """``clear()`` (sin plc_name) borra TODOS los proyectos."""
    plc_project_set(cache, "A", PlcProject("a", "/a", "V15"))
    plc_project_set(cache, "B", PlcProject("b", "/b", "V15"))
    plc_project_clear(cache)
    assert plc_project_get(cache, "A") is None
    assert plc_project_get(cache, "B") is None


def test_plc_project_clear_plc_inexistente_es_noop(cache: AppCache) -> None:
    """``clear(plc_name="X")`` sin entry previa: no falla."""
    plc_project_clear(cache, "X")  # no raise


# ── plc_user_constants ────────────────────────────────────────────────


def test_plc_user_constants_set_get_roundtrip(cache: AppCache) -> None:
    """``set`` + ``get`` recuperan el mismo mapping keyed por plc_name."""
    constants = {"N_MAX_DISP_ED": 10, "N_MAX_DISP_EA": 20}
    plc_user_constants_set(cache, "A", constants)
    assert plc_user_constants_get(cache, "A") == constants
    assert plc_user_constants_get(cache, "OTHER") == {}


def test_plc_user_constants_hace_copia_defensiva(cache: AppCache) -> None:
    """``set`` copia el mapping (mutaciones externas no afectan al cache)."""
    constants = {"N_MAX_X": 1}
    plc_user_constants_set(cache, "A", constants)
    constants["N_MAX_X"] = 999  # mutar el dict original
    assert plc_user_constants_get(cache, "A") == {"N_MAX_X": 1}


def test_plc_user_constants_clear_un_plc(cache: AppCache) -> None:
    """``clear(plc_name="A")`` borra solo el de A."""
    plc_user_constants_set(cache, "A", {"N_MAX_X": 1})
    plc_user_constants_set(cache, "B", {"N_MAX_X": 2})
    plc_user_constants_clear(cache, "A")
    assert plc_user_constants_get(cache, "A") == {}
    assert plc_user_constants_get(cache, "B") == {"N_MAX_X": 2}


def test_plc_user_constants_clear_todos(cache: AppCache) -> None:
    """``clear()`` (sin plc_name) borra TODAS las constantes cacheadas."""
    plc_user_constants_set(cache, "A", {"N_MAX_X": 1})
    plc_user_constants_set(cache, "B", {"N_MAX_X": 2})
    plc_user_constants_clear(cache)
    assert plc_user_constants_get(cache, "A") == {}
    assert plc_user_constants_get(cache, "B") == {}


# ── slot= emite on_change ─────────────────────────────────────────────


def test_plc_list_set_emite_on_change_con_slot(cache: AppCache) -> None:
    """``plc_list_set`` dispara ``on_change(slot="plc_list")``."""
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_list_set(cache, [PlcInfo("A", "S7", "")])
    finally:
        cache.on_change(None)

    assert len(captured) == 1
    slot, area_id, plc_name, _value = captured[0]
    assert slot == "plc_list"
    assert area_id is None
    assert plc_name is None


def test_plc_list_clear_emite_on_change_con_slot(cache: AppCache) -> None:
    """``plc_list_clear`` dispara ``on_change(slot="plc_list")``."""
    plc_list_set(cache, [PlcInfo("A", "S7", "")])
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_list_clear(cache)
    finally:
        cache.on_change(None)

    assert any(c[0] == "plc_list" for c in captured)


def test_plc_project_set_emite_on_change_con_slot(cache: AppCache) -> None:
    """``plc_project_set`` dispara ``on_change(slot="plc_project")``."""
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_project_set(
            cache, "A", PlcProject("p", "/p", "V15"),
        )
    finally:
        cache.on_change(None)

    assert len(captured) == 1
    slot, area_id, plc_name, _value = captured[0]
    assert slot == "plc_project"
    assert area_id is None
    assert plc_name is None


def test_plc_project_clear_un_plc_emite_on_change_con_slot(
    cache: AppCache,
) -> None:
    """``plc_project_clear(plc_name)`` dispara ``on_change(slot="plc_project")``."""
    plc_project_set(cache, "A", PlcProject("p", "/p", "V15"))
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_project_clear(cache, "A")
    finally:
        cache.on_change(None)

    assert any(c[0] == "plc_project" for c in captured)


def test_plc_project_clear_todos_emite_on_change_con_slot(
    cache: AppCache,
) -> None:
    """``plc_project_clear()`` (all) dispara ``on_change(slot="plc_project")``."""
    plc_project_set(cache, "A", PlcProject("p", "/p", "V15"))
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_project_clear(cache)
    finally:
        cache.on_change(None)

    assert any(c[0] == "plc_project" for c in captured)


def test_plc_user_constants_set_emite_on_change_con_slot(
    cache: AppCache,
) -> None:
    """``plc_user_constants_set`` dispara ``on_change(slot="plc_user_constants")``."""
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_user_constants_set(cache, "A", {"N_MAX_X": 1})
    finally:
        cache.on_change(None)

    assert len(captured) == 1
    slot, area_id, plc_name, _value = captured[0]
    assert slot == "plc_user_constants"
    assert area_id is None
    assert plc_name is None


def test_plc_user_constants_clear_un_plc_emite_on_change_con_slot(
    cache: AppCache,
) -> None:
    """``plc_user_constants_clear(plc_name)`` dispara ``on_change``."""
    plc_user_constants_set(cache, "A", {"N_MAX_X": 1})
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_user_constants_clear(cache, "A")
    finally:
        cache.on_change(None)

    assert any(c[0] == "plc_user_constants" for c in captured)


def test_plc_user_constants_clear_todos_emite_on_change_con_slot(
    cache: AppCache,
) -> None:
    """``plc_user_constants_clear()`` (all) dispara ``on_change``."""
    plc_user_constants_set(cache, "A", {"N_MAX_X": 1})
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_user_constants_clear(cache)
    finally:
        cache.on_change(None)

    assert any(c[0] == "plc_user_constants" for c in captured)
