"""Tests del FB ``FunctionExcelCargar``.

Cubren:
  - Happy path: 3 ticks avanzan 10→20→95→99 (``n_done``),
    ``self.result`` con la shape multi-PLC, ``AppCache`` con
    ``excel_full`` y ``excel_active`` poblados.
  - Sad path 1: sin ``config_manager`` → nStep=98 (``n_error``) con
    ``error_msg`` mencionando "config_manager".
  - Sad path 2: el loader lanza ``ValueError`` (xlsx corrupto) →
    nStep=98 con ``error_msg`` conteniendo el mensaje original.
  - Estado terminal: ticks extra sobre ``n_done`` no avanzan.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from areas.alimentacion.functions.function_excel_cargar import FunctionExcelCargar
from core.runtime.log_buffer import LogBuffer
from core.runtime.progress_buffer import ProgressTracker
from core.runtime.app_cache import AppCache
from core.infrastructure.config.config_manager import ConfigManager


@pytest.fixture(autouse=True)
def _reset_app_singletons():
    """Reset del Singleton ``AppCache`` entre tests.

    Sin reset, el ``register_area("alimentacion", ...)`` de un test
    contamina al siguiente con ``ValueError: area 'alimentacion' ya
    registrada``.
    """
    import core.runtime.app_cache as _cache_mod
    _cache_mod._app_cache = None
    yield
    _cache_mod._app_cache = None


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_config() -> MagicMock:
    """ConfigManager con 1 hw_type activo (``disp_ed``)."""
    cfg = MagicMock(spec=ConfigManager)
    cfg.list_hw_types_active.return_value = ["disp_ed"]
    cfg.get_excel_target_for.return_value = {"canonical": "DispED"}
    return cfg


@pytest.fixture
def mock_state() -> AppCache:
    """AppCache real (no MagicMock): la nueva API escribe via
    ``excel_set_full`` sobre ``app_cache``."""
    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    cache = AppCache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    # ``selected_plc`` = "" -> filtro by_plc cae en rama "sin filtro".
    cache.mutate(
        lambda s: __import__("dataclasses", fromlist=["replace"]).replace(
            s, selected_plc="",
        ),
    )
    return cache


@pytest.fixture
def real_progress() -> ProgressTracker:
    """Tracker real (no mock) para verificar stages emitidos."""
    return ProgressTracker()


@pytest.fixture
def progress(real_progress: ProgressTracker) -> ProgressTracker:
    """Tracker con ``begin()`` ya invocado (mismo contrato que el use
    case legacy asume: el caller hace ``begin()`` antes de ``start()``).

    Stages alineados con el STAGES del FB (1 unico step tras commit 4c).
    """
    real_progress.begin(
        operation="subir_excel_test",
        label="Subir Excel (test)",
        stages=["Parsear y volcar Excel"],
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


def make_fb(
    config_manager: ConfigManager | None,
    state: AppCache,
    progress: ProgressTracker,
    log: MagicMock,
    loader_factory,
) -> FunctionExcelCargar:
    return FunctionExcelCargar(
        nombre="subir_excel_test",
        config_manager=config_manager,
        app_cache=state,
        tracker=progress,
        excel_loader_factory=loader_factory,
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subir_excel_happy_path_3_ticks(
    mock_config: MagicMock,
    mock_state: AppCache,
    progress: ProgressTracker,
    mock_log: MagicMock,
    happy_loader_factory,
    fake_cache: MagicMock,
) -> None:
    """Happy path: start + 3 ticks → nStep=n_done (99).

    State machine real (ver ``plc_function_base.py`` docstring):
      nStep=10 (arrancar) → 20 (ejecutar, primer tick pre-flight)
        → 95 (finalizar, _step_idx >= len(steps) tras el unico stage)
        → 99 (done, terminal).
    El FB tiene 1 stage (parsear + volcar), asi que hacen falta
    start + 3 ticks para llegar a n_done (incluyendo el tick de
    finalizar que mueve de 95 a 99).
    """
    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        happy_loader_factory,
    )

    ok = await fb.start(xlsx_path="/fake/path.xlsx")
    assert ok is True
    assert fb.nStep == 10  # arrancar

    # Tick #1: pre-flight (10 → 20)
    await fb.tick()
    assert fb.nStep == 20

    # Tick #2: ejecuta stage 0 (parsear + volcar) — _step_idx == len(steps)
    # asi que transiciona a 95 (finalizar).
    await fb.tick()
    assert fb.nStep == 95

    # Tick #3: ejecutar ``_step_finalizar`` (on_finish + finish tracker).
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

    # AppCache: cache completo y activo seteados desde el ``fake_cache``
    # via ``excel_set_full`` + ``derive_excel_active``. ``excel_path``
    # vive en el cache mismo.
    from core.runtime.excel_cache import excel_get_active, excel_get_full
    full = excel_get_full(mock_state, "alimentacion")
    active = excel_get_active(mock_state, "alimentacion")
    assert full is fake_cache
    assert active is fake_cache
    assert full.excel_path == "/fake/path.xlsx"


@pytest.mark.asyncio
async def test_subir_excel_sad_no_config(
    mock_state: AppCache,
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
    mock_state: AppCache,
    progress: ProgressTracker,
    mock_log: MagicMock,
) -> None:
    """El loader lanza ``ValueError`` (xlsx corrupto) en nStep=20.

    El FB llega a nStep=20 (pre-flight OK), el segundo tick falla,
    el wrapper pone el FB en ``n_error`` con el mensaje del loader
    en ``error_msg``. El cache de ``AppCache`` NO se escribe.
    """
    def bad_factory(config_manager: ConfigManager) -> MagicMock:
        loader = MagicMock()
        loader.load = MagicMock(side_effect=ValueError("xlsx corrupto"))
        return loader

    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        bad_factory,
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

    # El AppCache queda vacio porque loader.load lanzó antes de la
    # escritura via ``excel_set_full``.
    from core.runtime.excel_cache import excel_get_full
    assert excel_get_full(mock_state, "alimentacion") is None


@pytest.mark.asyncio
async def test_subir_excel_terminal_no_avanza_mas(
    mock_config: MagicMock,
    mock_state: AppState,
    progress: ProgressTracker,
    mock_log: MagicMock,
    happy_loader_factory,
) -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op (guarda de la base)."""
    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        happy_loader_factory,
    )
    await fb.start(xlsx_path="/fake.xlsx")

    # Avanzar al estado done: start + 3 ticks (1 stage + finalizar).
    await fb.tick()  # 10 → 20 (pre-flight)
    await fb.tick()  # ejecuta stage 0 (parsear + volcar) → 95
    await fb.tick()  # ejecuta _step_finalizar → 99 (done)
    assert fb.nStep == fb.n_done

    n_step_before = fb.nStep
    await fb.tick()
    assert fb.nStep == n_step_before  # no avanza