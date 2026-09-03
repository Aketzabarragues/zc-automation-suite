"""Tests del ``AppState`` genérico (Plan: Bounded Contexts — PR 1+2).

Cubre la API data-driven del Singleton:
  - ``get_devices`` / ``set_devices`` / ``reset``.
  - ``list_hw_types`` / ``all_devices`` / ``__iter__`` / ``__contains__``.
  - ``dimensiones`` (placeholder de back-compat, ``Any = None``).
  - Single-tenant: ``get_app_state()`` retorna SIEMPRE la misma instancia.

Tras PR 2, las 6 properties legacy (``dispositivos_ed/ea/sa/v/m/m_vf``)
vienen aportadas por ``areas.alimentacion.application.disp_state_extensions``;
este módulo las prueba invocando ``install`` explícitamente (el
Singleton las activa perezosamente, pero las ``AppState`` "frescas"
de los tests también las necesitan para validar back-compat).

Tests OFFLINE puros (sin gateway, sin TIA).
"""
from __future__ import annotations

from typing import Any

import pytest

from core.application.state import AppState, get_app_state


# ── Activación de las properties legacy para los tests ────────────────
# Las 6 properties ``dispositivos_*`` se añaden a la CLASE ``AppState``
# al importarse el ``__init__`` del área (vía ``get_app_state()``) o
# cuando algún test las solicita. Importamos el módulo del área
# explícitamente: su ``__init__`` registra la ``AREA_SPEC`` y las
# properties quedan disponibles al instanciar ``AppState()`` aquí.
from areas.alimentacion.application.disp_state_extensions import (  # noqa: E402, F401
    install as _install_legacy_state_props,
)


@pytest.fixture(autouse=True)
def _ensure_legacy_state_props_installed() -> None:
    """Pega las 6 properties legacy a ``AppState`` antes de cada test.

    El área de alimentación las instala en ``get_app_state()`` (vía
    ``AreaSpec.contributes_state_extensions``). En estos tests instanciamos
    ``AppState()`` directamente sin pasar por el Singleton, así que las
    añadimos explícitamente. El ``install`` es idempotente: solo
    re-asigna el ``property`` a la clase.
    """
    _install_legacy_state_props(None)


@pytest.fixture
def fresh_state() -> AppState:
    """Devuelve un ``AppState`` nuevo (no el Singleton global)."""
    return AppState()


# ────────────────────────────────────────────────────────────────────────
# API data-driven
# ────────────────────────────────────────────────────────────────────────


def test_get_devices_empty_for_unknown_hw_type(fresh_state: AppState) -> None:
    """``get_devices`` retorna ``[]`` para un hw_type que aún no existe."""
    assert fresh_state.get_devices("ed") == []
    assert fresh_state.get_devices("m_sina") == []
    assert fresh_state.get_devices("anything") == []


def test_set_then_get_devices_roundtrip(fresh_state: AppState) -> None:
    """Tras ``set_devices``, ``get_devices`` devuelve la misma lista."""
    sample: list[Any] = [{"uid": "ED_001"}, {"uid": "ED_002"}]
    fresh_state.set_devices("ed", sample)
    assert fresh_state.get_devices("ed") == sample


def test_set_devices_copies_input_list(fresh_state: AppState) -> None:
    """``set_devices`` copia defensivamente: mutar la lista externa no
    afecta al estado interno.
    """
    src: list[Any] = [{"uid": "X"}]
    fresh_state.set_devices("ed", src)
    src.append({"uid": "Y"})  # mutar la lista externa
    # El estado interno debe tener solo el elemento original.
    assert len(fresh_state.get_devices("ed")) == 1


def test_list_hw_types_only_includes_non_empty(
    fresh_state: AppState,
) -> None:
    """``list_hw_types`` solo retorna los hw_types con al menos 1 device."""
    fresh_state.set_devices("ed", [{"uid": "1"}])
    fresh_state.set_devices("v", [{"uid": "1"}])
    fresh_state.set_devices("m_sina", [])  # vacío: no debe aparecer
    assert sorted(fresh_state.list_hw_types()) == ["ed", "v"]


def test_all_devices_flattens_all_hw_types(
    fresh_state: AppState,
) -> None:
    """``all_devices`` devuelve una lista heterogénea con todos los devices."""
    fresh_state.set_devices("ed", [{"uid": "E1"}, {"uid": "E2"}])
    fresh_state.set_devices("v", [{"uid": "V1"}])
    all_d = fresh_state.all_devices()
    assert len(all_d) == 3
    uids = sorted(d["uid"] for d in all_d)
    assert uids == ["E1", "E2", "V1"]


def test_reset_clears_all_hw_types(fresh_state: AppState) -> None:
    """``reset`` vacía todas las listas."""
    fresh_state.set_devices("ed", [{"uid": "1"}])
    fresh_state.set_devices("v", [{"uid": "2"}])
    fresh_state.reset()
    assert fresh_state.get_devices("ed") == []
    assert fresh_state.get_devices("v") == []
    assert fresh_state.list_hw_types() == []


def test_iter_yields_hw_to_devices_pairs(fresh_state: AppState) -> None:
    """``for hw, devices in state: ...`` itera sobre el dict interno."""
    fresh_state.set_devices("ed", [{"uid": "1"}])
    fresh_state.set_devices("v", [{"uid": "2"}])
    pairs = dict(iter(fresh_state))
    assert pairs == {"ed": [{"uid": "1"}], "v": [{"uid": "2"}]}


def test_contains_checks_hw_type_membership(
    fresh_state: AppState,
) -> None:
    """``hw_type in state`` refleja si la clave está en el dict interno."""
    assert "ed" not in fresh_state
    fresh_state.set_devices("ed", [])
    assert "ed" in fresh_state  # existe aunque esté vacía
    assert "v" not in fresh_state


# ────────────────────────────────────────────────────────────────────────
# dimensiones (back-compat — placeholder)
# ────────────────────────────────────────────────────────────────────────


def test_dimensiones_present_by_default(fresh_state: AppState) -> None:
    """``dimensiones`` existe como placeholder (atributo back-compat).

    Tras PR 2, ``dimensiones`` ya no es un ``DimensionesDispositivos``
    instanciado por defecto: el ``AppState`` genérico no sabe de
    áreas, y el modelo vive en ``areas.alimentacion.domain.models``.
    El atributo se mantiene como ``Any = None`` para no romper la SPA
    (``DefinicionProgramacion.js`` lee ``store.memoryState.dimensiones``),
    los routers (``excel.py`` setea, ``diagnostics.py`` lee) y los
    tests que aún construyen ``DimensionesDispositivos(...)`` y lo
    asignan manualmente. La tipificación se resolverá en un refactor
    futuro (TODO(PR2.5)).
    """
    assert hasattr(fresh_state, "dimensiones")
    assert fresh_state.dimensiones is None


# ────────────────────────────────────────────────────────────────────────
# Singleton
# ────────────────────────────────────────────────────────────────────────


def test_get_app_state_returns_singleton_instance() -> None:
    """``get_app_state()`` retorna la misma instancia en llamadas sucesivas."""
    a = get_app_state()
    b = get_app_state()
    assert a is b


def test_get_app_state_is_app_state_instance() -> None:
    """El Singleton es una instancia de ``AppState``."""
    assert isinstance(get_app_state(), AppState)


# ────────────────────────────────────────────────────────────────────────
# Repr (no rompe con estado vacío ni con devices)
# ────────────────────────────────────────────────────────────────────────


def test_repr_works_empty_and_populated(fresh_state: AppState) -> None:
    """``__repr__`` no lanza con estado vacío ni con devices."""
    r1 = repr(fresh_state)
    assert "AppState(" in r1

    fresh_state.set_devices("ed", [{"uid": "1"}, {"uid": "2"}])
    fresh_state.set_devices("v", [])
    r2 = repr(fresh_state)
    # Solo aparecen las claves no vacías en el conteo.
    assert "'ed': 2" in r2  # ed tiene 2 devices
    # v está vacía: NO aparece como clave en el dict del repr.
    assert "'v':" not in r2


# ────────────────────────────────────────────────────────────────────────
# Parche de transición (PR 1): las 6 properties legacy siguen
# funcionando para no romper la SPA ni los tests que las usan.
# ────────────────────────────────────────────────────────────────────────


def test_legacy_property_dispositivos_ed_serves_from_state(
    fresh_state: AppState,
) -> None:
    """``state.dispositivos_ed`` lee de ``_dispositivos['ed']`` (parche PR 1).

    Este comportamiento desaparecerá en PR 2, cuando las properties
    pasen a aportarse vía ``AreaSpec.contributes_state_extensions``.
    """
    fresh_state.set_devices("ed", [{"uid": "ED_001"}])
    assert fresh_state.dispositivos_ed == [{"uid": "ED_001"}]


def test_legacy_setter_dispositivos_ea_syncs_to_dict(
    fresh_state: AppState,
) -> None:
    """``state.dispositivos_ea = [...]`` actualiza ``_dispositivos['ea']``."""
    fresh_state.dispositivos_ea = [{"uid": "EA_001"}]
    assert fresh_state.get_devices("ea") == [{"uid": "EA_001"}]
    assert fresh_state.dispositivos_ea == [{"uid": "EA_001"}]


def test_legacy_property_returns_empty_for_unset_hw(
    fresh_state: AppState,
) -> None:
    """Las 6 properties legacy retornan ``[]`` si aún no se asignaron."""
    assert fresh_state.dispositivos_ed == []
    assert fresh_state.dispositivos_ea == []
    assert fresh_state.dispositivos_sa == []
    assert fresh_state.dispositivos_v == []
    assert fresh_state.dispositivos_m == []
    assert fresh_state.dispositivos_m_vf == []
