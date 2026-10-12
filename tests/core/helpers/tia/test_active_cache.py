"""Tests de los helpers ``core.helpers.tia.active_cache``.

Cubre los 4 helpers publicos:
  - ``get_devices(app_cache, hw, area_id)``
  - ``get_nmax(app_cache, area_id)``
  - ``get_nmax_entidades(app_cache, area_id)``
  - ``get_entidades(app_cache, plc_name, area_id)``

Los helpers leen via ``excel_get_active`` sobre el ``area_id`` que el
caller pasa, partiendo del ``AppCache`` recibido.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType, SimpleNamespace

import pytest

from core.data.data_excel_cache import DataExcelCache
from core.helpers.tia.active_cache import (
    get_devices,
    get_entidades,
    get_nmax,
    get_nmax_entidades,
)
from core.runtime.app_cache import AppCache
from core.runtime.excel_cache import excel_set_active


@pytest.fixture(autouse=True)
def _reset_app_singletons():
    """Reset del Singleton ``AppCache`` entre tests.

    Sin reset, el ``register_area("alimentacion", ...)`` de un test
    contamina al siguiente con
    ``ValueError: area 'alimentacion' ya registrada``.
    """
    import core.runtime.app_cache as _cache_mod
    _cache_mod._app_cache = None
    yield
    _cache_mod._app_cache = None


def _make_dim(plc_name: str, extras: dict[str, int], n_max_entidades: int = 0):
    """Stub ``DataDimensionesPLC`` con campos minimos."""
    return SimpleNamespace(
        plc_name=plc_name,
        extras=dict(extras),
        n_max_entidades=n_max_entidades,
    )


def _make_active(
    *,
    dispositivos: dict[str, tuple] | None = None,
    entidades: tuple = (),
    por_plc: tuple = (),
    n_max_override: object | None = None,
) -> DataExcelCache:
    """Stub ``DataExcelCache`` para tests."""
    dim = SimpleNamespace(por_plc=por_plc) if n_max_override is None else n_max_override
    return DataExcelCache(
        excel_path="/x.xlsx",
        excel_mtime_ns=1,
        parsed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        dispositivos=dispositivos or {},
        n_max=dim,
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        entidades=entidades,
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )


def _make_app_cache(active: DataExcelCache | None) -> AppCache:
    """Construye un ``AppCache`` con cache activo inyectado."""
    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    cache = AppCache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    if active is not None:
        excel_set_active(cache, "alimentacion", active)
    return cache


# ============================================================================
# get_devices
# ============================================================================


def test_get_devices_happy_path():
    """Happy path: 1 hw con 3 devices."""
    devs = (object(), object(), object())
    cache = _make_app_cache(_make_active(dispositivos={"ed": devs}))
    assert get_devices(cache, "ed", "alimentacion") == list(devs)


def test_get_devices_hw_inexistente_devuelve_vacio():
    """Si el hw no esta en el cache, devuelve lista vacia."""
    cache = _make_app_cache(_make_active(dispositivos={"ed": (object(),)}))
    assert get_devices(cache, "ea", "alimentacion") == []


def test_get_devices_cache_none_raise():
    """Sin cache activo, RuntimeError accionable."""
    cache = _make_app_cache(None)
    with pytest.raises(RuntimeError, match="Cargue primero el Excel"):
        get_devices(cache, "ed", "alimentacion")


# ============================================================================
# get_nmax
# ============================================================================


def test_get_nmax_un_plc_devuelve_extras():
    """1 PLC en cache: devuelve extras tal cual."""
    dim = _make_dim("PLC1", {"N_MAX_DISP_ED": 11, "N_MAX_DISP_EA": 7})
    cache = _make_app_cache(_make_active(por_plc=(dim,)))

    assert get_nmax(cache, "alimentacion") == {"N_MAX_DISP_ED": 11, "N_MAX_DISP_EA": 7}


def test_get_nmax_multi_plc_une_poblacion():
    """Multi-PLC: union por nombre de columna (primero gana)."""
    dim1 = _make_dim("PLC1", {"N_MAX_DISP_ED": 11, "N_MAX_DISP_EA": 7})
    dim2 = _make_dim("PLC2", {"N_MAX_DISP_ED": 99, "N_MAX_DISP_EA": 88})
    cache = _make_app_cache(_make_active(por_plc=(dim1, dim2)))

    # Primero gana en caso de colision.
    assert get_nmax(cache, "alimentacion") == {"N_MAX_DISP_ED": 11, "N_MAX_DISP_EA": 7}


def test_get_nmax_sin_nmax_field_raise():
    """Si ``cache.n_max`` es None, RuntimeError."""
    import dataclasses as _dc
    active = _dc.replace(_make_active(), n_max=None)
    cache = _make_app_cache(active)

    with pytest.raises(RuntimeError, match="Excel sin Tabla_Dispositivos"):
        get_nmax(cache, "alimentacion")


# ============================================================================
# get_nmax_entidades
# ============================================================================


def test_get_nmax_entidades_un_plc_devuelve_entidades():
    """1 PLC en cache: devuelve el campo ``n_max_entidades``."""
    dim = _make_dim("PLC1", {"N_MAX_DISP_ED": 11}, n_max_entidades=10)
    cache = _make_app_cache(_make_active(por_plc=(dim,)))

    assert get_nmax_entidades(cache, "alimentacion") == {"N_MAX_ENTIDAD": 10}


def test_get_nmax_entidades_multi_plc_toma_primero():
    """Multi-PLC: igual que ``get_nmax``, toma el primero."""
    dim1 = _make_dim("PLC1", extras={}, n_max_entidades=10)
    dim2 = _make_dim("PLC2", extras={}, n_max_entidades=20)
    cache = _make_app_cache(_make_active(por_plc=(dim1, dim2)))

    assert get_nmax_entidades(cache, "alimentacion") == {"N_MAX_ENTIDAD": 10}


def test_get_nmax_entidades_por_plc_vacio_devuelve_vacio():
    """por_plc vacio (PLC sin fila en Tabla_Dimensiones): ``{}``."""
    cache = _make_app_cache(_make_active(por_plc=()))

    assert get_nmax_entidades(cache, "alimentacion") == {}


def test_get_nmax_entidades_cache_sin_nmax_devuelve_vacio():
    """Si ``cache.n_max`` es None (Excel sin Tabla_Dimensiones), ``{}``."""
    import dataclasses as _dc
    active = _dc.replace(_make_active(), n_max=None)
    cache = _make_app_cache(active)

    assert get_nmax_entidades(cache, "alimentacion") == {}


def test_get_nmax_entidades_cache_none_raise():
    """Sin cache activo, RuntimeError accionable."""
    cache = _make_app_cache(None)
    with pytest.raises(RuntimeError, match="Cargue primero el Excel"):
        get_nmax_entidades(cache, "alimentacion")


# ============================================================================
# get_entidades
# ============================================================================


def test_get_entidades_filtra_por_plc_name():
    """Solo devuelve las del PLC indicado."""
    e1 = SimpleNamespace(plc_name="PLC1")
    e2 = SimpleNamespace(plc_name="PLC2")
    e3 = SimpleNamespace(plc_name="PLC1")
    cache = _make_app_cache(_make_active(entidades=(e1, e2, e3)))

    assert get_entidades(cache, "PLC1", "alimentacion") == [e1, e3]
    assert get_entidades(cache, "PLC2", "alimentacion") == [e2]
    assert get_entidades(cache, "PLC_NOPE", "alimentacion") == []


def test_get_entidades_cache_none_raise():
    """Sin cache activo, RuntimeError accionable."""
    cache = _make_app_cache(None)
    with pytest.raises(RuntimeError, match="Cargue primero el Excel"):
        get_entidades(cache, "PLC1", "alimentacion")