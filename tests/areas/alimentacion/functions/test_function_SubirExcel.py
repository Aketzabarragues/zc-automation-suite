"""Tests del FB ``FunctionSubirExcel``.

Fase 2, pasos 2.1.1 + 2.1.2.  Cubren:
  - Happy path: 3 ticks avanzan 10→20→30→99 (``n_done``), ``self.result``
    con la shape legacy, AppState populado, cache ``put()`` llamado,
    log de éxito emitido, progress stages completos.
  - Sad path 1: sin ``config_manager`` → nStep=98 (``n_error``) con
    ``error_msg`` mencionando "config_manager".
  - Sad path 2: el loader lanza ``ValueError`` (xlsx corrupto) →
    nStep=98 con ``error_msg`` conteniendo el mensaje original.
  - Estado terminal: ticks extra sobre ``n_done`` no avanzan.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.functions.function_SubirExcel import FunctionSubirExcel
from core.application.log_buffer import LogBuffer
from core.application.progress_buffer import ProgressTracker
from core.application.state import AppState
from core.infrastructure.config_manager import ConfigManager


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_config() -> MagicMock:
    """ConfigManager con 1 hw_type activo (``disp_ed``)."""
    cfg = MagicMock(spec=ConfigManager)
    cfg.list_hw_types_active.return_value = ["disp_ed"]
    cfg.get_excel_target_for.return_value = {"canonical": "DispED"}
    return cfg


@pytest.fixture
def mock_state() -> MagicMock:
    return MagicMock(spec=AppState)


@pytest.fixture
def real_progress() -> ProgressTracker:
    """Tracker real (no mock) para verificar stages emitidos."""
    return ProgressTracker()


@pytest.fixture
def progress(real_progress: ProgressTracker) -> ProgressTracker:
    """Tracker con ``begin()`` ya invocado (mismo contrato que el use
    case legacy asume: el caller hace ``begin()`` antes de ``start()``).

    Stages alineados con ``function_SubirExcel._step_parsear`` y
    ``_step_volcar_y_result``.
    """
    real_progress.begin(
        operation="subir_excel_test",
        label="Subir Excel (test)",
        stages=["parsear_excel", "volcar_appstate"],
    )
    return real_progress


@pytest.fixture
def mock_log() -> MagicMock:
    return MagicMock(spec=LogBuffer)


@pytest.fixture
def fake_cache() -> MagicMock:
    """Cache ficticio con 2 dispositivos en ``disp_ed``."""
    cache = MagicMock()
    cache.dispositivos = {"disp_ed": (("dev1",), ("dev2",))}
    cache.n_max = MagicMock()
    cache.n_max.to_api_dict.return_value = {"max1": 10}
    cache.procesos = []
    cache.parametros_real = []
    cache.parametros_int = []
    cache.alarmas = []
    cache.excel_path = "/fake/path.xlsx"
    return cache


@pytest.fixture
def happy_loader_factory(fake_cache: MagicMock):
    """Factoría que devuelve un loader cuyo ``.load()`` retorna ``fake_cache``."""
    def factory(config_manager: ConfigManager) -> MagicMock:
        loader = MagicMock()
        # ``.load`` es sync; ``asyncio.to_thread`` lo envuelve.
        loader.load = MagicMock(return_value=fake_cache)
        return loader
    return factory


@pytest.fixture
def mock_cache_cls() -> MagicMock:
    """Clase de cache con ``put`` async mockeado."""
    cls = MagicMock()
    cls.put = AsyncMock()
    return cls


def make_fb(
    config_manager: ConfigManager | None,
    state: MagicMock,
    progress: ProgressTracker,
    log: MagicMock,
    loader_factory,
    cache_cls: MagicMock,
) -> FunctionSubirExcel:
    return FunctionSubirExcel(
        nombre="subir_excel_test",
        config_manager=config_manager,
        app_state=state,
        progress_tracker=progress,
        log=log,
        excel_loader_factory=loader_factory,
        excel_cache_cls=cache_cls,
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subir_excel_happy_path_3_ticks(
    mock_config: MagicMock,
    mock_state: MagicMock,
    progress: ProgressTracker,
    mock_log: MagicMock,
    happy_loader_factory,
    mock_cache_cls: MagicMock,
    fake_cache: MagicMock,
) -> None:
    """Happy path: 3 ticks → nStep=99, result + AppState + cache + log."""
    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        happy_loader_factory, mock_cache_cls,
    )

    ok = await fb.start(xlsx_path="/fake/path.xlsx")
    assert ok is True
    assert fb.nStep == 10

    # Tick #1: pre-flight (10 → 20)
    await fb.tick()
    assert fb.nStep == 20

    # Tick #2: parse + cache (20 → 30)
    await fb.tick()
    assert fb.nStep == 30
    mock_cache_cls.put.assert_awaited_once_with(fake_cache)

    # Tick #3: volcar AppState + summary + result (30 → 99)
    await fb.tick()
    assert fb.nStep == fb.n_done  # 99
    assert fb.is_terminal() is True
    assert fb.error_msg is None

    # Result con la shape legacy
    assert fb.result == {
        "ok": True,
        "summary": {"DispED": 2},
        "total_dispositivos": 2,
        "dimensiones": {"max1": 10},
    }

    # AppState populado con la shape legacy (list de device-tuples).
    # ``cache.dispositivos[hw]`` es un tuple de devices, cada device
    # es un tuple de campos (tag, type, hw_type, ...).  El FB hace
    # ``list(devices_tuple)`` para la SPA.
    mock_state.set_devices.assert_called_once_with(
        "disp_ed", [("dev1",), ("dev2",)]
    )
    assert mock_state.dimensiones == fake_cache.n_max
    assert mock_state.excel_cache == fake_cache
    assert mock_state.excel_path == "/fake/path.xlsx"

    # Log de éxito emitido con conteos
    mock_log.success.assert_called_once()
    msg = mock_log.success.call_args[0][0]
    assert "Carga maestra" in msg
    assert "2 dispositivos" in msg


@pytest.mark.asyncio
async def test_subir_excel_sad_no_config(
    mock_state: MagicMock,
    progress: ProgressTracker,
    mock_log: MagicMock,
) -> None:
    """Sin ``config_manager``: el primer tick falla con RuntimeError
    y el wrapper de la base pone el FB en ``n_error`` con ``error_msg``
    que menciona "config_manager".
    """
    fb = make_fb(
        config_manager=None,
        state=mock_state,
        progress=progress,
        log=mock_log,
        loader_factory=MagicMock(),
        cache_cls=MagicMock(),
    )
    await fb.start(xlsx_path="/fake.xlsx")
    assert fb.nStep == 10

    await fb.tick()

    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    assert "config_manager" in fb.error_msg
    assert fb.is_terminal() is True


@pytest.mark.asyncio
async def test_subir_excel_sad_parse_fails(
    mock_config: MagicMock,
    mock_state: MagicMock,
    progress: ProgressTracker,
    mock_log: MagicMock,
) -> None:
    """El loader lanza ``ValueError`` (xlsx corrupto) en nStep=20.

    El FB llega a nStep=20 (pre-flight OK), el segundo tick falla,
    el wrapper pone el FB en ``n_error`` con el mensaje del loader
    en ``error_msg``.  El cache ``put()`` NO se llama.
    """
    def bad_factory(config_manager: ConfigManager) -> MagicMock:
        loader = MagicMock()
        loader.load = MagicMock(side_effect=ValueError("xlsx corrupto"))
        return loader

    cache_cls = MagicMock()
    cache_cls.put = AsyncMock()

    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        bad_factory, cache_cls,
    )
    await fb.start(xlsx_path="/fake/bad.xlsx")

    # Tick #1: pre-flight OK (10 → 20)
    await fb.tick()
    assert fb.nStep == 20

    # Tick #2: parse falla (20 → 98)
    await fb.tick()
    assert fb.nStep == fb.n_error
    assert "xlsx corrupto" in fb.error_msg
    assert fb.is_terminal() is True

    # El cache.put NO se llamó porque loader.load lanzó antes
    cache_cls.put.assert_not_called()


@pytest.mark.asyncio
async def test_subir_excel_terminal_no_avanza_mas(
    mock_config: MagicMock,
    mock_state: MagicMock,
    progress: ProgressTracker,
    mock_log: MagicMock,
    happy_loader_factory,
    mock_cache_cls: MagicMock,
) -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op (guarda de la base)."""
    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        happy_loader_factory, mock_cache_cls,
    )
    await fb.start(xlsx_path="/fake.xlsx")

    # Avanzar al estado done
    await fb.tick()  # 10 → 20
    await fb.tick()  # 20 → 30
    await fb.tick()  # 30 → 99
    assert fb.nStep == fb.n_done

    n_step_before = fb.nStep
    await fb.tick()
    assert fb.nStep == n_step_before  # no avanza
