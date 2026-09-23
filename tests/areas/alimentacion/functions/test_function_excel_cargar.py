"""Tests del FB ``FunctionExcelCargar``.

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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from areas.alimentacion.functions.function_excel_cargar import FunctionExcelCargar
from core.runtime.log_buffer import LogBuffer
from core.runtime.progress_buffer import ProgressTracker
from core.runtime.app_state import AppState
from core.infrastructure.config.config_manager import ConfigManager


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

    Stages alineados con los nombres de ``STAGES`` del FB
    (en lenguaje humano, ver F11).
    """
    real_progress.begin(
        operation="subir_excel_test",
        label="Subir Excel (test)",
        stages=["Parsear Excel", "Volcar a estado de aplicación"],
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
) -> FunctionExcelCargar:
    return FunctionExcelCargar(
        nombre="subir_excel_test",
        config_manager=config_manager,
        app_state=state,
        tracker=progress,
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
    """Happy path: start + 4 ticks → nStep=n_done (99).

    State machine real (ver ``plc_function_base.py`` docstring):
      nStep=10 (arrancar) → 20 (ejecutar, primer tick pre-flight)
        → 20 (sigue ejecutando stages, _step_idx avanza por su cuenta)
        → 95 (finalizar, cuando _step_idx >= len(steps))
        → 99 (done, terminal).
    El FB tiene 2 stages (parsear + volcar), asi que hacen falta
    start + 4 ticks para llegar a n_done (incluyendo el tick de
    finalizar que mueve de 95 a 99).
    """
    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        happy_loader_factory, mock_cache_cls,
    )

    ok = await fb.start(xlsx_path="/fake/path.xlsx")
    assert ok is True
    assert fb.nStep == 10  # arrancar

    # Patch: el FB recupera el cache global en stage 2 via
    # ``ExcelCacheManager.get``. El ``parse_excel_to_cache`` real lo
    # pone ahi, pero en el test mockeamos ``put`` directamente.
    # Tambien parchamos ``on_finish`` que lee ``ExcelCacheManager._cache``
    # (atributo de clase directo, no via ``get``).
    from areas.alimentacion.helpers.excel import excel_cache_manager
    original_cache = excel_cache_manager.ExcelCacheManager._cache
    excel_cache_manager.ExcelCacheManager._cache = fake_cache
    try:
        with patch(
            "areas.alimentacion.helpers.excel.excel_cache_manager.ExcelCacheManager.get",
            new=AsyncMock(return_value=fake_cache),
        ):
            # Tick #1: pre-flight (10 → 20)
            await fb.tick()
            assert fb.nStep == 20

            # Tick #2: ejecuta stage 0 (parsear) — nStep se queda en 20
            # mientras _step_idx < len(steps).
            await fb.tick()
            assert fb.nStep == 20
            mock_cache_cls.put.assert_awaited_once_with(fake_cache)

            # Tick #3: ejecuta stage 1 (volcar) — _step_idx == len(steps)
            # asi que transiciona a 95 (finalizar).
            await fb.tick()
            assert fb.nStep == 95

            # Tick #4: ejecutar ``_step_finalizar`` (on_finish + finish tracker).
            await fb.tick()
            assert fb.nStep == fb.n_done  # 99
            assert fb.is_terminal() is True
            assert fb.error_msg is None

            # Result con la shape actual del FB.
            assert fb.result == {
                "ok": True,
                "summary": {"DispED": 2},
                "total_dispositivos": 2,
                "dimensiones": {"max1": 10},
                "software": {
                    "procesos": 0,
                    "preal": 0,
                    "pint": 0,
                    "alarmas": 0,
                    "n_max_total": 1,
                },
            }
    finally:
        excel_cache_manager.ExcelCacheManager._cache = original_cache

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


@pytest.mark.asyncio
async def test_subir_excel_sad_no_config(
    mock_state: MagicMock,
    progress: ProgressTracker,
    mock_log: MagicMock,
) -> None:
    """Sin ``config_manager``: el primer stage falla con RuntimeError
    y el wrapper de la base pone el FB en ``n_error`` con ``error_msg``
    que menciona "config_manager".

    State machine: tick #1 ejecuta el pre-flight (10→20), tick #2
    ejecuta el primer stage que falla por falta de config.
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

    # Tick #1: pre-flight (10 → 20)
    await fb.tick()
    assert fb.nStep == 20

    # Tick #2: ejecuta stage 0 → RuntimeError → n_error
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
    fake_cache: MagicMock,
) -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op (guarda de la base)."""
    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        happy_loader_factory, mock_cache_cls,
    )
    await fb.start(xlsx_path="/fake.xlsx")

    # Mismo patch que el happy path: stage 2 y on_finish leen
    # ``ExcelCacheManager._cache`` (atributo de clase).
    from areas.alimentacion.helpers.excel import excel_cache_manager
    original_cache = excel_cache_manager.ExcelCacheManager._cache
    excel_cache_manager.ExcelCacheManager._cache = fake_cache
    try:
        # Avanzar al estado done: start + 4 ticks.
        await fb.tick()  # 10 → 20 (pre-flight)
        await fb.tick()  # ejecuta stage 0 (parsear)
        await fb.tick()  # ejecuta stage 1 (volcar) → 95 (finalizar)
        await fb.tick()  # ejecuta _step_finalizar → 99 (done)
        assert fb.nStep == fb.n_done

        n_step_before = fb.nStep
        await fb.tick()
        assert fb.nStep == n_step_before  # no avanza
    finally:
        excel_cache_manager.ExcelCacheManager._cache = original_cache
