"""Tests del FB ``FunctionProcDBGenerarPreview``.

Cubre:
  - Happy path: ``execute()`` corre los 6 steps, ``self.result``
    con la shape legacy, helper llamado 1 vez por step, progress stages
    completos.
  - Sad path 1: sin ``config_manager`` -> nStep=98 con ``error_msg``
    mencionando "config_manager".
  - Sad path 2: sin ``tia_client`` -> nStep=98 con ``error_msg``
    mencionando "tia_client".
  - Sad path 3: ``execute()`` sin ``plc_name`` o con valor invalido ->
    ValueError.
  - Sad path 4: ``execute()`` sin ``proc_uid`` o no-int -> ValueError.
  - Guard del base: ``execute()`` sobre un FB activo es no-op.

Mockeamos el helper ``proc_generar_preview`` (sus funciones) para
validar SOLO la state machine del FB (no la logica del helper; eso
tiene su propio test en ``test_proc_generar_preview.py``).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from areas.alimentacion.functions.function_proc_db_generar_preview import (
    FunctionProcDBGenerarPreview,
    ProcPreviewContext,
)
from core.runtime.progress_buffer import ProgressTracker
from core.infrastructure.config.config_manager import ConfigManager


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_config() -> MagicMock:
    return MagicMock(spec=ConfigManager)


@pytest.fixture
def mock_tia_client() -> MagicMock:
    """Gateway mockeado. Los export_* son MagicMock; no se llaman en
    este test porque parcheamos el helper."""
    client = MagicMock()
    # Mock list_plcs para validate_plc_in_tia (PR5).
    client.submit_and_wait = MagicMock(
        return_value={"ok": True, "result": {"plcs": [{"name": "S7-1500"}]}}
    )
    client.export_plc_tags_xml = MagicMock(return_value=None)
    client.export_block = MagicMock(return_value=None)
    return client


@pytest.fixture
def patch_validate_plc_in_excel():
    """Mockea ``validate_plc_in_excel`` para tests que no quieren
    validar contra el Excel (solo validar la state machine del FB).
    """
    with patch(
        "areas.alimentacion.functions.function_proc_db_generar_preview"
        ".validate_plc_in_excel"
    ) as mocked:
        yield mocked


@pytest.fixture
def mock_app_cache() -> MagicMock:
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
    app_cache: MagicMock,
    bloques_cache: MagicMock,
    progress_tracker: ProgressTracker,
) -> FunctionProcDBGenerarPreview:
    return FunctionProcDBGenerarPreview(
        nombre="proc_generar_preview_test",
        config_manager=config,
        tia_client=tia_client,
        app_cache=app_cache,
        bloques_cache=bloques_cache,
        tracker=progress_tracker,
    )


# ── Tests directos de _stage_6_build_response (db_present / table_present) ──


def _make_minimal_slot_map(
    *,
    table_present: bool,
    db_missing: list[str],
) -> MagicMock:
    """Slot map mockeado con los atributos minimos que
    ``_stage_6_build_response`` lee.
    """
    sm = MagicMock()
    sm.db_param_name = "DB3100_CPR1_PARAM"
    sm.db_alm_name = "DB5100_CPR1_ALM"
    sm.table_name = "100_CPR1"
    sm.table_present = table_present
    sm.db_missing = list(db_missing)
    sm.missing_blocks = [
        f"DB de parametros: {n}" for n in db_missing
    ] + ([] if table_present else ["Tabla de variables: 100_CPR1"])
    sm.warnings = []
    return sm


def test_stage_6_build_response_happy_path_flags_presentes(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Happy path (sin DBs ausentes, tabla presente):
    ``db_present={"param": True, "alm": True}`` y ``table_present=True``.
    """
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb._ctx = ProcPreviewContext(
        plc_name="S7-1500",
        proc_uid=42,
        tia_client=mock_tia_client,
        config_manager=mock_config,
        app_cache=mock_app_cache,
        build_cache_root=mock_config.build_cache_root if hasattr(
            mock_config, "build_cache_root"
        ) else None,
        bloques_cache=mock_bloques_cache,
        excel_loaded=True,
        bloques_loaded=True,
        slot_map=_make_minimal_slot_map(table_present=True, db_missing=[]),
        slot_map_error=None,
        nmax_block={},
        preal_current={},
        pint_current={},
        alm_current={},
        export_error=None,
    )

    with patch(
        "areas.alimentacion.functions.function_proc_db_generar_preview"
        ".compose_arrays", return_value={}
    ), patch(
        "areas.alimentacion.functions.function_proc_db_generar_preview"
        ".compute_summary", return_value={
            "total": 0, "agregados": 0, "renombrados": 0,
            "eliminados": 0, "sin_cambios": 0,
        }
    ):
        fb._stage_6_build_response()

    assert fb._ctx.result["db_present"] == {"param": True, "alm": True}
    assert fb._ctx.result["table_present"] is True
    assert fb._ctx.result["precondiciones_ok"] is True


def test_stage_6_build_response_db_param_ausente_marca_solo_param(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Solo DB PARAM ausente (recuperable, no fatal):
    ``db_present={"param": False, "alm": True}``, ``table_present=True``,
    ``precondiciones_ok=True``.
    """
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb._ctx = ProcPreviewContext(
        plc_name="S7-1500",
        proc_uid=42,
        tia_client=mock_tia_client,
        config_manager=mock_config,
        app_cache=mock_app_cache,
        build_cache_root=mock_config.build_cache_root if hasattr(
            mock_config, "build_cache_root"
        ) else None,
        bloques_cache=mock_bloques_cache,
        excel_loaded=True,
        bloques_loaded=True,
        slot_map=_make_minimal_slot_map(
            table_present=True, db_missing=["DB3100_CPR1_PARAM"],
        ),
        slot_map_error=None,
        nmax_block={},
        preal_current={},
        pint_current={},
        alm_current={},
        export_error=None,
    )

    with patch(
        "areas.alimentacion.functions.function_proc_db_generar_preview"
        ".compose_arrays", return_value={}
    ), patch(
        "areas.alimentacion.functions.function_proc_db_generar_preview"
        ".compute_summary", return_value={
            "total": 0, "agregados": 0, "renombrados": 0,
            "eliminados": 0, "sin_cambios": 0,
        }
    ):
        fb._stage_6_build_response()

    assert fb._ctx.result["db_present"] == {"param": False, "alm": True}
    assert fb._ctx.result["table_present"] is True
    assert fb._ctx.result["precondiciones_ok"] is True


def test_stage_6_build_response_ambos_dbs_ausentes_marca_fatal(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Ambos DBs ausentes (fatal): ``db_present={False, False}``,
    ``table_present=True``, ``precondiciones_ok=False``.
    """
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb._ctx = ProcPreviewContext(
        plc_name="S7-1500",
        proc_uid=42,
        tia_client=mock_tia_client,
        config_manager=mock_config,
        app_cache=mock_app_cache,
        build_cache_root=mock_config.build_cache_root if hasattr(
            mock_config, "build_cache_root"
        ) else None,
        bloques_cache=mock_bloques_cache,
        excel_loaded=True,
        bloques_loaded=True,
        slot_map=_make_minimal_slot_map(
            table_present=True,
            db_missing=["DB3100_CPR1_PARAM", "DB5100_CPR1_ALM"],
        ),
        slot_map_error=None,
        nmax_block={},
        preal_current={},
        pint_current={},
        alm_current={},
        export_error=None,
    )

    fb._stage_6_build_response()

    assert fb._ctx.result["db_present"] == {"param": False, "alm": False}
    assert fb._ctx.result["table_present"] is True
    assert fb._ctx.result["precondiciones_ok"] is False
    assert fb._ctx.result["arrays"] == {}


def test_stage_6_build_response_tabla_ausente_marca_solo_tabla(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Tabla ausente (fatal, sin importar DBs):
    ``table_present=False``, ``db_present`` refleja solo los DBs que
    falten (en este test ambos presentes).
    """
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb._ctx = ProcPreviewContext(
        plc_name="S7-1500",
        proc_uid=42,
        tia_client=mock_tia_client,
        config_manager=mock_config,
        app_cache=mock_app_cache,
        build_cache_root=mock_config.build_cache_root if hasattr(
            mock_config, "build_cache_root"
        ) else None,
        bloques_cache=mock_bloques_cache,
        excel_loaded=True,
        bloques_loaded=True,
        slot_map=_make_minimal_slot_map(
            table_present=False, db_missing=[],
        ),
        slot_map_error=None,
        nmax_block={},
        preal_current={},
        pint_current={},
        alm_current={},
        export_error=None,
    )

    fb._stage_6_build_response()

    assert fb._ctx.result["db_present"] == {"param": True, "alm": True}
    assert fb._ctx.result["table_present"] is False
    assert fb._ctx.result["precondiciones_ok"] is False
    assert fb._ctx.result["arrays"] == {}


# ── Helper / fixture para tests de state machine ─────────────────────


def _patch_helper_fns(fb) -> Any:
    """Helper: parchea todas las funciones del FB para que sean no-op.

    Devuelve un context manager compuesto que podemos usar con ``with``.
    Cada funcion del FB se reemplaza por un mock vacio (sync, como el
    FB ya convertido). ``proc_compose_response`` se reemplaza
    por un MagicMock que el test puede sobreescribir.
    """
    from contextlib import ExitStack
    stack = ExitStack()
    # ``with_plc`` opera sobre ``state.app_cache`` (dataclass frozen
    # con ``excel_full_by_area``). En estos tests mockeamos el state
    # entero (MagicMock), asi que parchamos el helper para evitar el
    # path de filtro.
    stack.enter_context(
        patch(
            "areas.alimentacion.functions.function_proc_db_generar_preview"
            ".with_plc"
        )
    )
    stack.enter_context(
        patch.object(fb, "_stage_1_check_state", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_2_check_blocks", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_3_build_slot_maps", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_4_compute_nmax", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_5_export_and_diff", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_6_build_response", MagicMock(), create=True)
    )
    return stack


# ── Happy path ──────────────────────────────────────────────────────


def test_proc_generar_preview_happy_path_6_ticks(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    patch_validate_plc_in_excel: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Happy path: ``execute()`` -> nStep=99, todas las funciones del helper
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
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    with _patch_helper_fns(fb) as stack:
        # Sobre-escribimos _stage_6_build_response con nuestra version.
        stack.enter_context(
            patch.object(
                fb, "_stage_6_build_response",
                side_effect=fake_compose, create=True,
            )
        )

        result = fb.execute(plc_name="S7-1500", proc_uid=42)

        assert fb.nStep == fb.n_done
        assert fb.is_terminal() is True
        assert fb.error_msg is None
        assert fb.result is not None
        assert result is fb.result
        assert fb.result["precondiciones_ok"] is True
        assert fb.result["proc_uid"] == 42
        assert fb.result["db_param_name"] == "DB42_CPR_PARAM"

        # Cada helper fue llamado 1 vez (los MagicMock auto-trackean).
        assert fb._stage_1_check_state.call_count == 1
        assert fb._stage_2_check_blocks.call_count == 1
        assert fb._stage_3_build_slot_maps.call_count == 1
        assert fb._stage_4_compute_nmax.call_count == 1
        assert fb._stage_5_export_and_diff.call_count == 1
        assert fb._stage_6_build_response.call_count == 1


# ── Sad paths (pre-flight) ───────────────────────────────────────────


def test_proc_generar_preview_sad_no_config(
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Sin ``config_manager`` -> ``execute()`` falla con "config_manager"."""
    fb = FunctionProcDBGenerarPreview(
        nombre="no_config_test",
        config_manager=None,
        tia_client=mock_tia_client,
        app_cache=mock_app_cache,
        bloques_cache=mock_bloques_cache,
        tracker=progress,
    )
    fb.execute(plc_name="S7-1500", proc_uid=42)

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "config_manager" in fb.error_msg


def test_proc_generar_preview_sad_no_tia_client(
    mock_config: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Sin ``tia_client`` -> ``execute()`` falla con "tia_client"."""
    fb = FunctionProcDBGenerarPreview(
        nombre="no_tia_test",
        config_manager=mock_config,
        tia_client=None,
        app_cache=mock_app_cache,
        bloques_cache=mock_bloques_cache,
        tracker=progress,
    )
    fb.execute(plc_name="S7-1500", proc_uid=42)

    assert fb.nStep == fb.n_error
    assert "tia_client" in fb.error_msg


def test_proc_generar_preview_sad_no_plc_name(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """``execute()`` sin ``plc_name`` -> falla con ValueError."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb.execute(proc_uid=42)  # sin plc_name

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "plc_name" in fb.error_msg


def test_proc_generar_preview_sad_no_proc_uid(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """``execute()`` sin ``proc_uid`` -> falla con ValueError."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb.execute(plc_name="S7-1500")  # sin proc_uid

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "proc_uid" in fb.error_msg


def test_proc_generar_preview_sad_proc_uid_not_int(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """``execute()`` con ``proc_uid`` no-int -> falla con ValueError."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb.execute(plc_name="S7-1500", proc_uid="42")  # string, no int

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "proc_uid" in fb.error_msg


# ── Terminal ─────────────────────────────────────────────────────────


def test_proc_generar_preview_activo_execute_ignorado(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Con el FB activo, ``execute()`` no hace nada (guarda de la base).

    En el camino sync no hay ``tick()``: el guard equivalente es el
    ``execute()`` ignorado cuando el FB ya esta en curso. Un FB en
    estado terminal, en cambio, se re-arranca (el base lo documenta:
    el FB es reusable).
    """
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    # Forzar estado activo (20) sin esperar el ciclo completo.
    fb.nStep = fb.n_ejecutar
    n_step_before = fb.nStep

    with _patch_helper_fns(fb):
        fb.execute(plc_name="S7-1500", proc_uid=42)

        assert fb.nStep == n_step_before  # no avanza
        assert fb.result is None
        assert fb._stage_1_check_state.call_count == 0
