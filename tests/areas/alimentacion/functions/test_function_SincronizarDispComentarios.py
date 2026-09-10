"""Tests del FB ``FunctionSincronizarDispComentarios``.

Fase 2, paso 2.1.6.  Cubren:
  - Happy path: 3 ticks → nStep=99, use case ``apply_comentarios_disp``
    llamado 1 vez con ``plc_name`` correcto, ``self.result`` con el
    dict del use case.
  - Sad path: el use case lanza ``RuntimeError`` → nStep=98,
    ``error_msg`` poblado, ``self.result`` queda ``None``.
  - Sad path 2: el FB se construye sin ``gateway`` → primer tick
    falla con ``RuntimeError`` mencionando "gateway".
  - Sad path 3: el FB se construye sin ``config_manager`` → primer
    tick falla con ``RuntimeError`` mencionando "config_manager".
  - Pre-flight: ``plc_name`` ausente → ``ValueError``.
  - Terminal: ticks extra sobre ``n_done`` son no-op.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.functions.function_SincronizarDispComentarios import (
    FunctionSincronizarDispComentarios,
)
from core.application.progress_buffer import ProgressTracker
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_gateway() -> MagicMock:
    return MagicMock(spec=TIAProcessGateway)


@pytest.fixture
def mock_config() -> MagicMock:
    return MagicMock(spec=ConfigManager)


@pytest.fixture
def fake_apply_result() -> dict[str, Any]:
    """Output de ``apply_comentarios_disp``: dict con ``plc_name``,
    ``success``, ``applied``, ``operations_executed``, ``summary``,
    ``details``, ``warnings``.
    """
    return {
        "plc_name": "S7-1500",
        "success": True,
        "applied": True,
        "operations_executed": 24,
        "summary": {"disp_dbs_updated": 6, "total_ops": 24},
        "details": [{"hw": "ed", "ops": 4}, {"hw": "ea", "ops": 4}],
        "warnings": [],
    }


@pytest.fixture
def mock_use_case_factory(fake_apply_result: dict[str, Any]):
    """Factoría que devuelve un use case mock cuyo
    ``apply_comentarios_disp()`` retorna ``fake_apply_result``.
    """
    def factory(**_kwargs: Any) -> MagicMock:
        use_case = MagicMock()
        use_case.apply_comentarios_disp = AsyncMock(
            return_value=fake_apply_result
        )
        return use_case
    return factory


@pytest.fixture
def real_progress() -> ProgressTracker:
    return ProgressTracker()


def make_fb(
    gateway: MagicMock,
    config: MagicMock,
    use_case_factory,
    progress: ProgressTracker,
) -> FunctionSincronizarDispComentarios:
    return FunctionSincronizarDispComentarios(
        nombre="sincronizar_disp_comentarios_test",
        gateway=gateway,
        config_manager=config,
        progress_tracker=progress,
        use_case_factory=use_case_factory,
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sincronizar_disp_comentarios_happy_path_3_ticks(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
    fake_apply_result: dict[str, Any],
) -> None:
    """Happy path: 3 ticks → nStep=99, use case llamado 1 vez con
    plc_name correcto, ``self.result`` con el dict."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )

    ok = await fb.start(plc_name="S7-1500")
    assert ok is True
    assert fb.nStep == 10

    # Tick #1: pre-flight (10 → 20)
    await fb.tick()
    assert fb.nStep == 20

    # Tick #2: delega al use case (20 → 30)
    await fb.tick()
    assert fb.nStep == 30
    assert fb._use_case is not None
    fb._use_case.apply_comentarios_disp.assert_awaited_once_with("S7-1500")

    # Tick #3: set result + done (30 → 99)
    await fb.tick()
    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True
    assert fb.error_msg is None
    assert fb.result is fake_apply_result  # misma referencia


@pytest.mark.asyncio
async def test_sincronizar_disp_comentarios_sad_use_case_raises(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    real_progress: ProgressTracker,
) -> None:
    """El use case lanza ``RuntimeError`` → nStep=98, ``error_msg``
    poblado, ``self.result`` queda ``None``."""
    def bad_factory(**_kwargs: Any) -> MagicMock:
        use_case = MagicMock()
        use_case.apply_comentarios_disp = AsyncMock(
            side_effect=RuntimeError("AppState vacío, cargue el Excel primero")
        )
        return use_case

    fb = make_fb(mock_gateway, mock_config, bad_factory, real_progress)
    await fb.start(plc_name="S7-1500")
    await fb.tick()  # 10 → 20
    await fb.tick()  # 20 → 98 (use case falla)

    assert fb.nStep == fb.n_error
    assert fb.is_terminal() is True
    assert fb.error_msg is not None
    assert "AppState vacío" in fb.error_msg
    assert fb.result is None


@pytest.mark.asyncio
async def test_sincronizar_disp_comentarios_sad_no_gateway(
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
) -> None:
    """Sin ``gateway`` → el primer tick falla con RuntimeError
    mencionando "gateway"."""
    fb = FunctionSincronizarDispComentarios(
        nombre="no_gateway",
        gateway=None,
        config_manager=mock_config,
        progress_tracker=real_progress,
        use_case_factory=mock_use_case_factory,
    )
    await fb.start(plc_name="S7-1500")
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "gateway" in fb.error_msg
    assert fb._use_case is None


@pytest.mark.asyncio
async def test_sincronizar_disp_comentarios_sad_no_config(
    mock_gateway: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
) -> None:
    """Sin ``config_manager`` → el primer tick falla con RuntimeError
    mencionando "config_manager"."""
    fb = FunctionSincronizarDispComentarios(
        nombre="no_config",
        gateway=mock_gateway,
        config_manager=None,
        progress_tracker=real_progress,
        use_case_factory=mock_use_case_factory,
    )
    await fb.start(plc_name="S7-1500")
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "config_manager" in fb.error_msg
    assert fb._use_case is None


@pytest.mark.asyncio
async def test_sincronizar_disp_comentarios_sad_no_plc_name(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
) -> None:
    """``start()`` sin ``plc_name`` → el primer tick falla con ValueError."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )
    await fb.start()  # sin kwargs
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "plc_name" in fb.error_msg


@pytest.mark.asyncio
async def test_sincronizar_disp_comentarios_terminal_no_avanza_mas(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
) -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )
    await fb.start(plc_name="S7-1500")

    # Forzar n_done
    fb.nStep = fb.n_done
    n_step_before = fb.nStep

    await fb.tick()
    assert fb.nStep == n_step_before
    # Use case NO se llamó
    assert fb._use_case is None
