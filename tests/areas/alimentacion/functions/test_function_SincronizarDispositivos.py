"""Tests del FB ``FunctionSincronizarDispositivos``.

Fase 2, paso 2.1.5.  Cubren:
  - Happy path: 3 ticks → nStep=99, use case ``ejecutar_transaccion``
    llamado 1 vez con ``plc_name`` y ``prevision`` correctos,
    ``self.result`` con el dict del use case.
  - Sad path: el use case lanza ``RuntimeError`` → nStep=98,
    ``error_msg`` poblado, ``self.result`` queda ``None``.
  - Sad path 2: el FB se construye sin ``gateway`` → primer tick
    falla con ``RuntimeError`` mencionando "gateway".
  - Pre-flight: ``plc_name`` ausente → ``ValueError``.
  - Pre-flight: ``prevision`` ausente o no-dict → ``ValueError``.
  - Terminal: ticks extra sobre ``n_done`` son no-op.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.functions.function_SincronizarDispositivos import (
    FunctionSincronizarDispositivos,
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
    """Output de ``generar_prevision``: dict con ``agregados``,
    ``eliminados``, ``renombrados``, ``todos``, ``nmax``, ``summary``.
    """
    return {
        "agregados": [{"uid": "1", "table": "2000_Disp_ED", "plc_tag": "tag1"}],
        "eliminados": [],
        "renombrados": [],
        "todos": [],
        "nmax": {"todos": [], "summary": {"agregados": 0, "eliminados": 0,
                                           "renombrados": 0, "actualizar": 0}},
        "summary": {"agregados": 1, "eliminados": 0, "renombrados": 0,
                     "actualizar": 0},
    }


@pytest.fixture
def fake_commit_result() -> dict[str, Any]:
    """Output de ``ejecutar_transaccion``: dict con ``success``,
    ``message``, ``added``, ``removed``, ``renombrados``,
    ``operations``, ``n_max_updates``, ``post_sync_preview``,
    ``comments_sync``.
    """
    return {
        "success": True,
        "message": "Sync aplicado OK",
        "added": ["1"],
        "removed": [],
        "renombrados": [],
        "operations": 5,
        "n_max_updates": 0,
        "post_sync_preview": {"agregados": [], "eliminados": [],
                                "renombrados": [], "todos": [],
                                "nmax": {}, "summary": {}},
        "comments_sync": {"applied": True, "operations_executed": 0,
                          "warnings": [], "error": None},
    }


@pytest.fixture
def mock_use_case_factory(fake_commit_result: dict[str, Any]):
    """Factoría que devuelve un use case mock cuyo
    ``ejecutar_transaccion()`` retorna ``fake_commit_result``.
    """
    def factory(**_kwargs: Any) -> MagicMock:
        use_case = MagicMock()
        use_case.ejecutar_transaccion = AsyncMock(
            return_value=fake_commit_result
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
) -> FunctionSincronizarDispositivos:
    return FunctionSincronizarDispositivos(
        nombre="sincronizar_disp_test",
        gateway=gateway,
        config_manager=config,
        progress_tracker=progress,
        use_case_factory=use_case_factory,
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sincronizar_disp_happy_path_3_ticks(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
    fake_prevision: dict[str, Any],
    fake_commit_result: dict[str, Any],
) -> None:
    """Happy path: 3 ticks → nStep=99, use case llamado 1 vez con
    plc_name y prevision correctos, ``self.result`` con el dict."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )

    ok = await fb.start(plc_name="S7-1500", prevision=fake_prevision)
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
        "S7-1500", fake_prevision
    )

    # Tick #3: set result + done (30 → 99)
    await fb.tick()
    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True
    assert fb.error_msg is None
    assert fb.result is fake_commit_result  # misma referencia


@pytest.mark.asyncio
async def test_sincronizar_disp_sad_use_case_raises(
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
            side_effect=RuntimeError("Transacción COM abortada")
        )
        return use_case

    fb = make_fb(mock_gateway, mock_config, bad_factory, real_progress)
    await fb.start(plc_name="S7-1500", prevision=fake_prevision)
    await fb.tick()  # 10 → 20
    await fb.tick()  # 20 → 98 (use case falla)

    assert fb.nStep == fb.n_error
    assert fb.is_terminal() is True
    assert fb.error_msg is not None
    assert "Transacción COM abortada" in fb.error_msg
    assert fb.result is None


@pytest.mark.asyncio
async def test_sincronizar_disp_sad_no_gateway(
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
    fake_prevision: dict[str, Any],
) -> None:
    """Sin ``gateway`` → el primer tick falla con RuntimeError
    mencionando "gateway"."""
    fb = FunctionSincronizarDispositivos(
        nombre="no_gateway",
        gateway=None,
        config_manager=mock_config,
        progress_tracker=real_progress,
        use_case_factory=mock_use_case_factory,
    )
    await fb.start(plc_name="S7-1500", prevision=fake_prevision)
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "gateway" in fb.error_msg
    assert fb._use_case is None


@pytest.mark.asyncio
async def test_sincronizar_disp_sad_no_plc_name(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
    fake_prevision: dict[str, Any],
) -> None:
    """``start()`` sin ``plc_name`` → el primer tick falla con ValueError."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )
    # start() solo con prevision, sin plc_name
    await fb.start(prevision=fake_prevision)
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "plc_name" in fb.error_msg


@pytest.mark.asyncio
async def test_sincronizar_disp_sad_no_prevision(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
) -> None:
    """``start()`` sin ``prevision`` → el primer tick falla con ValueError."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )
    # start() solo con plc_name, sin prevision
    await fb.start(plc_name="S7-1500")
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "prevision" in fb.error_msg


@pytest.mark.asyncio
async def test_sincronizar_disp_terminal_no_avanza_mas(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
) -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )
    await fb.start(plc_name="S7-1500", prevision={"agregados": []})

    # Forzar n_done
    fb.nStep = fb.n_done
    n_step_before = fb.nStep

    await fb.tick()
    assert fb.nStep == n_step_before
    # Use case NO se llamó
    assert fb._use_case is None
