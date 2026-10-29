"""Tests del FB ``FunctionExcelCargar``.

Camino sync: el FB se conduce con ``fb.execute(**params)``, una sola
llamada que recorre la state machine completa (10→20→95→99).

Cubren:
  - Happy path: ``execute()`` avanza 10→20→95→99 (``n_done``),
    ``self.result`` con la shape multi-PLC, ``AppCache`` con
    ``excel_full`` y ``excel_active`` poblados.
  - Sad path 1: sin ``config_manager`` → nStep=98 (``n_error``) con
    ``error_msg`` mencionando "config_manager".
  - Sad path 2: el loader lanza ``ValueError`` (xlsx corrupto) →
    nStep=98 con ``error_msg`` conteniendo el mensaje original.
  - Estado terminal: un ``execute()`` extra sobre ``n_done`` deja el FB
    terminal en ``n_done``.
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

    Stages alineados con el STAGES del FB (1 unico step).
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
        # ``.load`` es sync y el FB lo llama directamente (no hay
        # event loop ni hilo extra).
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


def test_subir_excel_happy_path_3_ticks(
    mock_config: MagicMock,
    mock_state: AppCache,
    progress: ProgressTracker,
    mock_log: MagicMock,
    happy_loader_factory,
    fake_cache: MagicMock,
) -> None:
    """Happy path: ``execute()`` → nStep=n_done (99).

    State machine real (ver ``plc_function_base.py`` docstring):
      nStep=10 (arrancar) → 20 (ejecutar) → 95 (finalizar) → 99 (done).
    En el camino sync una sola llamada las recorre todas; las
    transiciones se capturan con el hook ``_on_nstep_change``.
    """
    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        happy_loader_factory,
    )
    transiciones: list[int] = []
    fb._on_nstep_change = lambda _old, new: transiciones.append(new)

    fb.execute(xlsx_path="/fake/path.xlsx")

    assert transiciones == [
        fb.n_arrancar, fb.n_ejecutar, fb.n_finalizar, fb.n_done,
    ]
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


def test_subir_excel_sad_no_config(
    mock_state: AppCache,
    progress: ProgressTracker,
    mock_log: MagicMock,
) -> None:
    """Sin ``config_manager``: el primer stage falla con RuntimeError
    y el wrapper de la base pone el FB en ``n_error`` con ``error_msg``
    que menciona "config_manager".

    ``execute()`` captura la excepcion de runtime (no la propaga): el
    FB queda en ``n_error`` con el mensaje en ``error_msg``.
    """
    fb = make_fb(
        config_manager=None,
        state=mock_state,
        progress=progress,
        log=mock_log,
        loader_factory=MagicMock(),
    )
    fb.execute(xlsx_path="/fake.xlsx")

    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    assert "config_manager" in fb.error_msg
    assert fb.is_terminal() is True


def test_subir_excel_sad_parse_fails(
    mock_config: MagicMock,
    mock_state: AppCache,
    progress: ProgressTracker,
    mock_log: MagicMock,
) -> None:
    """El loader lanza ``ValueError`` (xlsx corrupto) al parsear.

    ``execute()`` captura la excepcion de runtime y deja el FB en
    ``n_error`` con el mensaje del loader en ``error_msg``. El cache de
    ``AppCache`` NO se escribe.
    """
    def bad_factory(config_manager: ConfigManager) -> MagicMock:
        loader = MagicMock()
        loader.load = MagicMock(side_effect=ValueError("xlsx corrupto"))
        return loader

    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        bad_factory,
    )
    fb.execute(xlsx_path="/fake/bad.xlsx")

    assert fb.nStep == fb.n_error
    assert "xlsx corrupto" in fb.error_msg
    assert fb.is_terminal() is True

    # El AppCache queda vacio porque loader.load lanzó antes de la
    # escritura via ``excel_set_full``.
    from core.runtime.excel_cache import excel_get_full
    assert excel_get_full(mock_state, "alimentacion") is None


def test_subir_excel_terminal_no_avanza_mas(
    mock_config: MagicMock,
    mock_state: AppCache,
    progress: ProgressTracker,
    mock_log: MagicMock,
    happy_loader_factory,
) -> None:
    """En ``n_done`` el FB queda terminal; un ``execute()`` extra lo
    re-ejecuta y vuelve a ``n_done`` (no queda en estado activo).
    """
    fb = make_fb(
        mock_config, mock_state, progress, mock_log,
        happy_loader_factory,
    )
    fb.execute(xlsx_path="/fake.xlsx")
    assert fb.nStep == fb.n_done

    n_step_before = fb.nStep
    fb.execute(xlsx_path="/fake.xlsx")
    assert fb.nStep == n_step_before  # sigue terminal en n_done
    assert fb.is_terminal() is True