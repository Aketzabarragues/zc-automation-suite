"""Tests del FB ``FunctionProcDBSincronizar``.

Cubre:
  - Happy path: ``execute()`` (camino sync: on_start + 9 steps +
    on_finish) -> nStep=99, ``self.result`` con la shape legacy, helper
    llamado 1 vez por step.
  - Sad path 1: sin ``config_manager`` -> nStep=98 con "config_manager".
  - Sad path 2: sin ``tia_client`` -> nStep=98 con "tia_client".
  - Sad path 3: ``execute()`` sin ``plc_name`` -> nStep=98.
  - Sad path 4: ``execute()`` sin ``proc_uid`` -> nStep=98.
  - Sad path 5: helper ``proc_check_state_commit`` reporta excel no
    cargado -> primer step ejecutivo falla con RuntimeError.
  - Sad path 6: helper ``proc_build_slot_maps_commit`` reporta
    missing_blocks -> tercer step ejecutivo falla con RuntimeError.
  - Estado terminal: una llamada extra del driver no avanza el FB.

Mockeamos el helper ``proc_sincronizar`` (sus funciones) para validar
SOLO la state machine del FB (no la logica del helper; eso tiene su
propio test en ``test_proc_sincronizar.py``).
"""
from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from areas.alimentacion.functions.function_proc_db_sincronizar import (
    FunctionProcDBSincronizar,
)
from core.runtime.progress_buffer import ProgressTracker
from core.infrastructure.config.config_manager import ConfigManager


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_config() -> MagicMock:
    return MagicMock(spec=ConfigManager)


@pytest.fixture
def mock_tia_client() -> MagicMock:
    client = MagicMock()
    client.execute_transactional_batch = MagicMock(
        return_value={"operations_executed": 2, "details": []}
    )
    # Mock list_plcs para validate_plc_in_tia.
    client.submit_and_wait = MagicMock(
        return_value={"ok": True, "result": {"plcs": [{"name": "S7-1500"}]}}
    )
    return client


@pytest.fixture
def patch_validate_plc_in_excel():
    """Mockea ``validate_plc_in_excel`` para los tests del FB que no
    quieren validar contra el Excel (solo validar la state machine).

    Parcheamos el helper a no-op para que los tests se enfoquen solo
    en la logica del FB.
    """
    with patch(
        "areas.alimentacion.functions.function_proc_db_sincronizar"
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
    real_progress.begin(
        operation="proc_sincronizar_test",
        label="Sincronizar comentarios del proceso (test)",
        stages=[
            "check_state_commit", "check_blocks_commit",
            "build_slot_maps_commit", "sync_nmax",
            "wait_consolidation", "compile_proc_blocks",
            "open_transaction", "done",
        ],
    )
    return real_progress


def make_fb(
    config: MagicMock,
    tia_client: MagicMock,
    app_cache: MagicMock,
    bloques_cache: MagicMock,
    progress_tracker: ProgressTracker,
) -> FunctionProcDBSincronizar:
    return FunctionProcDBSincronizar(
        nombre="proc_sincronizar_test",
        config_manager=config,
        tia_client=tia_client,
        app_cache=app_cache,
        bloques_cache=bloques_cache,
        tracker=progress_tracker,
    )


def _patch_helper_fns_except_stage_3(fb) -> ExitStack:
    """Parchea todos los stages MENOS ``_stage_3_construir_mapa_de_slots``.

    Usado por los tests del stage 3 que quieren ejecutar el codigo
    real del stage (con ``proc_build_slot_maps`` mockeado).
    """
    stack = ExitStack()
    stack.enter_context(
        patch(
            "areas.alimentacion.functions.function_proc_db_sincronizar"
            ".with_plc"
        )
    )
    stack.enter_context(
        patch.object(fb, "_stage_1_validar_estado_de_tia", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_2_validar_bloques", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_4_aplicar_n_max", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_5_esperar_consolidacion_tia", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_6_compilar_bloques", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_7_abrir_transaccion_tia", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_8_generar_preview_post_sincronizacion", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_9_componer_respuesta", MagicMock(), create=True)
    )
    return stack


def _patch_helper_fns(fb) -> ExitStack:
    stack = ExitStack()
    # ``with_plc`` opera sobre ``state.app_cache`` (dataclass frozen
    # con ``excel_full_by_area``). En estos tests mockeamos el state
    # entero (MagicMock), asi que parchamos el helper para evitar el
    # path de filtro.
    stack.enter_context(
        patch(
            "areas.alimentacion.functions.function_proc_db_sincronizar"
            ".with_plc"
        )
    )
    stack.enter_context(
        patch.object(fb, "_stage_1_validar_estado_de_tia", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_2_validar_bloques", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_3_construir_mapa_de_slots", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_4_aplicar_n_max", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_5_esperar_consolidacion_tia", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_6_compilar_bloques", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_7_abrir_transaccion_tia", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_8_generar_preview_post_sincronizacion", MagicMock(), create=True)
    )
    stack.enter_context(
        patch.object(fb, "_stage_9_componer_respuesta", MagicMock(), create=True)
    )
    return stack


# ── Happy path ──────────────────────────────────────────────────────


def test_proc_sincronizar_happy_path_8_ticks(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    patch_validate_plc_in_excel: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Happy path: ``execute()`` -> nStep=99, todas las funciones del helper
    llamadas una vez, ``self.result`` con la shape legacy.

    Camino sync: ``execute()`` corre el FB entero (on_start + 9 steps +
    on_finish) en una sola llamada y devuelve ``self.result``.
    """
    fake_result = {
        "proc_uid": 42,
        "plc_name": "S7-1500",
        "success": True,
        "applied": True,
        "operations_executed": 2,
        "details": [
            {"command": "update_proc_comments_db_param", "ok": True},
            {"command": "update_proc_comments_db_alm", "ok": True},
        ],
        "warnings": [],
    }

    def fake_done_summary() -> None:
        # El dispatcher del FB llama los stages sin args.
        fb._ctx.result = dict(fake_result)

    fake_slot_map = MagicMock()
    fake_slot_map.missing_blocks = []
    fake_slot_map.preal = {1: "Bomba 1"}
    fake_slot_map.pint = {1: "Param 1"}
    fake_slot_map.alm = {1: "Alarma 1"}
    fake_slot_map.warnings = []

    def fake_build_slot_maps() -> None:
        # El dispatcher del FB llama los stages sin args
        # (handler(), no handler(ctx)).
        fb._ctx.slot_map = fake_slot_map

    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    with _patch_helper_fns(fb) as stack:
        # Sobre-escribimos ``_stage_3_construir_mapa_de_slots`` y
        # ``_stage_9_componer_respuesta``.
        stack.enter_context(
            patch.object(
                fb, "_stage_3_construir_mapa_de_slots",
                side_effect=fake_build_slot_maps, create=True,
            )
        )
        stack.enter_context(
            patch.object(
                fb, "_stage_9_componer_respuesta",
                side_effect=fake_done_summary, create=True,
            )
        )


        result = fb.execute(plc_name="S7-1500", proc_uid=42)

        assert fb.nStep == fb.n_done
        assert result is fb.result
        assert fb.is_terminal() is True
        assert fb.error_msg is None
        assert fb.result is not None
        assert fb.result["success"] is True
        assert fb.result["operations_executed"] == 2
        assert fb.result["plc_name"] == "S7-1500"
        assert fb.result["proc_uid"] == 42

        # Cada helper fue llamado 1 vez.
        assert fb._stage_1_validar_estado_de_tia.call_count == 1
        assert fb._stage_2_validar_bloques.call_count == 1
        assert fb._stage_3_construir_mapa_de_slots.call_count == 1
        assert fb._stage_4_aplicar_n_max.call_count == 1
        assert fb._stage_5_esperar_consolidacion_tia.call_count == 1
        assert fb._stage_6_compilar_bloques.call_count == 1
        assert fb._stage_7_abrir_transaccion_tia.call_count == 1
        assert fb._stage_8_generar_preview_post_sincronizacion.call_count == 1
        assert fb._stage_9_componer_respuesta.call_count == 1


# ── Sad paths (pre-flight en on_start) ──────────────────────────────


def test_proc_sincronizar_sad_no_config(
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Sin ``config_manager`` -> ``execute()`` deja el FB en n_error."""
    fb = FunctionProcDBSincronizar(
        nombre="no_config_test",
        config_manager=None,
        tia_client=mock_tia_client,
        app_cache=mock_app_cache,
        bloques_cache=mock_bloques_cache,
        tracker=progress,
    )
    fb.execute(plc_name="S7-1500", proc_uid=42)

    assert fb.nStep == fb.n_error
    assert "config_manager" in fb.error_msg


def test_proc_sincronizar_sad_no_tia_client(
    mock_config: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Sin ``tia_client`` -> ``execute()`` deja el FB en n_error."""
    fb = FunctionProcDBSincronizar(
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


def test_proc_sincronizar_sad_no_plc_name(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """``execute()`` sin ``plc_name`` -> el FB queda en n_error."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb.execute(proc_uid=42)

    assert fb.nStep == fb.n_error
    assert "plc_name" in fb.error_msg


def test_proc_sincronizar_sad_no_proc_uid(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """``execute()`` sin ``proc_uid`` -> el FB queda en n_error."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb.execute(plc_name="S7-1500")

    assert fb.nStep == fb.n_error
    assert "proc_uid" in fb.error_msg


# ── Sad paths (en ticks ejecutivos) ────────────────────────────────


def test_proc_sincronizar_sad_check_state_no_excel(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Si helper reporta excel no cargado, el primer step ejecutivo falla."""
    def bad_check_state() -> None:
        # El helper real check_state lanza RuntimeError si el
        # Excel no esta cargado. Simulamos eso.
        raise RuntimeError("Excel no cargado")

    fb = make_fb(
            mock_config, mock_tia_client, mock_app_cache,
            mock_bloques_cache, progress,
        )
    with _patch_helper_fns(fb) as stack:
        stack.enter_context(
            patch.object(
                fb, "_stage_1_validar_estado_de_tia",
                side_effect=bad_check_state, create=True,
            )
        )

        fb.execute(plc_name="S7-1500", proc_uid=42)

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "Excel" in fb.error_msg


def test_proc_sincronizar_sad_missing_blocks(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    patch_validate_plc_in_excel: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Si slot_map.missing_blocks poblado, el tercer step ejecutivo falla."""
    fake_sm = MagicMock()
    fake_sm.missing_blocks = ["DB42_CPR_PARAM no esta en el PLC"]
    fake_sm.preal = {1: "Bomba 1"}
    fake_sm.pint = {1: "Param 1"}
    fake_sm.alm = {1: "Alarma 1"}

    def bad_build_slot_maps() -> None:
        # El helper real build_slot_maps lanza RuntimeError si hay
        # missing_blocks. Simulamos eso.
        raise RuntimeError("Bloques missing: DB42_CPR_PARAM no esta en el PLC")

    fb = make_fb(
            mock_config, mock_tia_client, mock_app_cache,
            mock_bloques_cache, progress,
        )
    with _patch_helper_fns(fb) as stack:
        stack.enter_context(
            patch.object(
                fb, "_stage_3_construir_mapa_de_slots",
                side_effect=bad_build_slot_maps, create=True,
            )
        )

        fb.execute(plc_name="S7-1500", proc_uid=42)

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "missing" in fb.error_msg.lower() or "faltan" in fb.error_msg.lower()


def test_proc_sincronizar_sad_open_transaction_fails(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    patch_validate_plc_in_excel: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Si el gateway falla, el 4º step ejecutivo falla (rollback atomico)."""
    fake_slot_map = MagicMock()
    fake_slot_map.missing_blocks = []
    fake_slot_map.preal = {1: "Bomba 1"}
    fake_slot_map.pint = {1: "Param 1"}
    fake_slot_map.alm = {1: "Alarma 1"}

    def fake_build_slot_maps() -> None:
        # El dispatcher del FB llama los stages sin args
        # (handler(), no handler(ctx)).
        fb._ctx.slot_map = fake_slot_map

    fb = make_fb(
            mock_config, mock_tia_client, mock_app_cache,
            mock_bloques_cache, progress,
        )
    with _patch_helper_fns(fb) as stack:
        stack.enter_context(
            patch.object(
                fb, "_stage_3_construir_mapa_de_slots",
                side_effect=fake_build_slot_maps, create=True,
            )
        )
        stack.enter_context(
            patch.object(
                fb, "_stage_7_abrir_transaccion_tia",
                side_effect=RuntimeError("Bloque DB42_CPR_PARAM no encontrado"),
                create=True,
            )
        )

        fb.execute(plc_name="S7-1500", proc_uid=42)

    assert fb.nStep == fb.n_error
    assert "DB42_CPR_PARAM" in fb.error_msg


# ── Terminal ─────────────────────────────────────────────────────────


def test_proc_sincronizar_terminal_no_avanza_mas(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Una llamada extra del driver no avanza el FB.

    Camino sync: el driver llama a ``execute()``. Con el FB ya activo
    (``n_ejecutar``) la llamada se ignora y ``nStep`` no cambia.
    """
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb.nStep = fb.n_ejecutar
    n_step_before = fb.nStep

    fb.execute(plc_name="S7-1500", proc_uid=42)

    assert fb.nStep == n_step_before
    assert fb.result is None


# ── Stage 3: cobertura de abort / warning segun table_present y db_missing ──


def _make_slot_map(
    table_present: bool,
    db_param_name: str = "DB3000_CPR_PARAM",
    db_alm_name: str = "DB3001_CPR_ALM",
    table_name: str = "100_CPR",
    db_missing: list[str] | None = None,
) -> MagicMock:
    sm = MagicMock()
    sm.table_present = table_present
    sm.db_param_name = db_param_name
    sm.db_alm_name = db_alm_name
    sm.table_name = table_name
    sm.db_missing = list(db_missing) if db_missing is not None else []
    sm.warnings = []
    return sm


def test_stage_3_aborta_si_tabla_ausente(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    patch_validate_plc_in_excel: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """``table_present=False`` -> stage 3 aborta con RuntimeError claro.

    Estrategia: parchear ``proc_build_slot_maps`` en su modulo de
    origen para que retorne un slot_map con ``table_present=False``.
    El stage 3 corre entero y aborta con su mensaje accionable.
    """
    fake_sm = _make_slot_map(table_present=False)

    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    with _patch_helper_fns_except_stage_3(fb), patch(
        "areas.alimentacion.data.data_proc_slot_map.proc_build_slot_maps",
        return_value=fake_sm,
    ):
        fb.execute(plc_name="S7-1500", proc_uid=42)

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "Tabla de variables" in fb.error_msg
    assert "100_CPR" in fb.error_msg


def test_stage_3_aborta_si_ambos_dbs_ausentes(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    patch_validate_plc_in_excel: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Tabla presente + ambos DBs ausentes -> stage 3 aborta con
    RuntimeError claro."""
    fake_sm = _make_slot_map(
        table_present=True,
        db_missing=["DB3000_CPR_PARAM", "DB3001_CPR_ALM"],
    )

    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    with _patch_helper_fns_except_stage_3(fb), patch(
        "areas.alimentacion.data.data_proc_slot_map.proc_build_slot_maps",
        return_value=fake_sm,
    ):
        fb.execute(plc_name="S7-1500", proc_uid=42)

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "no hay nada que aplicar" in fb.error_msg
    assert "DB3000_CPR_PARAM" in fb.error_msg
    assert "DB3001_CPR_ALM" in fb.error_msg


def test_stage_3_sigue_con_un_db_ausente_y_avisa(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    patch_validate_plc_in_excel: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Tabla + DB_PARAM presentes, DB_ALM ausente: stage 3 NO aborta
    y añade el warning del DB omitido a ``slot_map.warnings``."""
    fake_sm = _make_slot_map(
        table_present=True,
        db_missing=["DB3001_CPR_ALM"],
    )

    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    with _patch_helper_fns_except_stage_3(fb), patch(
        "areas.alimentacion.data.data_proc_slot_map.proc_build_slot_maps",
        return_value=fake_sm,
    ), patch.object(
        fb, "_proc_compute_nmax_ops_inline", MagicMock(), create=True,
    ):
        fb.execute(plc_name="S7-1500", proc_uid=42)

    assert fb.nStep == fb.n_done
    assert fb.error_msg is None
    assert any(
        "DB3001_CPR_ALM" in w and "alarmas" in w
        for w in fake_sm.warnings
    )


# ── Filtrado de DBs ausentes en compile y fase 2 de Tx B ──


def test_proc_discover_compile_dbs_omite_db_ausente(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """``_proc_discover_compile_dbs_inline`` excluye los DBs en
    ``slot_map.db_missing``."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb._ctx = MagicMock()
    fb._ctx.slot_map = _make_slot_map(
        table_present=True,
        db_missing=["DB3001_CPR_ALM"],
    )

    result = fb._proc_discover_compile_dbs_inline()

    assert result == ["DB3000_CPR_PARAM"]


def test_proc_discover_compile_dbs_devuelve_vacio_si_todos_ausentes(
    mock_config: MagicMock,
    mock_tia_client: MagicMock,
    mock_app_cache: MagicMock,
    mock_bloques_cache: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Con ambos DBs ausentes, ``_proc_discover_compile_dbs_inline``
    retorna ``[]`` (stage 6 marca ``compile_ok=False`` con su
    mensaje defensivo)."""
    fb = make_fb(
        mock_config, mock_tia_client, mock_app_cache,
        mock_bloques_cache, progress,
    )
    fb._ctx = MagicMock()
    fb._ctx.slot_map = _make_slot_map(
        table_present=True,
        db_missing=["DB3000_CPR_PARAM", "DB3001_CPR_ALM"],
    )

    assert fb._proc_discover_compile_dbs_inline() == []


def test_proc_tx_b_detectar_eliminar_export_filtra_por_db_missing(
    progress: ProgressTracker,
    tmp_path,
) -> None:
    """Fase 2 envia solo el export del DB presente y deja
    ``exports_alm_dir=None`` cuando DB_ALM esta en ``db_missing``.

    ``validate_execute_batch_result`` aborta si una op esperada
    falla, asi que mockeamos ``submit_and_wait`` para devolver un batch
    OK con las ops enviadas. El test verifica la shape de las ops.
    """
    from areas.alimentacion.functions.function_proc_db_sincronizar import (
        _proc_tx_b_detectar_eliminar_export,
        ProcSyncContext,
    )

    bloques_cache = MagicMock()
    bloques_cache.plc_name = "S7-1500"

    slot_map = _make_slot_map(
        table_present=True,
        db_missing=["DB3001_CPR_ALM"],
    )

    ctx = ProcSyncContext(
        plc_name="S7-1500",
        proc_uid=42,
        tia_client=MagicMock(),
        config_manager=MagicMock(),
        app_cache=MagicMock(),
        build_cache_root=MagicMock(),
        bloques_cache=bloques_cache,
    )
    ctx.slot_map = slot_map

    dispatched_ops: list[dict] = []

    def fake_submit_and_wait(command, args=None, timeout=30.0):
        ops = (args or {}).get("operations", [])
        if command == "execute_batch":
            for op in ops:
                dispatched_ops.append(op)
            return {
                "result": {
                    "success": True,
                    "operations_executed": len(ops),
                    "operations_failed": 0,
                    "details": [
                        {"step": i + 1, "command": op["command"], "ok": True}
                        for i, op in enumerate(ops)
                    ],
                },
            }
        return {"ok": True, "result": {}}

    ctx.tia_client.submit_and_wait.side_effect = fake_submit_and_wait

    # ``build_cache`` expone un proceso sync_bloques_export real
    # (Path) para que el operador ``/`` funcione.
    sync_export_root = tmp_path / "exports"
    sync_export_root.mkdir()
    proc_ctx_mock = MagicMock()
    proc_ctx_mock.sync_bloques_export = sync_export_root

    with patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache",
        return_value=MagicMock(procesos=proc_ctx_mock),
    ):
        _proc_tx_b_detectar_eliminar_export(ctx)

    # Solo 1 op: el export de DB_PARAM. DB_ALM esta en db_missing y
    # no se envia al worker.
    assert len(dispatched_ops) == 1
    assert dispatched_ops[0]["command"] == "export_blocks"
    assert (
        dispatched_ops[0]["args"]["block_names"] == ["DB3000_CPR_PARAM"]
    )
    # ctx.exports_param_dir conserva el path; ctx.exports_alm_dir
    # queda None (DB_ALM omitido).
    assert ctx.exports_param_dir is not None
    assert ctx.exports_alm_dir is None


def test_proc_tx_b_detectar_eliminar_export_envuelve_ambos_si_no_falta(
    progress: ProgressTracker,
    tmp_path,
) -> None:
    """Sin db_missing, la fase 2 envia las 2 ops (DB_PARAM + DB_ALM)
    y ambos ``exports_*_dir`` quedan con path."""
    from areas.alimentacion.functions.function_proc_db_sincronizar import (
        _proc_tx_b_detectar_eliminar_export,
        ProcSyncContext,
    )

    bloques_cache = MagicMock()
    bloques_cache.plc_name = "S7-1500"

    slot_map = _make_slot_map(table_present=True, db_missing=[])

    ctx = ProcSyncContext(
        plc_name="S7-1500",
        proc_uid=42,
        tia_client=MagicMock(),
        config_manager=MagicMock(),
        app_cache=MagicMock(),
        build_cache_root=MagicMock(),
        bloques_cache=bloques_cache,
    )
    ctx.slot_map = slot_map

    dispatched_ops: list[dict] = []

    def fake_submit_and_wait(command, args=None, timeout=30.0):
        ops = (args or {}).get("operations", [])
        if command == "execute_batch":
            for op in ops:
                dispatched_ops.append(op)
            return {
                "result": {
                    "success": True,
                    "operations_executed": 2,
                    "operations_failed": 0,
                    "details": [
                        {"step": 1, "command": "export_block", "ok": True},
                        {"step": 2, "command": "export_block", "ok": True},
                    ],
                },
            }
        return {"ok": True, "result": {}}

    ctx.tia_client.submit_and_wait.side_effect = fake_submit_and_wait

    sync_export_root = tmp_path / "exports"
    sync_export_root.mkdir()
    proc_ctx_mock = MagicMock()
    proc_ctx_mock.sync_bloques_export = sync_export_root

    with patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache",
        return_value=MagicMock(procesos=proc_ctx_mock),
    ):
        _proc_tx_b_detectar_eliminar_export(ctx)

    assert len(dispatched_ops) == 2
    assert {op["args"]["block_names"][0] for op in dispatched_ops} == {
        "DB3000_CPR_PARAM",
        "DB3001_CPR_ALM",
    }
    assert ctx.exports_param_dir is not None
    assert ctx.exports_alm_dir is not None

