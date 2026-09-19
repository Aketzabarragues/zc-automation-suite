"""Tests del FB ``FunctionProcSincronizar``.

Cubre:
  - Happy path: 7 ticks (1 arrancar + 4 steps + 1 finalizar + 1 done),
    ``self.result`` con la shape legacy, helper llamado 1 vez por step.
  - Sad path 1: sin ``config_manager`` -> nStep=98 con "config_manager".
  - Sad path 2: sin ``tia_client`` -> nStep=98 con "tia_client".
  - Sad path 3: ``start()`` sin ``plc_name`` -> ValueError.
  - Sad path 4: ``start()`` sin ``proc_uid`` -> ValueError.
  - Sad path 5: helper ``proc_check_state_commit`` reporta excel no
    cargado -> primer tick ejecutivo falla con RuntimeError.
  - Sad path 6: helper ``proc_build_slot_maps_commit`` reporta
    missing_blocks -> tercer tick ejecutivo falla con RuntimeError.
  - Estado terminal: ticks extra sobre ``n_done`` son no-op.

Mockeamos el helper ``proc_sincronizar`` (sus funciones) para validar
SOLO la state machine del FB (no la logica del helper; eso tiene su
propio test en ``test_proc_sincronizar.py``).
"""
from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from areas.alimentacion.functions.function_ProcSincronizar import (
    FunctionProcSincronizar,
)
from areas.alimentacion.helpers.proc import proc_sincronizar as helper_mod
from core.runtime.app_state import AppState
from core.runtime.progress_buffer import ProgressTracker
from core.infrastructure.config.config_manager import ConfigManager


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_config() -> MagicMock:
    return MagicMock(spec=ConfigManager)


@pytest.fixture
def mock_tia_client() -> MagicMock:
    client = MagicMock()
    client.execute_transactional_batch = AsyncMock(
        return_value={"operations_executed": 2, "details": []}
    )
    return client


@pytest.fixture
def mock_app_state() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_bloques_cache() -> MagicMock:
    cache = MagicMock()
    cache.plc_name = "S7-1500"
    return cache


@pytest.fixture
def real_progress() -> ProgressTracker:
    return ProgressTracker()


@pytest.fixture
def progress(real_progress: ProgressTracker) -> ProgressTracker:
    real_progress.begin(
        operation="proc_sincronizar_test",
        label="Sincronizar comentarios del proceso (test)",
        stages=[
            "check_state_commit", "check_blocks_commit",
            "build_slot_maps_commit", "sync_nmax",
            "wait_consolidation", "compile_proc_blocks",
            "open_transaction", "done",
        ],
    )
    return real_progress


def make_fb(
    config: MagicMock,
    tia_client: MagicMock,
    app_state: MagicMock,
    bloques_cache: MagicMock,
    progress_tracker: ProgressTracker,
) -> FunctionProcSincronizar:
    return FunctionProcSincronizar(
        nombre="proc_sincronizar_test",
        config_manager=config,
        tia_client=tia_client,
        app_state=app_state,
        bloques_cache=bloques_cache,
        tracker=progress_tracker,
    )


def _patch_helper_fns() -> ExitStack:
    """Parchea todas las funciones del helper como no-op.

    El test puede sobre-escribir ``proc_done_summary_commit`` con su
    propio side_effect despues de entrar al contexto.
    """
    stack = ExitStack()
    stack.enter_context(
        patch.object(helper_mod, "proc_check_state_commit", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(helper_mod, "proc_check_blocks_commit", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(helper_mod, "proc_build_slot_maps_commit", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(helper_mod, "proc_compute_nmax_ops", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(helper_mod, "proc_sync_nmax", AsyncMock(), create=True)
    )
    stack.enter_context(
        patch.object(helper_mod, "proc_wait_consolidation", AsyncMock(), create=True)
    )
    stack.enter_context(
        patch.object(helper_mod, "proc_compile_blocks", AsyncMock(), create=True)
    )
    stack.enter_context(
        patch.object(helper_mod, "proc_open_transaction", AsyncMock(), create=True)
    )
    stack.enter_context(
        patch.object(helper_mod, "proc_done_summary_commit", MagicMock(), create=True)
    )
    return stack


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proc_sincronizar_happy_path_8_ticks(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Happy path: 10 ticks -> nStep=99, todas las funciones del helper
    llamadas una vez, ``self.result`` con la shape legacy.

    : el FB ahora tiene 8 steps (3 nuevos: sync_nmax,
    wait_consolidation, compile_proc_blocks), por lo que el flujo es:
      tick #1:  10 -> 20 (on_start + tracker.begin)
      ticks #2-9: 20 (8 steps; nStep NO avanza)
      tick #10: 95 -> 99 (on_finish)
    """
    fake_result = {
        "proc_uid": 42,
        "plc_name": "S7-1500",
        "success": True,
        "applied": True,
        "operations_executed": 2,
        "details": [
            {"command": "update_proc_comments_db_param", "ok": True},
            {"command": "update_proc_comments_db_alm", "ok": True},
        ],
        "warnings": [],
    }

    def fake_done_summary(ctx: Any) -> None:
        ctx.result = dict(fake_result)

    fake_slot_map = MagicMock()
    fake_slot_map.missing_blocks = []
    fake_slot_map.preal = {1: "Bomba 1"}
    fake_slot_map.pint = {1: "Param 1"}
    fake_slot_map.alm = {1: "Alarma 1"}
    fake_slot_map.warnings = []

    def fake_build_slot_maps(ctx: Any) -> None:
        ctx.slot_map = fake_slot_map

    with _patch_helper_fns() as stack:
        # Sobre-escribimos ``proc_build_slot_maps_commit`` y
        # ``proc_done_summary_commit``.
        stack.enter_context(
            patch.object(
                helper_mod, "proc_build_slot_maps_commit",
                side_effect=fake_build_slot_maps, create=True,
            )
        )
        stack.enter_context(
            patch.object(
                helper_mod, "proc_done_summary_commit",
                side_effect=fake_done_summary, create=True,
            )
        )

        fb = make_fb(
            mock_config, mock_tia_client, mock_app_state,
            mock_bloques_cache, progress,
        )

        ok = await fb.start(plc_name="S7-1500", proc_uid=42)
        assert ok is True
        assert fb.nStep == 10

        # State machine del FunctionBase:
        #   tick #1: 10 -> 20 (on_start + tracker.begin)
        #   ticks #2-10: 20 (corren los 9 steps; nStep NO avanza)
        #   tick #11: 95 -> 99 (on_finish)
        n_ticks_done = 0
        await fb.tick()
        n_ticks_done += 1
        assert fb.nStep == 20

        for _ in range(9):
            await fb.tick()
            n_ticks_done += 1
            assert fb.nStep in (20, 95)
        assert fb.nStep == 95

        await fb.tick()
        n_ticks_done += 1
        assert fb.nStep == 99
        assert n_ticks_done == 11

        assert fb.is_terminal() is True
        assert fb.error_msg is None
        assert fb.result is not None
        assert fb.result["success"] is True
        assert fb.result["operations_executed"] == 2
        assert fb.result["plc_name"] == "S7-1500"
        assert fb.result["proc_uid"] == 42

        # Cada helper fue llamado 1 vez.
        assert helper_mod.proc_check_state_commit.call_count == 1
        assert helper_mod.proc_check_blocks_commit.call_count == 1
        assert helper_mod.proc_build_slot_maps_commit.call_count == 1
        assert helper_mod.proc_compute_nmax_ops.call_count == 1
        assert helper_mod.proc_sync_nmax.await_count == 1
        assert helper_mod.proc_wait_consolidation.await_count == 1
        assert helper_mod.proc_compile_blocks.await_count == 1
        assert helper_mod.proc_open_transaction.await_count == 1
        assert helper_mod.proc_done_summary_commit.call_count == 1


# ── Sad paths (pre-flight en on_start) ──────────────────────────────


@pytest.mark.asyncio
async def test_proc_sincronizar_sad_no_config(
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Sin ``config_manager`` -> primer tick falla con "config_manager"."""
    fb = FunctionProcSincronizar(
        nombre="no_config_test",
        config_manager=None,
        tia_client=mock_tia_client,
        app_state=mock_app_state,
        bloques_cache=mock_bloques_cache,
        tracker=progress,
    )
    await fb.start(plc_name="S7-1500", proc_uid=42)
    assert fb.nStep == 10

    await fb.tick()  # 10 -> 98
    assert fb.nStep == fb.n_error
    assert "config_manager" in fb.error_msg


@pytest.mark.asyncio
async def test_proc_sincronizar_sad_no_tia_client(
    mock_config: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Sin ``tia_client`` -> primer tick falla con "tia_client"."""
    fb = FunctionProcSincronizar(
        nombre="no_tia_test",
        config_manager=mock_config,
        tia_client=None,
        app_state=mock_app_state,
        bloques_cache=mock_bloques_cache,
        tracker=progress,
    )
    await fb.start(plc_name="S7-1500", proc_uid=42)
    assert fb.nStep == 10

    await fb.tick()  # 10 -> 98
    assert fb.nStep == fb.n_error
    assert "tia_client" in fb.error_msg


@pytest.mark.asyncio
async def test_proc_sincronizar_sad_no_plc_name(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """``start()`` sin ``plc_name`` -> primer tick falla con ValueError."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_state,
        mock_bloques_cache, progress,
    )
    await fb.start(proc_uid=42)
    assert fb.nStep == 10

    await fb.tick()  # 10 -> 98
    assert fb.nStep == fb.n_error
    assert "plc_name" in fb.error_msg


@pytest.mark.asyncio
async def test_proc_sincronizar_sad_no_proc_uid(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """``start()`` sin ``proc_uid`` -> primer tick falla con ValueError."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_state,
        mock_bloques_cache, progress,
    )
    await fb.start(plc_name="S7-1500")
    assert fb.nStep == 10

    await fb.tick()  # 10 -> 98
    assert fb.nStep == fb.n_error
    assert "proc_uid" in fb.error_msg


# ── Sad paths (en ticks ejecutivos) ────────────────────────────────


@pytest.mark.asyncio
async def test_proc_sincronizar_sad_check_state_no_excel(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Si helper reporta excel no cargado, el primer step ejecutivo falla."""
    def bad_check_state(ctx: Any) -> None:
        ctx.excel_loaded = False

    with _patch_helper_fns() as stack:
        stack.enter_context(
            patch.object(
                helper_mod, "proc_check_state_commit",
                side_effect=bad_check_state, create=True,
            )
        )

        fb = make_fb(
            mock_config, mock_tia_client, mock_app_state,
            mock_bloques_cache, progress,
        )
        await fb.start(plc_name="S7-1500", proc_uid=42)
        await fb.tick()  # 10 -> 20 (on_start)
        await fb.tick()  # 20 -> 98 (check_state falla)

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "Excel" in fb.error_msg


@pytest.mark.asyncio
async def test_proc_sincronizar_sad_missing_blocks(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Si slot_map.missing_blocks poblado, el tercer step ejecutivo falla."""
    fake_sm = MagicMock()
    fake_sm.missing_blocks = ["DB42_CPR_PARAM no esta en el PLC"]
    fake_sm.preal = {1: "Bomba 1"}
    fake_sm.pint = {1: "Param 1"}
    fake_sm.alm = {1: "Alarma 1"}

    def bad_build_slot_maps(ctx: Any) -> None:
        ctx.slot_map = fake_sm

    with _patch_helper_fns() as stack:
        stack.enter_context(
            patch.object(
                helper_mod, "proc_build_slot_maps_commit",
                side_effect=bad_build_slot_maps, create=True,
            )
        )

        fb = make_fb(
            mock_config, mock_tia_client, mock_app_state,
            mock_bloques_cache, progress,
        )
        await fb.start(plc_name="S7-1500", proc_uid=42)
        await fb.tick()  # 10 -> 20
        await fb.tick()  # 20: check_state_commit (excel_loaded=True)
        await fb.tick()  # 20: check_blocks_commit (bloques_loaded=True)
        await fb.tick()  # 20 -> 98 (build_slot_maps con missing)

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "missing" in fb.error_msg.lower() or "faltan" in fb.error_msg.lower()


@pytest.mark.asyncio
async def test_proc_sincronizar_sad_open_transaction_fails(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Si el gateway falla, el 4º step ejecutivo falla (rollback atomico)."""
    fake_slot_map = MagicMock()
    fake_slot_map.missing_blocks = []
    fake_slot_map.preal = {1: "Bomba 1"}
    fake_slot_map.pint = {1: "Param 1"}
    fake_slot_map.alm = {1: "Alarma 1"}

    def fake_build_slot_maps(ctx: Any) -> None:
        ctx.slot_map = fake_slot_map

    with _patch_helper_fns() as stack:
        stack.enter_context(
            patch.object(
                helper_mod, "proc_build_slot_maps_commit",
                side_effect=fake_build_slot_maps, create=True,
            )
        )
        stack.enter_context(
            patch.object(
                helper_mod, "proc_open_transaction",
                side_effect=RuntimeError("Bloque DB42_CPR_PARAM no encontrado"),
                create=True,
            )
        )

        fb = make_fb(
            mock_config, mock_tia_client, mock_app_state,
            mock_bloques_cache, progress,
        )
        await fb.start(plc_name="S7-1500", proc_uid=42)
        await fb.tick()  # 10 -> 20
        await fb.tick()  # 20: check_state_commit
        await fb.tick()  # 20: check_blocks_commit
        await fb.tick()  # 20: build_slot_maps_commit (+ calc nmax)
        await fb.tick()  # 20: sync_nmax
        await fb.tick()  # 20: wait_consolidation
        await fb.tick()  # 20: compile_proc_blocks
        await fb.tick()  # 20 -> 98 (open_transaction falla)

    assert fb.nStep == fb.n_error
    assert "DB42_CPR_PARAM" in fb.error_msg


# ── Terminal ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proc_sincronizar_terminal_no_avanza_mas(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_state,
        mock_bloques_cache, progress,
    )
    await fb.start(plc_name="S7-1500", proc_uid=42)

    fb.nStep = fb.n_done
    n_step_before = fb.nStep

    await fb.tick()
    assert fb.nStep == n_step_before
