"""Tests del FB entities_sincronizar (D.1: scaffold + ctx + stages 1-2).

Cubre:
  - Validaciones de on_start (deps inyectadas, plc_name).
  - Creacion del EntidadesSyncContext.
  - on_finish con/sin ctx.
  - Steps declarados con ``@step`` (orden de definicion).
  - Stages 1-2 (export + diff) con tia_client y app_state mockeados.
  - Camino sync: ``execute()`` recorre las 11 etapas sin event loop.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_fb(
    *,
    config_manager: MagicMock | None = None,
    tia_client: MagicMock | None = None,
    app_cache: MagicMock | None = None,
) -> "FunctionEntidadesSincronizar":
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )
    return FunctionEntidadesSincronizar(
        config_manager=config_manager or MagicMock(),
        tia_client=tia_client or MagicMock(),
        build_cache=Path("."),
        app_cache=app_cache or MagicMock(),
    )


def test_los_steps_declarados_tienen_11_nombres_unicos() -> None:
    """Los steps declarados con ``@step`` son 11 y con nombres unicos."""
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )
    specs = FunctionEntidadesSincronizar.pasos_declarados()
    assert len(specs) == 11
    nombres = [s.nombre for s in specs]
    assert len(set(nombres)) == 11
    # Las etiquetas visibles que ve el operario, en orden de flujo.
    assert nombres == [
        "Exportar etiquetas y DB",
        "Calcular diferencias",
        "Preparar operaciones",
        "Aplicar NMAX online (Tx A)",
        "Esperar consolidacion TIA",
        "Re-exportar etiquetas y DB",
        "Editar XMLs offline",
        "Aplicar constantes offline (Tx B)",
        "Compilar bloques",
        "Aplicar comentarios offline (Tx C)",
        "Generar preview post-sincronizacion",
    ]


def test_on_start_falla_si_config_manager_es_none() -> None:
    """Sin config_manager, on_start raise RuntimeError claro."""
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )
    fb = FunctionEntidadesSincronizar(
        tia_client=MagicMock(),
        config_manager=None,
    )
    with pytest.raises(RuntimeError, match="config_manager"):
        fb.on_start(plc_name="PLC_X")


def test_on_start_falla_si_tia_client_es_none() -> None:
    """Sin tia_client, on_start raise RuntimeError claro."""
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )
    fb = FunctionEntidadesSincronizar(
        tia_client=None,
        config_manager=MagicMock(),
    )
    with pytest.raises(RuntimeError, match="tia_client"):
        fb.on_start(plc_name="PLC_X")


def test_on_start_falla_si_plc_name_vacio() -> None:
    """Sin plc_name, on_start raise ValueError claro."""
    fb = _make_fb()
    with pytest.raises(ValueError, match="plc_name"):
        fb.on_start(plc_name="")


def test_on_start_crea_ctx_con_deps_inyectadas() -> None:
    """Con deps OK y plc_name, on_start crea el EntidadesSyncContext."""
    fb = _make_fb()
    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_tia"
    ) as v_tia, patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_excel"
    ) as v_excel, patch(
        "areas.alimentacion.functions.function_entidades_sincronizar.with_plc"
    ):
        fb.on_start(plc_name="ZC_PLC_STD")

    v_tia.assert_called_once()
    v_excel.assert_called_once()
    assert fb._ctx is not None
    assert fb._ctx.plc_name == "ZC_PLC_STD"
    assert fb._ctx.db_name == "DB6_ENT"
    assert fb._ctx.tag_table == "6_Entidades"


def test_on_finish_sin_ctx_devuelve_empty_result() -> None:
    """Si on_start fallo, on_finish vuelca shape vacia sin levantar."""
    fb = _make_fb()
    fb.on_finish()
    assert fb.result["success"] is False
    assert fb.result["operations"] == 0
    assert fb.result["n_max_updates"] == 0
    assert fb.result["post_sync_preview"] is None


def test_on_finish_vuelca_ctx_result() -> None:
    """Con ctx inicializado, on_finish vuelca ctx.result + calcula operations."""
    fb = _make_fb()
    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_tia"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_excel"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar.with_plc"
    ):
        fb.on_start(plc_name="ZC_PLC_STD")

    # Simular que stages 3+ poblaron las listas de ops.
    fb._ctx.constant_ops = [{"op": "add", "plc_tag": "ENT_001"}]
    fb._ctx.comment_ops = [{"slot": 1, "comment": "Linea 1"}]
    fb._ctx.nmax_op = {"name": "N_MAX_ENTIDAD", "value": 16}
    fb._ctx.result = {
        "success":           True,
        "message":           "Sincronización completada",
        "operations":        0,  # lo recalcula on_fencion
        "n_max_updates":     0,
        "post_sync_preview": None,
        "compile_ok":        True,
        "compile_error":     None,
        "comments_sync":     {"added": 1, "updated": 0, "unchanged": 0},
    }

    fb.on_finish()
    assert fb.result["success"] is True
    assert fb.result["operations"] == 3  # 1 const + 1 comment + 1 nmax


def test_el_fb_no_declara_run_step() -> None:
    """El dispatch lo hace el motor: el FB no define ``run_step``."""
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )
    assert "run_step" not in vars(FunctionEntidadesSincronizar)


def test_cada_step_declarado_tiene_handler_en_el_fb() -> None:
    """Cada step declarado apunta a un metodo que el FB expone."""
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )
    fb = _make_fb()
    specs = FunctionEntidadesSincronizar.pasos_declarados()
    assert len(specs) == len(fb.steps)
    for idx, spec in enumerate(specs):
        assert fb.steps[idx]["nombre"] == spec.nombre
        assert fb.steps[idx]["handler"] == spec.metodo
        assert hasattr(fb, spec.metodo)


def test_el_dispatch_del_motor_invoca_el_handler_del_step() -> None:
    """El motor invoca el handler declarado y usa su retorno como detail."""
    fb = _make_fb()
    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_tia"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_excel"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar.with_plc"
    ):
        fb.on_start(plc_name="ZC_PLC_STD")

    assert fb.steps[0]["handler"] == "_stage_1_exportar_etiquetas_y_db"

    handler = MagicMock(return_value="Exportar etiquetas y DB: OK")
    fb._stage_1_exportar_etiquetas_y_db = handler  # type: ignore[method-assign]

    detail = fb._invoke_step_sync(0)

    handler.assert_called_once()
    assert detail == "Exportar etiquetas y DB: OK"


def test_stage_1_exportar_etiquetas_y_db_llama_submit_and_wait_2_veces() -> None:
    """Stage 1 llama submit_and_wait 2 veces (export_tables + export_blocks)."""
    fb = _make_fb()
    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_tia"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_excel"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar.with_plc"
    ):
        fb.on_start(plc_name="ZC_PLC_STD")

    # Mockear submit_and_wait para que devuelva dicts no-None.
    with patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache"
    ) as build_cache_mock:
        # Mock del EntidadesLayout que devuelve paths.
        layout = MagicMock()
        layout.sync_variables_export = Path(".") / "sync" / "variables" / "export"
        layout.sync_variables_modified = Path(".") / "sync" / "variables" / "modified"
        layout.sync_bloques_export = Path(".") / "sync" / "bloques" / "export"
        layout.sync_bloques_modified = Path(".") / "sync" / "bloques" / "modified"
        layout.clean_sincronizar = MagicMock()
        ent_ctx = MagicMock()
        ent_ctx.sync_variables_export = layout.sync_variables_export
        ent_ctx.sync_variables_modified = layout.sync_variables_modified
        ent_ctx.sync_bloques_export = layout.sync_bloques_export
        ent_ctx.sync_bloques_modified = layout.sync_bloques_modified
        build_cache_mock.return_value.entidades = ent_ctx

        # Mock de config_manager.get_entidades_config()
        fb._ctx.config_manager.get_entidades_config.return_value = {
            "db_name": "DB6_ENT",
            "db_array_name": "ENT",
            "tag_table": "6_Entidades",
            "config_table": "0_Config_Generales",
        }
        # Stage 1 exporta con subcarpeta TIA. Mockeamos los getters
        # de los folders.
        fb._ctx.config_manager.get_tia_folder_entidades_tags.return_value = (
            "6_Entidades"
        )
        fb._ctx.config_manager.get_tia_folder_entidades_config.return_value = (
            "0_Sistema"
        )

        fb._ctx.tia_client.submit_and_wait.return_value = {"ok": True, "files": []}
        detail = fb._stage_1_exportar_etiquetas_y_db()

    assert detail.startswith("Exportar etiquetas y DB:")
    dispatch_mock = fb._ctx.tia_client.submit_and_wait
    assert dispatch_mock.call_count == 2
    # Primer call: export_tables.
    call1 = dispatch_mock.call_args_list[0]
    assert call1.args[0] == "export_tables"
    assert "0_Config_Generales" in call1.args[1]["table_names"]
    # keep_folder_structure=True (mirror Disp): TIA V21 matchea el
    # import recursivo por subpath TIA. Sin esto, el modified queda
    # FLAT y TIA no encuentra la ruta esperada al re-importar.
    assert call1.args[1]["keep_folder_structure"] is True
    # Segundo call: export_blocks.
    call2 = dispatch_mock.call_args_list[1]
    assert call2.args[0] == "export_blocks"
    assert call2.args[1]["block_names"] == ["DB6_ENT"]


def test_stage_1_exportar_etiquetas_y_db_si_worker_falla_sigue_con_warnings() -> None:
    """Si submit_and_wait retorna None (worker TIA falla), stage 1 emite
    warning y continua (degradacion graciosa)."""
    fb = _make_fb()
    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_tia"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_excel"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar.with_plc"
    ):
        fb.on_start(plc_name="ZC_PLC_STD")

    with patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache"
    ) as build_cache_mock:
        ent_ctx = MagicMock()
        ent_ctx.sync_variables_export = Path("sync_vars_export")
        ent_ctx.sync_variables_modified = Path("sync_vars_modified")
        ent_ctx.sync_bloques_export = Path("sync_bloques_export")
        ent_ctx.sync_bloques_modified = Path("sync_bloques_modified")
        ent_ctx.clean_sincronizar = MagicMock()
        build_cache_mock.return_value.entidades = ent_ctx

        fb._ctx.config_manager.get_entidades_config.return_value = {
            "db_name": "DB6_ENT",
            "db_array_name": "ENT",
            "tag_table": "6_Entidades",
            "config_table": "0_Config_Generales",
        }

        fb._ctx.tia_client.submit_and_wait.return_value = None
        detail = fb._stage_1_exportar_etiquetas_y_db()

    assert detail.startswith("Exportar etiquetas y DB:")
    # 2 warnings: 1 por export_tables, 1 por export_blocks.
    assert len(fb._ctx.warnings) == 2
    assert any("export_tables fallo" in w for w in fb._ctx.warnings)
    assert any("export_blocks fallo" in w for w in fb._ctx.warnings)


def test_stage_2_calcular_diferencias_llama_helpers_de_preview() -> None:
    """Stage 2 reusa compute_diff_entities + compute_nmax_diff_entidades +
    compute_comments_diff."""
    fb = _make_fb()
    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_tia"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_excel"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar.with_plc"
    ):
        fb.on_start(plc_name="ZC_PLC_STD")

    # Inyectar workdirs minimos para que stage 2 no falle por paths vacios.
    sync_vars_export = Path("sync_vars_export")
    sync_bloques_export = Path("sync_bloques_export")
    fb._ctx.sync_variables_export = sync_vars_export
    fb._ctx.sync_bloques_export = sync_bloques_export

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar.get_entidades",
        return_value=[],
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar.get_nmax_entidades",
        return_value={"N_MAX_ENTIDAD": 16},
    ), patch(
        "areas.alimentacion.helpers.entidades.entidades_generate_preview"
        ".compute_diff_entities",
        return_value=MagicMock(
            base={}, base_comments={}, desired={}, added=[], removed=[],
            renamed={}, missing_xml=False, ops=[],
        ),
    ) as cd, patch(
        "areas.alimentacion.helpers.entidades.entidades_generate_preview"
        ".compute_nmax_diff_entidades",
        return_value=MagicMock(
            current={"N_MAX_ENTIDAD": 10}, desired={"N_MAX_ENTIDAD": 16},
            todos=[], summary={"actualizar": 1, "sin_cambios": 0},
            nmax_error=None,
        ),
    ) as cnm, patch(
        "areas.alimentacion.helpers.entidades.entidades_generate_preview"
        ".compute_comments_diff",
        return_value=MagicMock(
            slots_tia=set(), current={}, desired={},
            added=[], removed=[], updated=[], unchanged=[], missing_xml=False,
        ),
    ) as cc, patch(
        "core.infrastructure.tia.tia_export_paths.SdPair",
    ) as sdpair:
        sdpair.return_value.dcl.exists.return_value = False
        sdpair.return_value.res.exists.return_value = False

        detail = fb._stage_2_calcular_diferencias()

    assert detail.startswith("Calcular diferencias:")
    assert cd.called
    assert cnm.called
    assert cc.called
    assert fb._ctx.entities_ops == []
    assert fb._ctx.entities_block["missing_xml"] is False
    assert fb._ctx.nmax_block["summary"]["actualizar"] == 1


def test_entidades_sync_context_defaults() -> None:
    """EntidadesSyncContext tiene defaults razonables para deps comunes."""
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        EntidadesSyncContext,
    )
    ctx = EntidadesSyncContext(
        plc_name="X",
        tia_client=MagicMock(),
        config_manager=MagicMock(),
        app_cache=MagicMock(),
        build_cache_root=Path("."),
    )
    assert ctx.db_name == "DB6_ENT"
    assert ctx.db_array_name == "ENT"
    assert ctx.tag_table == "6_Entidades"
    assert ctx.config_table == "0_Config_Generales"
    assert ctx.constant_ops == []
    assert ctx.comment_ops == []
    assert ctx.warnings == []
    assert ctx.compile_ok is True
    assert ctx.post_sync_preview is None


def test_los_steps_declarados_son_sync() -> None:
    """Los steps declarados con ``@step`` son sync (camino OB1)."""
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )
    for spec in FunctionEntidadesSincronizar.pasos_declarados():
        assert not inspect.iscoroutinefunction(
            getattr(FunctionEntidadesSincronizar, spec.metodo)
        ), f"{spec.metodo} debe ser sync"


def test_los_details_de_los_steps_empiezan_con_su_nombre_visible() -> None:
    """Cada step devuelve un detail que empieza por su etiqueta visible.

    El detail lo devuelve el propio step (lo que ve el operario en la
    barra de progreso): la etiqueta visible del step seguida del resumen
    de lo que ha hecho.
    """
    fb = _make_fb()
    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_tia"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_excel"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar.with_plc"
    ):
        fb.on_start(plc_name="ZC_PLC_STD")

    # Steps que no tocan TIA: se pueden ejecutar tal cual.
    detalles = {
        "Preparar operaciones": fb._stage_3_preparar_operaciones(),
        "Aplicar NMAX online (Tx A)": fb._stage_4_aplicar_nmax_online_tx_a(),
        "Esperar consolidacion TIA": fb._stage_5_esperar_consolidacion_tia(),
        "Aplicar constantes offline (Tx B)": (
            fb._stage_8_aplicar_constantes_offline_tx_b()
        ),
        "Compilar bloques": fb._stage_9_compilar_bloques(),
        "Aplicar comentarios offline (Tx C)": (
            fb._stage_10_aplicar_comentarios_offline_tx_c()
        ),
    }
    for nombre, detail in detalles.items():
        assert detail.startswith(f"{nombre}:"), (nombre, detail)


def test_execute_sync_recorre_las_11_etapas() -> None:
    """``execute()`` (camino sync del OB1) recorre las 11 etapas y termina
    en ``n_done`` sin event loop."""
    from core.runtime.progress_buffer import ProgressTracker
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )

    fb = FunctionEntidadesSincronizar(
        config_manager=MagicMock(),
        tia_client=MagicMock(),
        build_cache=Path("."),
        app_cache=MagicMock(),
        tracker=ProgressTracker(),
    )
    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_tia"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".validate_plc_in_excel"
    ), patch(
        "areas.alimentacion.functions.function_entidades_sincronizar.with_plc"
    ):
        # Mockear los 11 handlers: el test verifica el ciclo del
        # state machine, no la logica de cada stage.
        for spec in FunctionEntidadesSincronizar.pasos_declarados():
            setattr(fb, spec.metodo, MagicMock())

        fb.execute(plc_name="ZC_PLC_STD")

    assert fb.nStep == fb.n_done
    assert fb.error_msg is None
    assert fb.result is not None
    assert fb.result["operations"] == 0
    assert fb.result["n_max_updates"] == 0