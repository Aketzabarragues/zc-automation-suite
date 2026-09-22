"""Tests del FB ``FunctionProcDBGenerarPreview``.

Cubre:
  - Happy path: 8 ticks (1 arrancar + 6 steps + 1 finalizar), ``self.result``
    con la shape legacy, helper llamado 1 vez por step, progress stages
    completos.
  - Sad path 1: sin ``config_manager`` -> nStep=98 con ``error_msg``
    mencionando "config_manager".
  - Sad path 2: sin ``tia_client`` -> nStep=98 con ``error_msg``
    mencionando "tia_client".
  - Sad path 3: ``start()`` sin ``plc_name`` o con valor invalido ->
    ValueError.
  - Sad path 4: ``start()`` sin ``proc_uid`` o no-int -> ValueError.
  - Estado terminal: ticks extra sobre ``n_done`` son no-op.

Mockeamos el helper ``proc_generar_preview`` (sus funciones) para
validar SOLO la state machine del FB (no la logica del helper; eso
tiene su propio test en ``test_proc_generar_preview.py``).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from areas.alimentacion.functions.function_proc_db_generar_preview import (
    FunctionProcDBGenerarPreview,
)
from core.runtime.app_state import AppState
from core.runtime.progress_buffer import ProgressTracker
from core.infrastructure.config.config_manager import ConfigManager


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_config() -> MagicMock:
    return MagicMock(spec=ConfigManager)


@pytest.fixture
def mock_tia_client() -> MagicMock:
    """Gateway mockeado. Los export_* son AsyncMock; no se llaman en
    este test porque parcheamos el helper."""
    client = MagicMock()
    client.export_plc_tags_xml = AsyncMock(return_value=None)
    client.export_block = AsyncMock(return_value=None)
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
    """Tracker con ``begin()`` ya invocado, mismo patron que el use
    case legacy asume."""
    real_progress.begin(
        operation="proc_generar_preview_test",
        label="Generar preview proceso (test)",
        stages=[
            "check_state", "check_blocks", "build_slot_maps",
            "compute_nmax", "export_and_diff", "done",
        ],
    )
    return real_progress


def make_fb(
    config: MagicMock,
    tia_client: MagicMock,
    app_state: MagicMock,
    bloques_cache: MagicMock,
    progress_tracker: ProgressTracker,
) -> FunctionProcDBGenerarPreview:
    return FunctionProcDBGenerarPreview(
        nombre="proc_generar_preview_test",
        config_manager=config,
        tia_client=tia_client,
        app_state=app_state,
        bloques_cache=bloques_cache,
        tracker=progress_tracker,
    )


def _patch_helper_fns(fb) -> Any:
    """Helper: parchea todas las funciones del FB para que sean no-op.

    Devuelve un context manager compuesto que podemos usar con ``with``.
    Cada funcion del FB se reemplaza por un mock vacio (sync o
    async segun corresponda). ``proc_compose_response`` se reemplaza
    por un MagicMock que el test puede sobreescribir.
    """
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(
        patch.object(fb, "proc_check_state", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "proc_check_blocks", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "proc_build_slot_maps", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "proc_compute_nmax", AsyncMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "proc_export_and_diff", AsyncMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "proc_compose_response", MagicMock(), create=True)
    )
    return stack


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proc_generar_preview_happy_path_6_ticks(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Happy path: 8 ticks -> nStep=99, todas las funciones del helper
    llamadas una vez, ``self.result`` con la shape legacy."""
    fake_result = {
        "proc_uid": 42,
        "proc_codigo": "CPR",
        "precondiciones_ok": True,
        "missing_blocks": [],
        "db_param_name": "DB42_CPR_PARAM",
        "db_alm_name": "DB42_CPR_ALM",
        "table_name": "42_CPR",
        "arrays": {"PReal": {}, "PInt": {}, "ALM": {}},
        "summary": {"total": 0, "agregados": 0, "renombrados": 0,
                    "eliminados": 0, "sin_cambios": 0},
        "nmax": {"current": {}, "desired": {}, "todos": [],
                 "summary": {"actualizar": 0, "sin_cambios": 0, "total": 0}},
        "warnings": [],
    }

    def fake_compose() -> None:
        fb._ctx.result = dict(fake_result)

    fb = make_fb(
        mock_config, mock_tia_client, mock_app_state,
        mock_bloques_cache, progress,
    )
    with _patch_helper_fns(fb) as stack:
        # Sobre-escribimos proc_compose_response con nuestra version.
        stack.enter_context(
            patch.object(
                fb, "proc_compose_response",
                side_effect=fake_compose, create=True,
            )
        )

        ok = await fb.start(plc_name="S7-1500", proc_uid=42)
        assert ok is True
        assert fb.nStep == 10

        # State machine del FunctionBase:
        #   tick #1: 10 -> 20 (on_start + tracker.begin)
        #   ticks #2-7: 20 (corren los 6 steps; nStep NO avanza)
        #   tick #8: 95 -> 99 (on_finish)
        n_ticks_done = 0
        # Tick #1: arrancar (10 -> 20).
        await fb.tick()
        n_ticks_done += 1
        assert fb.nStep == 20

        # Ticks #2-7: ejecutar 6 steps (nStep se mantiene en 20, luego 95).
        for _ in range(6):
            await fb.tick()
            n_ticks_done += 1
            assert fb.nStep in (20, 95)
        assert fb.nStep == 95

        # Tick #8: on_finish -> 99.
        await fb.tick()
        n_ticks_done += 1
        assert fb.nStep == 99
        assert n_ticks_done == 8

        assert fb.is_terminal() is True
        assert fb.error_msg is None
        assert fb.result is not None
        assert fb.result["precondiciones_ok"] is True
        assert fb.result["proc_uid"] == 42
        assert fb.result["db_param_name"] == "DB42_CPR_PARAM"

        # Cada helper fue llamado 1 vez (los MagicMock auto-trackean).
        assert fb.proc_check_state.call_count == 1
        assert fb.proc_check_blocks.call_count == 1
        assert fb.proc_build_slot_maps.call_count == 1
        assert fb.proc_compute_nmax.await_count == 1
        assert fb.proc_export_and_diff.await_count == 1
        assert fb.proc_compose_response.call_count == 1


# ── Sad paths (pre-flight) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_proc_generar_preview_sad_no_config(
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Sin ``config_manager`` -> primer tick falla con "config_manager"."""
    fb = FunctionProcDBGenerarPreview(
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
    assert fb.error_msg is not None
    assert "config_manager" in fb.error_msg


@pytest.mark.asyncio
async def test_proc_generar_preview_sad_no_tia_client(
    mock_config: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Sin ``tia_client`` -> primer tick falla con "tia_client"."""
    fb = FunctionProcDBGenerarPreview(
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
async def test_proc_generar_preview_sad_no_plc_name(
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
    await fb.start(proc_uid=42)  # sin plc_name
    assert fb.nStep == 10

    await fb.tick()  # 10 -> 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "plc_name" in fb.error_msg


@pytest.mark.asyncio
async def test_proc_generar_preview_sad_no_proc_uid(
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
    await fb.start(plc_name="S7-1500")  # sin proc_uid
    assert fb.nStep == 10

    await fb.tick()  # 10 -> 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "proc_uid" in fb.error_msg


@pytest.mark.asyncio
async def test_proc_generar_preview_sad_proc_uid_not_int(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """``start()`` con ``proc_uid`` no-int -> primer tick falla con ValueError."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_state,
        mock_bloques_cache, progress,
    )
    await fb.start(plc_name="S7-1500", proc_uid="42")  # string, no int
    assert fb.nStep == 10

    await fb.tick()  # 10 -> 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "proc_uid" in fb.error_msg


# ── Terminal ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proc_generar_preview_terminal_no_avanza_mas(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_state: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op (guarda de la base)."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_state,
        mock_bloques_cache, progress,
    )
    await fb.start(plc_name="S7-1500", proc_uid=42)

    # Forzar n_done (sin esperar 8 ticks).
    fb.nStep = fb.n_done
    n_step_before = fb.nStep

    await fb.tick()
    assert fb.nStep == n_step_before  # no avanza
