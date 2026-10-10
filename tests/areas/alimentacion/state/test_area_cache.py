"""Tests del ``AlimentacionAreaCache``.

Cubre:
  - defaults: campos en ``None`` al instanciar vacio.
  - ``reset()`` retorna una nueva instancia con todos los campos en
    default.
  - frozen dataclass: ``__setattr__`` falla.
  - cumple ``AreaCacheProtocol`` (runtime_checkable).
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from areas.alimentacion.state.area_cache import AlimentacionAreaCache
from core.runtime.app_cache import AreaCacheProtocol


def test_defaults_vacios() -> None:
    """Sin constructor: todos los campos en ``None``."""
    area = AlimentacionAreaCache()
    assert area.excel_full is None
    assert area.excel_active is None
    assert area.preview_disp is None
    assert area.preview_proc is None
    assert area.last_sync_disp_at is None
    assert area.last_sync_proc_at is None
    assert area.last_disp_commit_summary is None
    assert area.last_proc_commit_summary is None


def test_reset_retorna_instancia_con_defaults() -> None:
    """``reset()`` produce una nueva instancia con todos los campos en ``None``."""
    area = AlimentacionAreaCache(
        excel_full="dummy",  # type: ignore[arg-type]
        excel_active="dummy",  # type: ignore[arg-type]
        preview_disp={"x": 1},
        preview_proc={"y": 2},
        last_sync_disp_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        last_sync_proc_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        last_disp_commit_summary={"a": 1},
        last_proc_commit_summary={"b": 2},
    )
    # Sanity check: los campos se setearon (no frozen en atributos).
    assert area.excel_full == "dummy"

    nuevo = area.reset()

    assert isinstance(nuevo, AlimentacionAreaCache)
    assert nuevo.excel_full is None
    assert nuevo.excel_active is None
    assert nuevo.preview_disp is None
    assert nuevo.preview_proc is None
    assert nuevo.last_sync_disp_at is None
    assert nuevo.last_sync_proc_at is None
    assert nuevo.last_disp_commit_summary is None
    assert nuevo.last_proc_commit_summary is None


def test_frozen_no_mutation_in_place() -> None:
    """Los campos no se pueden mutar; ``dataclasses.replace`` es el camino."""
    area = AlimentacionAreaCache()
    with pytest.raises(dataclasses.FrozenInstanceError):
        area.excel_full = "x"  # type: ignore[misc]


def test_replace_para_mutar() -> None:
    """``dataclasses.replace`` produce una nueva instancia con campos actualizados."""
    nuevo = AlimentacionAreaCache()
    filled = dataclasses.replace(nuevo, excel_full="cache")
    assert filled.excel_full == "cache"
    assert nuevo.excel_full is None  # el original intacto


def test_cumple_area_cache_protocol() -> None:
    """La instancia runtime es ``isinstance`` de ``AreaCacheProtocol``."""
    area = AlimentacionAreaCache()
    assert isinstance(area, AreaCacheProtocol)


def test_reset_sobre_instancia_vacia_devuelve_instancia_vacia() -> None:
    """``reset()`` sobre instancia vacia devuelve otra instancia vacia."""
    nuevo = AlimentacionAreaCache().reset()
    assert isinstance(nuevo, AlimentacionAreaCache)
    assert nuevo == AlimentacionAreaCache()
