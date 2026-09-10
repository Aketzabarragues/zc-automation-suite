"""Tests del FB ``FunctionGenerarPreview``.

Fase 2, paso 2.1.4b.  Cubren:
  - Happy path: 3 ticks → nStep=99, use case ``generar_prevision``
    llamado 1 vez con ``plc_name`` correcto, ``self.result`` con
    el shape legacy que devuelve el use case.
  - Sad path: el use case lanza ``RuntimeError`` → nStep=98,
    ``error_msg`` poblado, ``self.result`` queda ``None``.
  - Sad path 2: el FB se construye sin ``gateway`` → primer tick
    falla con ``RuntimeError`` mencionando "gateway".
  - Pre-flight: ``plc_name`` vacío → ``ValueError``.
  - Terminal: ticks extra sobre ``n_done`` son no-op.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.functions.function_GenerarPreview import (
    FunctionGenerarPreview,
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
    """Shape legacy que devuelve ``use_case.generar_prevision``."""
    return {
        "agregados": [{"uid": "1", "table": "2000_Disp_ED", "plc_tag": "tag1"}],
        "eliminados": [],
        "renombrados": [],
        "todos": [
            {"uid": "1", "table": "2000_Disp_ED", "type": "ed", "numero": 1,
             "actual": "tag1", "nuevo": "tag1", "status": "sin_cambios"},
        ],
        "nmax": {"todos": [], "summary": {"agregados": 0, "eliminados": 0,
                                           "renombrados": 0, "actualizar": 0}},
        "summary": {"agregados": 0, "eliminados": 0, "renombrados": 0,
                     "actualizar": 0},
    }


@pytest.fixture
def mock_use_case_factory(fake_prevision: dict[str, Any]):
    """Factoría que devuelve un use case mock cuyo
    ``generar_prevision()`` retorna ``fake_prevision``.
    """
    def factory(**_kwargs: Any) -> MagicMock:
        use_case = MagicMock()
        use_case.generar_prevision = AsyncMock(return_value=fake_prevision)
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
) -> FunctionGenerarPreview:
    return FunctionGenerarPreview(
        nombre="generar_preview_test",
        gateway=gateway,
        config_manager=config,
        progress_tracker=progress,
        use_case_factory=use_case_factory,
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generar_preview_happy_path_3_ticks(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
    fake_prevision: dict[str, Any],
) -> None:
    """Happy path: 3 ticks → nStep=99, use case llamado 1 vez,
    ``self.result`` con el dict del use case."""
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
    # El use case mock fue instanciado y llamado
    assert fb._use_case is not None
    fb._use_case.generar_prevision.assert_awaited_once_with("S7-1500")

    # Tick #3: set result + done (30 → 99)
    await fb.tick()
    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True
    assert fb.error_msg is None
    assert fb.result is fake_prevision  # misma referencia


@pytest.mark.asyncio
async def test_generar_preview_sad_use_case_raises(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    real_progress: ProgressTracker,
) -> None:
    """El use case lanza ``RuntimeError`` → nStep=98, ``error_msg``
    poblado, ``self.result`` queda ``None``."""
    def bad_factory(**_kwargs: Any) -> MagicMock:
        use_case = MagicMock()
        use_case.generar_prevision = AsyncMock(
            side_effect=RuntimeError("TIA Portal no responde")
        )
        return use_case

    fb = make_fb(mock_gateway, mock_config, bad_factory, real_progress)
    await fb.start(plc_name="S7-1500")
    await fb.tick()  # 10 → 20
    await fb.tick()  # 20 → 98 (use case falla)

    assert fb.nStep == fb.n_error
    assert fb.is_terminal() is True
    assert fb.error_msg is not None
    assert "TIA Portal no responde" in fb.error_msg
    assert fb.result is None


@pytest.mark.asyncio
async def test_generar_preview_sad_no_gateway(
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
) -> None:
    """Sin ``gateway`` → el primer tick falla con RuntimeError
    mencionando "gateway"."""
    fb = FunctionGenerarPreview(
        nombre="no_gateway",
        gateway=None,  # ← explícito
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
    # El use case NO se instanció (falló antes)
    assert fb._use_case is None


@pytest.mark.asyncio
async def test_generar_preview_sad_no_plc_name(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
) -> None:
    """``start()`` sin ``plc_name`` → el primer tick falla con ValueError."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )
    # start() con params vacíos: ``_params = {}``
    await fb.start()  # sin kwargs
    assert fb.nStep == 10
    assert fb._params == {}

    await fb.tick()  # 10 → 98 (plc_name ausente)

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "plc_name" in fb.error_msg
    assert fb._use_case is None


@pytest.mark.asyncio
async def test_generar_preview_terminal_no_avanza_mas(
    mock_gateway: MagicMock,
    mock_config: MagicMock,
    mock_use_case_factory,
    real_progress: ProgressTracker,
) -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op (guarda de la base)."""
    fb = make_fb(
        mock_gateway, mock_config, mock_use_case_factory, real_progress
    )
    await fb.start(plc_name="S7-1500")

    # Forzar n_done (sin esperar 3 ticks)
    fb.nStep = fb.n_done
    n_step_before = fb.nStep

    await fb.tick()
    assert fb.nStep == n_step_before  # no avanza
    # Use case NO se llamó (no llegamos a nStep=20)
    assert fb._use_case is None
