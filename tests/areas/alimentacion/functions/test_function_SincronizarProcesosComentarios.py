"""Tests del FB ``FunctionSincronizarProcesosComentarios``.

Fase 2, paso 2.1.7.  Cubren:
  - Happy path: 3 ticks → nStep=99, use case ``ejecutar_transaccion``
    llamado 1 vez con ``proc_uid`` y ``prevision`` correctos,
    ``self.result`` con el dict del use case.
  - Sad path: el use case lanza ``RuntimeError`` → nStep=98,
    ``error_msg`` poblado, ``self.result`` queda ``None``.
  - Sad path 2: el FB se construye sin ``gateway`` → primer tick
    falla con ``RuntimeError`` mencionando "gateway".
  - Pre-flight: ``proc_uid`` ausente o inválido → ``ValueError``.
  - Pre-flight: ``prevision`` ausente o no-dict → ``ValueError``.
  - Terminal: ticks extra sobre ``n_done`` son no-op.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.functions.function_SincronizarProcesosComentarios import (
    FunctionSincronizarProcesosComentarios,
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
def fake_prevision() -> dict[str, Any]:
    """Output de ``generar_prevision`` para un proceso."""
    return {
        "agregados": [{"uid": 1, "comentario": "Comentario A"}],
        "eliminados": [],
        "renombrados": [],
        "todos": [],
        "summary": {"agregados": 1, "eliminados": 0, "renombrados": 0},
    }


@pytest.fixture
def fake_tx_result() -> dict[str, Any]:
    """Output de ``ejecutar_transaccion``: dict con ``success``,
    ``message``, ``applied``, ``operations_executed``, ``summary``,
    ``warnings``, ``proc_uid``.
    """
    return {
        "success": True,
        "message": "Comentarios aplicados OK",
        "applied": True,
        "operations_executed": 8,
        "summary": {"preal": 3, "pint": 3, "alm": 2, "total": 8},
        "warnings": [],
        "proc_uid": 42,
    }


@pytest.fixture
def mock_use_case_factory(fake_tx_result: dict[str, Any]):
    """Factoría que devuelve un use case mock cuyo
    ``ejecutar_transaccion()`` retorna ``fake_tx_result``.
    """
    def factory(**_kwargs: Any) -> MagicMock:
        use_case = MagicMock()
        use_case.ejecutar_transaccion = AsyncMock(
            return_value=fake_tx_result
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
) -> FunctionSincronizarProcesosComentarios:
    return FunctionSincronizarProcesosComentarios(
        nombre="sincronizar_proc_comentarios_test",
        gateway=gateway,
        config_manager=config,
        progress_tracker=progress,
        use_case_factory=use_case_factory,
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sincronizar_proc_comentarios_happy_path_3_ticks(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
    fake_prevision: dict[str, Any],
    fake_tx_result: dict[str, Any],
) -> None:
    """Happy path: 3 ticks → nStep=99, use case llamado 1 vez con
    proc_uid y prevision correctos, ``self.result`` con el dict."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )

    ok = await fb.start(proc_uid=42, prevision=fake_prevision)
    assert ok is True
    assert fb.nStep == 10

    # Tick #1: pre-flight (10 → 20)
    await fb.tick()
    assert fb.nStep == 20

    # Tick #2: delega al use case (20 → 30)
    await fb.tick()
    assert fb.nStep == 30
    assert fb._use_case is not None
    fb._use_case.ejecutar_transaccion.assert_awaited_once_with(
        42, fake_prevision
    )

    # Tick #3: set result + done (30 → 99)
    await fb.tick()
    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True
    assert fb.error_msg is None
    assert fb.result is fake_tx_result  # misma referencia


@pytest.mark.asyncio
async def test_sincronizar_proc_comentarios_sad_use_case_raises(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    real_progress: ProgressTracker,
    fake_prevision: dict[str, Any],
) -> None:
    """El use case lanza ``RuntimeError`` → nStep=98, ``error_msg``
    poblado, ``self.result`` queda ``None``."""
    def bad_factory(**_kwargs: Any) -> MagicMock:
        use_case = MagicMock()
        use_case.ejecutar_transaccion = AsyncMock(
            side_effect=RuntimeError("Bloque DB2002 no encontrado en TIA")
        )
        return use_case

    fb = make_fb(mock_gateway, mock_config, bad_factory, real_progress)
    await fb.start(proc_uid=42, prevision=fake_prevision)
    await fb.tick()  # 10 → 20
    await fb.tick()  # 20 → 98 (use case falla)

    assert fb.nStep == fb.n_error
    assert fb.is_terminal() is True
    assert fb.error_msg is not None
    assert "DB2002 no encontrado" in fb.error_msg
    assert fb.result is None


@pytest.mark.asyncio
async def test_sincronizar_proc_comentarios_sad_no_gateway(
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
    fake_prevision: dict[str, Any],
) -> None:
    """Sin ``gateway`` → el primer tick falla con RuntimeError
    mencionando "gateway"."""
    fb = FunctionSincronizarProcesosComentarios(
        nombre="no_gateway",
        gateway=None,
        config_manager=mock_config,
        progress_tracker=real_progress,
        use_case_factory=mock_use_case_factory,
    )
    await fb.start(proc_uid=42, prevision=fake_prevision)
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "gateway" in fb.error_msg
    assert fb._use_case is None


@pytest.mark.asyncio
async def test_sincronizar_proc_comentarios_sad_no_proc_uid(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
    fake_prevision: dict[str, Any],
) -> None:
    """``start()`` sin ``proc_uid`` o con valor inválido → ValueError."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )
    # start() sin proc_uid
    await fb.start(prevision=fake_prevision)
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "proc_uid" in fb.error_msg


@pytest.mark.asyncio
async def test_sincronizar_proc_comentarios_sad_no_prevision(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
) -> None:
    """``start()`` sin ``prevision`` → el primer tick falla con ValueError."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )
    # start() solo con proc_uid, sin prevision
    await fb.start(proc_uid=42)
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "prevision" in fb.error_msg


@pytest.mark.asyncio
async def test_sincronizar_proc_comentarios_terminal_no_avanza_mas(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
    fake_prevision: dict[str, Any],
) -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )
    await fb.start(proc_uid=42, prevision=fake_prevision)

    # Forzar n_done
    fb.nStep = fb.n_done
    n_step_before = fb.nStep

    await fb.tick()
    assert fb.nStep == n_step_before
    # Use case NO se llamó
    assert fb._use_case is None
