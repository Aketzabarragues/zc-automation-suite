"""Tests del FB ``FunctionScanPlcBlocks``.

Fase 2, paso 2.1.3b.  Cubren:
  - Happy path: 3 ticks → nStep=99, gateway llamado, cache local
    populada, progress stages emitidos, lookup methods funcionan.
  - Sad path: el gateway lanza ``RuntimeError`` → nStep=98,
    ``error_stage`` invocado, ``error_msg`` poblado.
  - Cache fresh short-circuit: 2 ticks (10→20→done) sin llamar al
    gateway porque la cache local está fresca.
  - ``force_refresh=True`` ignora cache fresh y llama al gateway.
  - Terminal: ticks extra sobre ``n_done`` son no-op.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.functions.function_ScanPlcBlocks import FunctionScanPlcBlocks
from core.application.progress_buffer import ProgressTracker
from core.infrastructure.gateway import TIAProcessGateway
from core.models import BloqueCache, BloquePLC


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_gateway() -> MagicMock:
    """Gateway mock con ``scan_plc_blocks`` async."""
    g = MagicMock(spec=TIAProcessGateway)
    g.scan_plc_blocks = AsyncMock()
    return g


@pytest.fixture
def fake_block() -> MagicMock:
    """BloquePLC ficticio con ruta fija."""
    b = MagicMock(spec=BloquePLC)
    b.ruta = "DBs/DB100"
    # ``BloquePLC.normalize_name`` es classmethod real; el mock
    # necesita que la llamada funcione vía ``self.normalize_name``.
    b.normalize_name = lambda nombre: nombre.strip().lower()
    return b


@pytest.fixture
def fake_cache(fake_block: MagicMock) -> MagicMock:
    """BloqueCache con 2 bloques y 1 tag table."""
    cache = MagicMock(spec=BloqueCache)
    cache.blocks = {
        "db100": fake_block,
        "db200": MagicMock(spec=BloquePLC, ruta="DBs/DB200"),
    }
    cache.tag_tables = {
        "tags1": MagicMock(spec=BloquePLC, ruta="Tags/tags1"),
    }
    cache.scanned_at = datetime.now(timezone.utc)  # recién escaneado
    return cache


@pytest.fixture
def fresh_cache(fake_cache: MagicMock) -> MagicMock:
    """Cache con scanned_at = ahora (fresco, TTL = 5 min)."""
    return fake_cache


@pytest.fixture
def stale_cache(fake_cache: MagicMock) -> MagicMock:
    """Cache con scanned_at hace 10 min (caducado)."""
    fake_cache.scanned_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    return fake_cache


@pytest.fixture
def real_progress() -> ProgressTracker:
    return ProgressTracker()


@pytest.fixture
def progress(real_progress: ProgressTracker) -> ProgressTracker:
    """Tracker con ``begin()`` ya invocado (mismo contrato que
    ``FunctionSubirExcel``: el caller hace ``begin()`` antes).
    """
    real_progress.begin(
        operation="scan_plc_blocks_test",
        label="Scan PLC (test)",
        stages=["scan_blocks"],
    )
    return real_progress


def make_fb(
    gateway: MagicMock,
    progress: ProgressTracker,
) -> FunctionScanPlcBlocks:
    return FunctionScanPlcBlocks(
        nombre="scan_plc_blocks_test",
        gateway=gateway,
        progress_tracker=progress,
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_plc_blocks_happy_path_3_ticks(
    mock_gateway: MagicMock,
    progress: ProgressTracker,
    fake_cache: MagicMock,
) -> None:
    """Happy path: 3 ticks → nStep=99, gateway llamado, cache
    populada, lookup methods funcionales."""
    mock_gateway.scan_plc_blocks.return_value = fake_cache
    fb = make_fb(mock_gateway, progress)

    ok = await fb.start(plc_name="S7-1500")
    assert ok is True
    assert fb.nStep == 10

    # Tick #1: pre-flight (10 → 20)
    await fb.tick()
    assert fb.nStep == 20

    # Tick #2: check cache vacío/fresco? Sí, vacío → 30
    await fb.tick()
    assert fb.nStep == 30

    # Tick #3: scan via gateway (30 → 99)
    await fb.tick()
    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True
    assert fb.error_msg is None

    # Gateway llamado con los params correctos
    mock_gateway.scan_plc_blocks.assert_awaited_once_with(
        "S7-1500", force_refresh=False
    )

    # Cache local populada
    assert fb._local_cache["S7-1500"] is fake_cache
    assert "S7-1500" in fb._local_cache

    # Lookup methods funcionan post-scan
    block_db100 = fb.get_block("S7-1500", "DB100")
    assert block_db100 is fake_cache.blocks["db100"]
    assert fb.get_block_path("S7-1500", "DB100") == "DBs/DB100"
    assert fb.bloque_existe("S7-1500", "DB100") is True
    assert fb.bloque_existe("S7-1500", "INEXISTENTE") is False
    assert len(fb.list_blocks("S7-1500")) == 2
    assert len(fb.list_tag_tables("S7-1500")) == 1


@pytest.mark.asyncio
async def test_scan_plc_blocks_sad_gateway_raises(
    mock_gateway: MagicMock,
    progress: ProgressTracker,
) -> None:
    """El gateway lanza ``RuntimeError`` → nStep=98, error_stage
    invocado, error_msg poblado."""
    mock_gateway.scan_plc_blocks.side_effect = RuntimeError(
        "TIA Portal no responde"
    )
    fb = make_fb(mock_gateway, progress)

    await fb.start(plc_name="S7-1500")
    await fb.tick()  # 10 → 20
    await fb.tick()  # 20 → 30 (cache vacía)
    await fb.tick()  # 30 → 98 (scan falla)

    assert fb.nStep == fb.n_error
    assert fb.is_terminal() is True
    assert fb.error_msg is not None
    assert "TIA Portal no responde" in fb.error_msg

    # Cache NO se populó
    assert "S7-1500" not in fb._local_cache


@pytest.mark.asyncio
async def test_scan_plc_blocks_cache_fresh_short_circuit(
    mock_gateway: MagicMock,
    progress: ProgressTracker,
    fresh_cache: MagicMock,
) -> None:
    """Cache local fresca + force_refresh=False → 2 ticks (10→20→done),
    gateway NO se llama."""
    fb = make_fb(mock_gateway, progress)

    # Pre-poblar cache
    fb._local_cache["S7-1500"] = fresh_cache

    await fb.start(plc_name="S7-1500")
    await fb.tick()  # 10 → 20
    await fb.tick()  # 20 → 99 (cache fresca, short-circuit)

    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True

    # Gateway NO se llamó
    mock_gateway.scan_plc_blocks.assert_not_called()

    # Cache es la misma referencia
    assert fb._local_cache["S7-1500"] is fresh_cache
    # Lookup methods funcionan con la cache pre-poblada
    assert fb.get_block("S7-1500", "DB100") is fresh_cache.blocks["db100"]


@pytest.mark.asyncio
async def test_scan_plc_blocks_force_refresh_bypasses_cache(
    mock_gateway: MagicMock,
    progress: ProgressTracker,
    fresh_cache: MagicMock,
    fake_cache: MagicMock,
) -> None:
    """``force_refresh=True`` ignora cache fresca y llama al gateway."""
    mock_gateway.scan_plc_blocks.return_value = fake_cache
    fb = make_fb(mock_gateway, progress)

    # Pre-poblar cache con una versión distinta
    fb._local_cache["S7-1500"] = fresh_cache

    await fb.start(plc_name="S7-1500", force_refresh=True)
    await fb.tick()  # 10 → 20
    await fb.tick()  # 20 → 30 (fuerza refresh, salta short-circuit)
    await fb.tick()  # 30 → 99

    assert fb.nStep == fb.n_done
    # Gateway llamado CON force_refresh=True
    mock_gateway.scan_plc_blocks.assert_awaited_once_with(
        "S7-1500", force_refresh=True
    )
    # Cache reemplazada por la nueva
    assert fb._local_cache["S7-1500"] is fake_cache


@pytest.mark.asyncio
async def test_scan_plc_blocks_terminal_no_avanza_mas(
    mock_gateway: MagicMock, progress: ProgressTracker
) -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op (guarda de la base)."""
    fb = make_fb(mock_gateway, progress)
    await fb.start(plc_name="S7-1500")

    # Forzar n_done (sin esperar 3 ticks)
    fb.nStep = fb.n_done
    n_step_before = fb.nStep

    await fb.tick()
    assert fb.nStep == n_step_before  # no avanza
    # Gateway NO se llamó (no llegamos a nStep=30)
    mock_gateway.scan_plc_blocks.assert_not_called()
