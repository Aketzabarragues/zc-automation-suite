"""Tests de los helpers ``core.helpers.tia.active_cache``.

Cubre los 4 helpers publicos:
  - ``get_devices(state, hw)``
  - ``get_nmax(state)``
  - ``get_nmax_entidades(state)``  ← C.9
  - ``get_entidades(state, plc_name)``
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.helpers.tia.active_cache import (
    get_devices,
    get_entidades,
    get_nmax,
    get_nmax_entidades,
)


def _make_dim(plc_name: str, extras: dict[str, int], n_max_entidades: int = 0):
    """Mock ``DataDimensionesPLC`` con campos minimos."""
    return SimpleNamespace(
        plc_name=plc_name,
        extras=dict(extras),
        n_max_entidades=n_max_entidades,
    )


def _make_state(
    *,
    cache: object | None = None,
    dispositivos: dict[str, tuple] | None = None,
    entidades: tuple = (),
) -> MagicMock:
    """Mock ``AppState`` con ``excel_cache_active`` y sub-campos.

    Comportamiento:
      - ``cache=None`` + sin campos custom: cache activo ``None``
        (los helpers que dependen el cache deben raise RuntimeError).
      - ``cache=None`` + campos custom: auto-crea un ``SimpleNamespace``
        con esos campos (uso normal).
      - ``cache=<objeto>`` + campos custom: setea los campos en ese
        objeto.
    """
    state = MagicMock()
    if cache is None and (dispositivos is not None or entidades):
        cache = SimpleNamespace()
    state.excel_cache_active = cache
    if cache is not None:
        cache.dispositivos = dispositivos or {}
        cache.entidades = entidades
    return state


# ============================================================================
# get_devices
# ============================================================================

def test_get_devices_happy_path():
    """Happy path: 1 hw con 3 devices."""
    devs = (object(), object(), object())
    state = _make_state(dispositivos={"ed": devs})
    assert get_devices(state, "ed") == list(devs)


def test_get_devices_hw_inexistente_devuelve_vacio():
    """Si el hw no esta en el cache, devuelve lista vacia."""
    state = _make_state(dispositivos={"ed": (object(),)})
    assert get_devices(state, "ea") == []


def test_get_devices_cache_none_raise():
    """Sin cache activo, RuntimeError accionable."""
    state = _make_state(cache=None)
    with pytest.raises(RuntimeError, match="Cargue primero el Excel"):
        get_devices(state, "ed")


# ============================================================================
# get_nmax
# ============================================================================

def test_get_nmax_un_plc_devuelve_extras():
    """1 PLC en cache: devuelve extras tal cual."""
    dim = _make_dim("PLC1", {"N_MAX_DISP_ED": 11, "N_MAX_DISP_EA": 7})
    cache = SimpleNamespace(n_max=SimpleNamespace(por_plc=(dim,)))
    state = _make_state(cache=cache)

    assert get_nmax(state) == {"N_MAX_DISP_ED": 11, "N_MAX_DISP_EA": 7}


def test_get_nmax_multi_plc_une_poblacion():
    """Multi-PLC: union por nombre de columna (primero gana)."""
    dim1 = _make_dim("PLC1", {"N_MAX_DISP_ED": 11, "N_MAX_DISP_EA": 7})
    dim2 = _make_dim("PLC2", {"N_MAX_DISP_ED": 99, "N_MAX_DISP_EA": 88})
    cache = SimpleNamespace(n_max=SimpleNamespace(por_plc=(dim1, dim2)))
    state = _make_state(cache=cache)

    # Primero gana en caso de colision.
    assert get_nmax(state) == {"N_MAX_DISP_ED": 11, "N_MAX_DISP_EA": 7}


def test_get_nmax_sin_nmax_field_raise():
    """Si ``cache.n_max`` es None, RuntimeError."""
    cache = SimpleNamespace(n_max=None)
    state = _make_state(cache=cache)

    with pytest.raises(RuntimeError, match="Excel sin Tabla_Dispositivos"):
        get_nmax(state)


# ============================================================================
# get_nmax_entidades  (C.9)
# ============================================================================

def test_get_nmax_entidades_un_plc_devuelve_entidades():
    """1 PLC en cache: devuelve el campo ``n_max_entidades``."""
    dim = _make_dim("PLC1", {"N_MAX_DISP_ED": 11}, n_max_entidades=10)
    cache = SimpleNamespace(n_max=SimpleNamespace(por_plc=(dim,)))
    state = _make_state(cache=cache)

    assert get_nmax_entidades(state) == {"N_MAX_ENTIDAD": 10}


def test_get_nmax_entidades_multi_plc_toma_primero():
    """Multi-PLC: igual que ``get_nmax``, toma el primero."""
    dim1 = _make_dim("PLC1", extras={}, n_max_entidades=10)
    dim2 = _make_dim("PLC2", extras={}, n_max_entidades=20)
    cache = SimpleNamespace(n_max=SimpleNamespace(por_plc=(dim1, dim2)))
    state = _make_state(cache=cache)

    assert get_nmax_entidades(state) == {"N_MAX_ENTIDAD": 10}


def test_get_nmax_entidades_por_plc_vacio_devuelve_vacio():
    """por_plc vacio (PLC sin fila en Tabla_Dimensiones): ``{}``.

    El FB de entidades debe manejar este caso devolviendo un diff
    vacio contra Excel (missing_nmax_error); el sync solo contra TIA.
    """
    cache = SimpleNamespace(n_max=SimpleNamespace(por_plc=()))
    state = _make_state(cache=cache)

    assert get_nmax_entidades(state) == {}


def test_get_nmax_entidades_cache_sin_nmax_devuelve_vacio():
    """Si ``cache.n_max`` es None (Excel sin Tabla_Dimensiones), ``{}``.

    ``get_nmax_entidades`` NO raise en este caso (a diferencia de
    ``get_nmax``): el campo es opcional y solo lo usa el feature
    entidades. Si no existe, el FB tiene su propio manejo de
    ``missing_nmax_error``.
    """
    cache = SimpleNamespace(n_max=None)
    state = _make_state(cache=cache)

    assert get_nmax_entidades(state) == {}


def test_get_nmax_entidades_cache_none_raise():
    """Sin cache activo, RuntimeError accionable (mismo contrato que
    el resto de helpers)."""
    state = _make_state(cache=None)
    with pytest.raises(RuntimeError, match="Cargue primero el Excel"):
        get_nmax_entidades(state)


# ============================================================================
# get_entidades
# ============================================================================

def test_get_entidades_filtra_por_plc_name():
    """Solo devuelve las del PLC indicado."""
    e1 = SimpleNamespace(plc_name="PLC1")
    e2 = SimpleNamespace(plc_name="PLC2")
    e3 = SimpleNamespace(plc_name="PLC1")
    state = _make_state(entidades=(e1, e2, e3))

    assert get_entidades(state, "PLC1") == [e1, e3]
    assert get_entidades(state, "PLC2") == [e2]
    assert get_entidades(state, "PLC_NOPE") == []


def test_get_entidades_cache_none_raise():
    """Sin cache activo, RuntimeError accionable."""
    state = _make_state(cache=None)
    with pytest.raises(RuntimeError, match="Cargue primero el Excel"):
        get_entidades(state, "PLC1")