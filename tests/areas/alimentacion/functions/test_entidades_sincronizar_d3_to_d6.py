"""Tests para stages 5-11 del FB entities_sincronizar (D.3 + D.4 + D.5 + D.6).

Cubre:
  - stage_5_wait_consolidation: sleep solo si hay NMAX op.
  - stage_6_exportar_post_tx_a: re-export 2 dispatch_async solo si hay NMAX op.
  - stage_7_editar_xmls_offline: copytree + PlcUserConstantModifier + commit_array_comments.
  - stage_8_tx_b_constants: execute_transactional_batch con import_plc_tags_xml.
  - stage_9_compilar_bloques: compile_blocks solo si hubo NMAX op.
  - stage_10_tx_c_comments: execute_transactional_batch con import_block.
  - stage_11_post_preview: re-export + recompute unified diff.
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_fb(
    *,
    config_manager: MagicMock | None = None,
    tia_client: MagicMock | None = None,
    app_cache: MagicMock | None = None,
    build_cache: Path | None = None,
) -> "FunctionEntidadesSincronizar":
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )
    return FunctionEntidadesSincronizar(
        config_manager=config_manager or MagicMock(),
        tia_client=tia_client or MagicMock(),
        build_cache=build_cache or Path("."),
        app_cache=app_cache or MagicMock(),
    )


def _bootstrap_fb(fb: "FunctionEntidadesSincronizar") -> None:
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


def _make_sync_dirs(fb: "FunctionEntidadesSincronizar", tmp: Path) -> None:
    """Crea los 4 dirs de sincronizar (export + modified para variables y bloques)."""
    sync_vars_export = tmp / "sync" / "variables" / "export"
    sync_vars_modified = tmp / "sync" / "variables" / "modified"
    sync_bloq_export = tmp / "sync" / "bloques" / "export"
    sync_bloq_modified = tmp / "sync" / "bloques" / "modified"
    for d in (sync_vars_export, sync_vars_modified, sync_bloq_export, sync_bloq_modified):
        d.mkdir(parents=True, exist_ok=True)
    fb._ctx.sync_variables_export = sync_vars_export
    fb._ctx.sync_variables_modified = sync_vars_modified
    fb._ctx.sync_bloques_export = sync_bloq_export
    fb._ctx.sync_bloques_modified = sync_bloq_modified


# ---------------------------------------------------------------------------
# Stage 5
# ---------------------------------------------------------------------------


def test_stage_5_sin_nmax_op_no_llama_sleep() -> None:
    """Sin NMAX op, stage 5 no llama asyncio.sleep (no-op)."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = None

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".time.sleep",
    ) as sleep_mock:
        asyncio.run(fb._stage_5_wait_consolidation())
    sleep_mock.assert_not_called()


def test_stage_5_con_nmax_op_llama_sleep_2s() -> None:
    """Con NMAX op, stage 5 llama asyncio.to_thread(time.sleep, 2.0)."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = {"command": "update_user_constant_value", "args": {}}

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".time.sleep",
    ) as sleep_mock:
        asyncio.run(fb._stage_5_wait_consolidation())
    sleep_mock.assert_called_once_with(2.0)


# ---------------------------------------------------------------------------
# Stage 6
# ---------------------------------------------------------------------------


def test_stage_6_sin_nmax_op_no_re_exporta() -> None:
    """Sin NMAX op, stage 6 no llama dispatch_async."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = None
    fb._ctx.sync_variables_export = Path("sync_vars_export")
    fb._ctx.sync_bloques_export = Path("sync_bloques_export")

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(),
    ) as dispatch_mock:
        asyncio.run(fb._stage_6_exportar_post_tx_a())
    assert dispatch_mock.await_count == 0


def test_stage_6_con_nmax_op_llama_dispatch_async_2_veces() -> None:
    """Con NMAX op, stage 6 re-exporta tags + block."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = {"command": "update_user_constant_value", "args": {}}
    fb._ctx.sync_variables_export = Path("sync_vars_export")
    fb._ctx.sync_bloques_export = Path("sync_bloques_export")

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(return_value={"ok": True}),
    ) as dispatch_mock:
        asyncio.run(fb._stage_6_exportar_post_tx_a())
    assert dispatch_mock.await_count == 2
    assert dispatch_mock.await_args_list[0].args[1] == "export_tables"
    assert dispatch_mock.await_args_list[1].args[1] == "export_blocks"


def test_stage_6_si_worker_falla_sigue_con_warnings() -> None:
    """Si dispatch_async retorna None, stage 6 emite warning y sigue."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = {"command": "update_user_constant_value", "args": {}}
    fb._ctx.sync_variables_export = Path("sync_vars_export")
    fb._ctx.sync_bloques_export = Path("sync_bloques_export")

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(return_value=None),
    ):
        asyncio.run(fb._stage_6_exportar_post_tx_a())
    assert any("Re-export post Tx A fallo" in w for w in fb._ctx.warnings)


# ---------------------------------------------------------------------------
# Stage 7
# ---------------------------------------------------------------------------


def test_stage_7_copytree_filtrado_excluye_nmax(tmp_path: Path) -> None:
    """Stage 7 copia variables EXCLUYENDO 0_Config_Generales.xml (NMAX online-only)."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    _make_sync_dirs(fb, tmp_path)

    # Stage 1 exporta con keep_folder_structure=True, asi que los
    # XML viven en subcarpeta TIA (mirror Disp).
    tags_folder = (
        fb._ctx.config_manager.get_tia_folder_entidades_tags.return_value
    )
    config_folder = (
        fb._ctx.config_manager.get_tia_folder_entidades_config.return_value
    )
    (fb._ctx.sync_variables_export / tags_folder).mkdir(parents=True)
    (fb._ctx.sync_variables_export / config_folder).mkdir(parents=True)

    # Crear 6_Entidades.xml + 0_Config_Generales.xml en export.
    (fb._ctx.sync_variables_export / tags_folder / "6_Entidades.xml").write_text(
        "<Document><SW.Tags.PlcTagTable><ObjectList>"
        "<SW.Tags.PlcUserConstant><AttributeList>"
        "<Name>ENT_001</Name><Value>1</Value></AttributeList>"
        "</SW.Tags.PlcUserConstant>"
        "</ObjectList></SW.Tags.PlcTagTable></Document>",
        encoding="utf-8",
    )
    (fb._ctx.sync_variables_export / config_folder / "0_Config_Generales.xml").write_text(
        "<Document/>", encoding="utf-8",
    )
    # Crear DB en bloques export.
    (fb._ctx.sync_bloques_export / "DB6_ENT.s7dcl").write_text(
        "DATA_BLOCK DB6_ENT\nEND_DATA_BLOCK", encoding="utf-8",
    )
    (fb._ctx.sync_bloques_export / "DB6_ENT.s7res").write_text(
        "MultiLingualTexts: []", encoding="utf-8",
    )

    fb._ctx.constant_ops = [
        {"kind": "add", "plc_tag": "ENT_005", "uid": 5, "comment": "Linea 5"},
    ]
    fb._ctx.comment_ops = [
        {"kind": "update_comment", "slot": 5, "new_comment": "Linea 5"},
    ]

    asyncio.run(fb._stage_7_editar_xmls_offline())

    # modified/ debe tener 6_Entidades.xml (en su subcarpeta TIA) pero
    # NO 0_Config_Generales.xml.
    assert (fb._ctx.sync_variables_modified / tags_folder / "6_Entidades.xml").exists()
    assert not (
        fb._ctx.sync_variables_modified / config_folder / "0_Config_Generales.xml"
    ).exists()


def test_stage_7_aplica_constant_ops_al_xml(tmp_path: Path) -> None:
    """Stage 7 aplica los constant_ops al XML modified/ via PlcUserConstantModifier."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    _make_sync_dirs(fb, tmp_path)

    # Stage 1 exporta con subcarpeta TIA. Crear el XML en su carpeta
    # para que el copytree + PlcUserConstantModifier lo encuentre.
    tags_folder = (
        fb._ctx.config_manager.get_tia_folder_entidades_tags.return_value
    )
    (fb._ctx.sync_variables_export / tags_folder).mkdir(parents=True)

    xml_content = (
        "<Document><SW.Tags.PlcTagTable><ObjectList>"
        "<SW.Tags.PlcUserConstant><AttributeList>"
        "<Name>ENT_001</Name><Value>1</Value></AttributeList>"
        "</SW.Tags.PlcUserConstant>"
        "</ObjectList></SW.Tags.PlcTagTable></Document>"
    )
    (fb._ctx.sync_variables_export / tags_folder / "6_Entidades.xml").write_text(
        xml_content, encoding="utf-8",
    )

    fb._ctx.constant_ops = [
        {"kind": "remove", "plc_tag": "ENT_001"},
        {"kind": "add", "plc_tag": "ENT_005", "uid": 5, "comment": "Linea 5"},
    ]
    fb._ctx.comment_ops = []

    asyncio.run(fb._stage_7_editar_xmls_offline())

    # Verificar que el XML modified (en su subcarpeta TIA) tiene solo ENT_005.
    modified_xml = (
        fb._ctx.sync_variables_modified / tags_folder / "6_Entidades.xml"
    )
    assert modified_xml.exists()
    content = modified_xml.read_text(encoding="utf-8")
    assert "ENT_005" in content
    assert "ENT_001" not in content


# ---------------------------------------------------------------------------
# Stage 8
# ---------------------------------------------------------------------------


def test_stage_8_sin_constant_ops_no_llama_dispatch(tmp_path: Path) -> None:
    """Sin constant_ops, stage 8 no-op."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    _make_sync_dirs(fb, tmp_path)
    fb._ctx.constant_ops = []

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(),
    ) as dispatch_mock:
        asyncio.run(fb._stage_8_tx_b_constants())
    assert dispatch_mock.await_count == 0


def test_stage_8_con_constant_ops_llama_execute_batch(tmp_path: Path) -> None:
    """Con constant_ops, stage 8 llama execute_transactional_batch con
    import_plc_tags_xml (transaccional, atomicidad semantica).
    """
    fb = _make_fb()
    _bootstrap_fb(fb)
    _make_sync_dirs(fb, tmp_path)
    fb._ctx.constant_ops = [
        {"kind": "add", "plc_tag": "ENT_005", "uid": 5, "comment": "x"},
    ]

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(return_value={"ok": True, "result": "OK"}),
    ) as dispatch_mock:
        asyncio.run(fb._stage_8_tx_b_constants())

    assert dispatch_mock.await_count == 1
    call = dispatch_mock.await_args_list[0]
    assert call.args[1] == "execute_transactional_batch"
    assert "operations" in call.args[2]
    assert call.args[2]["operations"][0]["command"] == "import_plc_tags_xml"


# ---------------------------------------------------------------------------
# Stage 9
# ---------------------------------------------------------------------------


def test_stage_9_sin_ops_no_compila() -> None:
    """Sin NMAX op ni comment ops, stage 9 no compila (no hay cambios
    estructurales que consolidar en el DB)."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = None
    fb._ctx.comment_ops = []

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(),
    ) as dispatch_mock:
        asyncio.run(fb._stage_9_compilar_bloques())
    assert dispatch_mock.await_count == 0


def test_stage_9_con_nmax_op_compila_db6_ent() -> None:
    """Con NMAX op, stage 9 llama compile_blocks con block_names=[db_name]."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = {"command": "update_user_constant_value", "args": {}}

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(return_value={"success": True}),
    ) as dispatch_mock:
        asyncio.run(fb._stage_9_compilar_bloques())

    assert dispatch_mock.await_count == 1
    call = dispatch_mock.await_args_list[0]
    assert call.args[1] == "compile_blocks"
    assert call.args[2]["block_names"] == ["DB6_ENT"]
    assert fb._ctx.compile_ok is True


def test_stage_9_con_comment_ops_sin_nmax_compila_db6_ent() -> None:
    """Sin NMAX op pero con comment ops, stage 9 compila igualmente
    (Tx C va a importar el DB con slot comments modificados; el
    compile consolida la estructura del array antes del import)."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = None
    fb._ctx.comment_ops = [
        {"kind": "update_comment", "slot": 1, "new_comment": "Linea 1"},
    ]

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(return_value={"success": True}),
    ) as dispatch_mock:
        asyncio.run(fb._stage_9_compilar_bloques())

    assert dispatch_mock.await_count == 1
    call = dispatch_mock.await_args_list[0]
    assert call.args[1] == "compile_blocks"
    assert call.args[2]["block_names"] == ["DB6_ENT"]


def test_stage_9_compile_falla_sin_abortar() -> None:
    """Si compile_blocks falla (success=False), stage 9 NO raise, marca compile_ok=False."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = {"command": "update_user_constant_value", "args": {}}

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(return_value={"success": False, "error": "x"}),
    ):
        asyncio.run(fb._stage_9_compilar_bloques())
    assert fb._ctx.compile_ok is False
    assert fb._ctx.compile_error == "x"


# ---------------------------------------------------------------------------
# Stage 10
# ---------------------------------------------------------------------------


def test_stage_10_sin_comment_ops_no_llama_dispatch(tmp_path: Path) -> None:
    """Sin comment_ops, stage 10 no-op."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    _make_sync_dirs(fb, tmp_path)
    fb._ctx.comment_ops = []

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(),
    ) as dispatch_mock:
        asyncio.run(fb._stage_10_tx_c_comments())
    assert dispatch_mock.await_count == 0


def test_stage_10_con_comment_ops_llama_import_block(tmp_path: Path) -> None:
    """Con comment_ops, stage 10 llama execute_transactional_batch con import_block."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    _make_sync_dirs(fb, tmp_path)
    fb._ctx.comment_ops = [
        {"kind": "update_comment", "slot": 1, "new_comment": "Linea 1"},
    ]

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(return_value={"ok": True, "result": "OK"}),
    ) as dispatch_mock:
        asyncio.run(fb._stage_10_tx_c_comments())

    assert dispatch_mock.await_count == 1
    call = dispatch_mock.await_args_list[0]
    assert call.args[1] == "execute_transactional_batch"
    assert call.args[2]["operations"][0]["command"] == "import_block"


# ---------------------------------------------------------------------------
# Stage 11
# ---------------------------------------------------------------------------


def test_stage_11_post_preview_recompila_ops(tmp_path: Path) -> None:
    """Stage 11 re-exporta FLAT + recomputa ops, asigna post_sync_preview."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    _make_sync_dirs(fb, tmp_path)

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(return_value={"ok": True}),
    ) as dispatch_mock, patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache"
    ) as bc_mock:
        ent_ctx = MagicMock()
        ent_ctx.preview_config = tmp_path / "preview" / "config"
        ent_ctx.preview_disp = tmp_path / "preview" / "disp"
        ent_ctx.preview_bloques = tmp_path / "preview" / "bloques"
        ent_ctx.clean_preview = MagicMock()
        bc_mock.return_value.entidades = ent_ctx

        # Crear paths vacios para que no falle por archivos faltantes.
        for d in (ent_ctx.preview_config, ent_ctx.preview_disp, ent_ctx.preview_bloques):
            d.mkdir(parents=True, exist_ok=True)

        with patch(
            "areas.alimentacion.functions.function_entidades_sincronizar.get_entidades",
            return_value=[],
        ), patch(
            "areas.alimentacion.functions.function_entidades_sincronizar.get_nmax_entidades",
            return_value={"N_MAX_ENTIDAD": 16},
        ):
            asyncio.run(fb._stage_11_post_preview())

    assert fb._ctx.post_sync_preview is not None
    assert "ops" in fb._ctx.post_sync_preview
    assert fb._ctx.result.get("success") is True
    assert fb._ctx.result.get("post_sync_preview") is not None