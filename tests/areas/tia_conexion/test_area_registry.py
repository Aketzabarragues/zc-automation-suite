"""Tests unitarios del registry de areas (``core.application.area_registry``).

Cubre:
  - ``register()`` agrega un area nueva al registro.
  - ``register()`` con el mismo ``key`` SOBREESCRIBE (idempotencia).
  - ``get_areas()`` retorna una **copia defensiva** (mutar el
    retorno NO afecta al registro).
  - ``reset()`` vacia el registro (uso exclusivo de tests).

Marcados como ``area_smoke`` (ver ``pytest.ini``).

Note:
    Estos tests NO usan la app de FastAPI: ejercitan el registry
    directamente. El router de areas (``tests/areas/tia_conexion/
    test_router_areas.py``) es el que valida el contrato HTTP.

Aislamiento entre tests:
    El fixture ``_clean_registry`` (``autouse=True``) resetea el
    registry antes y despues de cada test de este archivo. El
    teardown resetea para que el siguiente test empiece limpio.
    El conftest en ``tests/areas/tia_conexion/conftest.py`` se
    encarga de re-registrar el area ``tia_conexion`` antes de los
    tests del router (que la necesitan registrada).
"""
from __future__ import annotations

import dataclasses

import pytest

from core.application import area_registry as reg


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Limpia el registry antes y despues de cada test.

    Como el registry es un singleton en memoria (``_REGISTRY``), si
    no lo limpiamos los tests se contaminarian entre si. Marcado
    como ``autouse=True`` para que cada test empiece de cero.
    """
    reg.reset()
    yield  # type: ignore[misc]
    reg.reset()


@pytest.mark.area_smoke
def test_register_adds_new_area() -> None:
    """``register()`` agrega un area nueva al registro."""
    reg.register(reg.AreaSpec(key="x", label="X"))
    areas = reg.get_areas()
    assert len(areas) == 1
    assert areas[0].key == "x"
    assert areas[0].label == "X"


@pytest.mark.area_smoke
def test_register_same_key_overwrites() -> None:
    """``register()`` con el mismo ``key`` SOBREESCRIBE (idempotente)."""
    reg.register(reg.AreaSpec(key="x", label="X1"))
    reg.register(reg.AreaSpec(key="x", label="X2"))  # mismo key
    areas = reg.get_areas()
    assert len(areas) == 1
    assert areas[0].label == "X2"  # la segunda gana


@pytest.mark.area_smoke
def test_register_different_keys_appends() -> None:
    """``register()`` con keys distintos APPEND al final (orden de
    registro = orden de retorno).
    """
    reg.register(reg.AreaSpec(key="a", label="A"))
    reg.register(reg.AreaSpec(key="b", label="B"))
    reg.register(reg.AreaSpec(key="c", label="C"))
    keys = [a.key for a in reg.get_areas()]
    assert keys == ["a", "b", "c"]


@pytest.mark.area_smoke
def test_get_areas_returns_defensive_copy() -> None:
    """``get_areas()`` retorna una copia: mutar el retorno NO afecta
    al registro interno.
    """
    reg.register(reg.AreaSpec(key="x", label="X"))
    snapshot = reg.get_areas()
    snapshot.clear()  # mutamos el retorno
    # El registro interno sigue intacto.
    assert len(reg.get_areas()) == 1


@pytest.mark.area_smoke
def test_area_spec_is_frozen() -> None:
    """``AreaSpec`` es ``frozen=True``: no se puede mutar."""
    spec = reg.AreaSpec(key="x", label="X")
    # ``FrozenInstanceError`` viene de ``dataclasses``; lo importamos
    # para no usar un ``Exception`` generico (B017 / PT011).
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.label = "Y"  # type: ignore[misc]


@pytest.mark.area_smoke
def test_area_spec_defaults() -> None:
    """``AreaSpec`` con defaults: ``icon=""``, ``available=True``,
    ``description=""``.
    """
    spec = reg.AreaSpec(key="x", label="X")
    assert spec.icon == ""
    assert spec.available is True
    assert spec.description == ""


@pytest.mark.area_smoke
def test_reset_empties_registry() -> None:
    """``reset()`` vacia el registro (uso exclusivo de tests)."""
    reg.register(reg.AreaSpec(key="x", label="X"))
    reg.register(reg.AreaSpec(key="y", label="Y"))
    assert len(reg.get_areas()) == 2
    reg.reset()
    assert reg.get_areas() == []
