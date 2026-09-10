"""Tests del ``ExcelCacheManager`` (singleton IT del cache del Excel).

Cubre la API pública:
  * ``get`` / ``put`` / ``clear``.
  * ``needs_reload`` (lectura atómica, no async).
  * ``on_excel_reload``.
  * ``wait_for_first_load`` con ``asyncio.Event``.

Sigue el mismo patrón de ``test_bloque_cache_manager.py``: estado
de clase ``ClassVar`` con un fixture ``autouse`` que limpia antes
y después de cada test (para no contaminar la suite).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from areas.alimentacion.domain.models.excel_cache import (
    DimensionesDispositivos,
    ExcelCache,
)
from areas.alimentacion.infrastructure.cache import ExcelCacheManager


def _make_cache(path: str = "/tmp/a.xlsx", mtime_ns: int = 1) -> ExcelCache:
    """Helper: cache mínimo con todos los campos requeridos."""
    return ExcelCache(
        excel_path=path,
        excel_mtime_ns=mtime_ns,
        parsed_at=datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
        dispositivos={
            "ed": (), "ea": (), "sa": (),
            "v": (),  "m": (),  "m_vf": (),
        },
        n_max=DimensionesDispositivos(),
        procesos=(), parametros_real=(), parametros_int=(), alarmas=(),
        procesos_by_codigo={}, parametros_real_by_codigo={},
        parametros_int_by_codigo={},
    )


# ── Fixture autouse ────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _clean_state() -> None:
    # Re-bind el ``_first_load_event`` al event loop del test para
    # evitar el error ``RuntimeError: Event is bound to a different
    # event loop`` cuando pytest-asyncio crea un loop por test.
    ExcelCacheManager._cache = None
    ExcelCacheManager._first_load_event = asyncio.Event()
    yield
    ExcelCacheManager._cache = None
    ExcelCacheManager._first_load_event = asyncio.Event()


# ── get / put ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_vacio_devuelve_none() -> None:
    """Sin estado previo → ``get`` devuelve ``None``."""
    assert await ExcelCacheManager.get() is None


@pytest.mark.asyncio
async def test_put_then_get() -> None:
    """Tras ``put``, ``get`` devuelve el mismo objeto cache."""
    cache = _make_cache()
    await ExcelCacheManager.put(cache)
    fetched = await ExcelCacheManager.get()
    assert fetched is cache
    assert fetched.excel_path == "/tmp/a.xlsx"


# ── clear ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clear_vacia_cache() -> None:
    """``clear`` deja el cache en ``None``."""
    await ExcelCacheManager.put(_make_cache())
    await ExcelCacheManager.clear()
    assert await ExcelCacheManager.get() is None


# ── needs_reload ──────────────────────────────────────────────────────


def test_needs_reload_con_cache_vacio() -> None:
    """Cache vacío → siempre ``needs_reload == True`` (no async)."""
    assert ExcelCacheManager.needs_reload("/tmp/a.xlsx", 1) is True


def test_needs_reload_con_path_distinto() -> None:
    """Cache cargado con path A, query con path B → ``True``."""
    # Seteamos manualmente (sin async) el ``_cache``.
    ExcelCacheManager._cache = _make_cache(path="/tmp/A.xlsx", mtime_ns=1)
    try:
        assert ExcelCacheManager.needs_reload("/tmp/B.xlsx", 1) is True
    finally:
        ExcelCacheManager._cache = None


def test_needs_reload_con_mtime_distinto() -> None:
    """Cache cargado con mtime 1, query con mtime 2 → ``True``."""
    ExcelCacheManager._cache = _make_cache(path="/tmp/A.xlsx", mtime_ns=1)
    try:
        assert ExcelCacheManager.needs_reload("/tmp/A.xlsx", 2) is True
    finally:
        ExcelCacheManager._cache = None


def test_needs_reload_con_mismo_path_y_mtime_devuelve_false() -> None:
    """Misma tupla (path, mtime) → ``False``."""
    ExcelCacheManager._cache = _make_cache(path="/tmp/A.xlsx", mtime_ns=1)
    try:
        assert ExcelCacheManager.needs_reload("/tmp/A.xlsx", 1) is False
    finally:
        ExcelCacheManager._cache = None


# ── on_excel_reload ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_excel_reload_invalida_si_distinto() -> None:
    """``on_excel_reload`` con tupla distinta invalida el cache."""
    await ExcelCacheManager.put(_make_cache(path="/tmp/old.xlsx", mtime_ns=1))
    await ExcelCacheManager.on_excel_reload("/tmp/new.xlsx", 2)
    assert await ExcelCacheManager.get() is None


@pytest.mark.asyncio
async def test_on_excel_reload_no_hace_nada_si_igual() -> None:
    """``on_excel_reload`` con misma tupla es no-op."""
    cache = _make_cache(path="/tmp/A.xlsx", mtime_ns=1)
    await ExcelCacheManager.put(cache)
    await ExcelCacheManager.on_excel_reload("/tmp/A.xlsx", 1)
    assert await ExcelCacheManager.get() is cache


# ── wait_for_first_load ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wait_for_first_load_resuelve_despues_de_put() -> None:
    """Una coroutine esperando recibe el cache tras ``put``."""
    # Limpia el event para que el wait bloquee.
    ExcelCacheManager._first_load_event.clear()
    ExcelCacheManager._cache = None

    async def waiter() -> None:
        result = await ExcelCacheManager.wait_for_first_load(timeout=2.0)
        assert result is not None
        assert result.excel_path == "/tmp/wait.xlsx"

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)  # deja que el waiter se bloquee
    await ExcelCacheManager.put(_make_cache(path="/tmp/wait.xlsx", mtime_ns=1))
    await task  # noqa


@pytest.mark.asyncio
async def test_wait_for_first_load_timeout_devuelve_none() -> None:
    """Si el timeout expira antes del ``put``, devuelve ``None``."""
    # Estado limpio: cache vacío, event no seteado.
    ExcelCacheManager._first_load_event.clear()
    ExcelCacheManager._cache = None

    result = await ExcelCacheManager.wait_for_first_load(timeout=0.1)
    assert result is None
