"""Tests del ``BloqueCacheManager`` (singleton IT de caches de bloques).

Validan el contrato de la API publica:
  - ``get`` / ``put`` / ``clear`` con aislamiento por PLC.
  - ``clear(None)`` borra todo; ``clear("X")`` solo ese PLC.
  - ``on_plc_change`` invalida el PLC viejo si difiere del nuevo.
  - Concurrencia: ``asyncio.Lock`` serializa ``put`` paralelos.
  - Logging: la invalidacion emite un ``INFO`` con el PLC afectado.

Como el manager tiene estado a nivel de CLASE (ClassVar), cada test
hace ``BloqueCacheManager.clear()`` en su ``finally`` para no contaminar
el resto de la suite. ``pytest-asyncio`` con ``mode=strict`` requiere
decorador explicito ``@pytest.mark.asyncio``.
"""
from __future__ import annotations

import asyncio
import logging

import pytest
import pytest_asyncio

from core.infrastructure.cache.bloque_cache_manager import BloqueCacheManager
from core.models import BloqueCache, BloquePLC


def _make_cache(plc: str) -> BloqueCache:
    """Helper: cache con 1 bloque + 1 tag table."""
    b = BloquePLC(nombre="DB1", numero=1, tipo="DB", ruta="")
    t = BloquePLC(nombre="Default_tag_table", numero=0, tipo="OTHER", ruta="")
    return BloqueCache(
        blocks={BloquePLC.normalize_name(b.nombre): b},
        tag_tables={BloquePLC.normalize_name(t.nombre): t},
        plc_name=plc,
    )


@pytest_asyncio.fixture(autouse=True)
async def _clean_state() -> None:
    """Limpia el estado de clase antes y después de cada test."""
    await BloqueCacheManager.clear()
    yield
    await BloqueCacheManager.clear()


# ────────────────────────────────────────────────────────────────────────
# get / put
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_none_when_empty() -> None:
    """Sin estado previo → ``get`` devuelve ``None``."""
    assert await BloqueCacheManager.get("PLC_X") is None


@pytest.mark.asyncio
async def test_put_then_get_returns_same_cache() -> None:
    """Tras ``put``, ``get`` devuelve el mismo objeto cache."""
    cache = _make_cache("PLC_A")
    await BloqueCacheManager.put("PLC_A", cache)
    fetched = await BloqueCacheManager.get("PLC_A")
    assert fetched is cache
    assert fetched.plc_name == "PLC_A"
    assert "db1" in fetched.blocks
    assert "default_tag_table" in fetched.tag_tables


# ────────────────────────────────────────────────────────────────────────
# clear
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clear_specific_plc_leaves_others() -> None:
    """``clear("PLC_A")`` solo borra PLC_A, deja PLC_B intacto."""
    await BloqueCacheManager.put("PLC_A", _make_cache("PLC_A"))
    await BloqueCacheManager.put("PLC_B", _make_cache("PLC_B"))
    await BloqueCacheManager.clear("PLC_A")
    assert await BloqueCacheManager.get("PLC_A") is None
    assert await BloqueCacheManager.get("PLC_B") is not None


@pytest.mark.asyncio
async def test_clear_none_removes_all() -> None:
    """``clear(None)`` vacia TODOS los PLCs cacheados."""
    await BloqueCacheManager.put("PLC_A", _make_cache("PLC_A"))
    await BloqueCacheManager.put("PLC_B", _make_cache("PLC_B"))
    await BloqueCacheManager.clear(None)
    assert await BloqueCacheManager.get("PLC_A") is None
    assert await BloqueCacheManager.get("PLC_B") is None


# ────────────────────────────────────────────────────────────────────────
# on_plc_change
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_plc_change_invalidates_old_only_when_different() -> None:
    """Si old != new, se borra old. new queda intacto."""
    await BloqueCacheManager.put("PLC_OLD", _make_cache("PLC_OLD"))
    await BloqueCacheManager.put("PLC_NEW", _make_cache("PLC_NEW"))
    await BloqueCacheManager.on_plc_change("PLC_OLD", "PLC_NEW")
    assert await BloqueCacheManager.get("PLC_OLD") is None
    assert await BloqueCacheManager.get("PLC_NEW") is not None


@pytest.mark.asyncio
async def test_on_plc_change_is_noop_when_same_plc() -> None:
    """Si old == new, no se invalida nada."""
    cache = _make_cache("PLC_X")
    await BloqueCacheManager.put("PLC_X", cache)
    await BloqueCacheManager.on_plc_change("PLC_X", "PLC_X")
    assert await BloqueCacheManager.get("PLC_X") is cache


# ────────────────────────────────────────────────────────────────────────
# Concurrencia
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_puts_are_thread_safe() -> None:
    """Dos ``put`` simultaneos: el estado final contiene ambos PLCs."""
    cache_a = _make_cache("PLC_A")
    cache_b = _make_cache("PLC_B")

    await asyncio.gather(
        BloqueCacheManager.put("PLC_A", cache_a),
        BloqueCacheManager.put("PLC_B", cache_b),
    )

    a = await BloqueCacheManager.get("PLC_A")
    b = await BloqueCacheManager.get("PLC_B")
    assert a is cache_a
    assert b is cache_b


# ────────────────────────────────────────────────────────────────────────
# Logging
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalidation_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """La invalidacion emite ``INFO`` con el nombre del PLC afectado."""
    await BloqueCacheManager.put("PLC_LOGS", _make_cache("PLC_LOGS"))

    with caplog.at_level(logging.INFO, logger="core.infrastructure.cache.bloque_cache_manager"):
        await BloqueCacheManager.clear("PLC_LOGS")

    # Filtramos solo los INFO de este logger.
    info_messages = [
        rec.message
        for rec in caplog.records
        if rec.levelno == logging.INFO
        and rec.name == "core.infrastructure.cache.bloque_cache_manager"
    ]
    assert any("PLC_LOGS" in msg for msg in info_messages), (
        f"Se esperaba un INFO mencionando 'PLC_LOGS', got: {info_messages!r}"
    )
