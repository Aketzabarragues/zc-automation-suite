"""Tests para stage 3 (preparar_ops) y stage 4 (tx_a_nmax) del FB entities_sincronizar.

Cubre:
  - stage_3_preparar_ops: walk unified_todos + nmax_block → 3 listas
  - stage_4_tx_a_nmax: dispatch_async con execute_transactional_batch (no-op si no hay op)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_fb(
    *,
    config_manager: MagicMock | None = None,
    tia_client: MagicMock | None = None,
    app_state: MagicMock | None = None,
) -> "FunctionEntidadesSincronizar":
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )
    return FunctionEntidadesSincronizar(
        config_manager=config_manager or MagicMock(),
        tia_client=tia_client or MagicMock(),
        build_cache=Path("."),
        app_state=app_state or MagicMock(),
    )


def _bootstrap_fb(fb: "FunctionEntidadesSincronizar") -> None:
    """on_start con todas las validaciones mockeadas + ctx listo."""
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


def test_stage_3_preparar_ops_constante_agregar() -> None:
    """Op add en entities_ops → 1 const op (add)."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.entities_ops = [
        {
            "kind":         "add",
            "plc_tag":      "ENT_001",
            "value_excel":  1,
            "comment_excel": "Linea 1",
        },
    ]
    fb._ctx.nmax_block = {"todos": [], "summary": {}}

    import asyncio
    asyncio.run(fb._stage_3_preparar_ops())

    assert len(fb._ctx.constant_ops) == 1
    op = fb._ctx.constant_ops[0]
    assert op["kind"] == "add"
    assert op["plc_tag"] == "ENT_001"
    assert op["uid"] == 1
    assert op["comment"] == "Linea 1"


def test_stage_3_preparar_ops_constante_eliminar() -> None:
    """Op delete en entities_ops → 1 const op (remove)."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.entities_ops = [
        {
            "kind":      "delete",
            "plc_tag":   "Constant_1",
            "value_tia": 4,
        },
    ]
    fb._ctx.nmax_block = {"todos": [], "summary": {}}

    import asyncio
    asyncio.run(fb._stage_3_preparar_ops())

    assert len(fb._ctx.constant_ops) == 1
    op = fb._ctx.constant_ops[0]
    assert op["kind"] == "remove"
    assert op["plc_tag"] == "Constant_1"


def test_stage_3_preparar_ops_constante_renombrar() -> None:
    """Op update_comment en entities_ops → 1 const op (rename_comment)."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.entities_ops = [
        {
            "kind":          "update_comment",
            "plc_tag":       "ENT_000",
            "value_tia":     0,
            "comment_tia":   "NO SE USA",
            "comment_excel": "NO USAR. NO ELIMINAR.",
        },
    ]
    fb._ctx.nmax_block = {"todos": [], "summary": {}}

    import asyncio
    asyncio.run(fb._stage_3_preparar_ops())

    assert len(fb._ctx.constant_ops) == 1
    op = fb._ctx.constant_ops[0]
    assert op["kind"] == "rename_comment"
    assert op["plc_tag"] == "ENT_000"
    assert op["new_comment"] == "NO USAR. NO ELIMINAR."


def test_stage_3_preparar_ops_sin_ops_no_genera_op() -> None:
    """Sin entities_ops → 0 const ops."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.entities_ops = []
    fb._ctx.nmax_block = {"todos": [], "summary": {}}

    import asyncio
    asyncio.run(fb._stage_3_preparar_ops())

    assert fb._ctx.constant_ops == []


def test_stage_3_preparar_ops_sin_cambios_es_noop() -> None:
    """D.8.12: op ``sin_cambios`` es informativa; el sync FB no la aplica
    (constant_ops y comment_ops quedan vacias para esa entity).
    """
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.entities_ops = [
        {"kind": "sin_cambios", "plc_tag": "ENT_001", "value_tia": 1},
        {"kind": "sin_cambios", "plc_tag": "ENT_002", "value_tia": 2},
    ]
    fb._ctx.desired_entities = ()  # sin entities del Excel -> comment_ops vacias
    fb._ctx.nmax_block = {"todos": [], "summary": {}}

    import asyncio
    asyncio.run(fb._stage_3_preparar_ops())

    # El sync ignora las ops sin_cambios: 0 ops de constant ni comment.
    assert fb._ctx.constant_ops == []
    assert fb._ctx.comment_ops == []


def test_stage_3_preparar_ops_mismo_plc_tag_distinto_value_split() -> None:
    """delete + add (mismo plc_tag, value distinto) en entities_ops -> 2 const ops."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.entities_ops = [
        {"kind": "delete", "plc_tag": "ENT_001", "value_tia": 3},
        {
            "kind":          "add",
            "plc_tag":       "ENT_001",
            "value_excel":   1,
            "comment_excel": "Linea 1",
        },
    ]
    fb._ctx.nmax_block = {"todos": [], "summary": {}}

    import asyncio
    asyncio.run(fb._stage_3_preparar_ops())

    assert len(fb._ctx.constant_ops) == 2
    # Orden: remove primero, add después (evita colision de plc_tag en el XML).
    assert fb._ctx.constant_ops[0]["kind"] == "remove"
    assert fb._ctx.constant_ops[1]["kind"] == "add"
    assert fb._ctx.constant_ops[0]["plc_tag"] == "ENT_001"
    assert fb._ctx.constant_ops[1]["plc_tag"] == "ENT_001"
    assert fb._ctx.constant_ops[1]["uid"] == 1


def test_stage_3_preparar_ops_nmax_op_si_hay_actualizar() -> None:
    """Si nmax_block.todos tiene 1 entry con status='actualizar', nmax_op se popula."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.unified_todos = []
    fb._ctx.nmax_block = {
        "todos": [
            {"name": "N_MAX_ENTIDAD", "status": "actualizar", "nuevo": 20, "actual": 16},
        ],
        "summary": {"actualizar": 1, "sin_cambios": 0},
    }

    import asyncio
    asyncio.run(fb._stage_3_preparar_ops())

    assert fb._ctx.nmax_op is not None
    assert fb._ctx.nmax_op["command"] == "update_user_constant_value"
    assert fb._ctx.nmax_op["args"]["constant_name"] == "N_MAX_ENTIDAD"
    assert fb._ctx.nmax_op["args"]["new_value"] == 20
    assert fb._ctx.nmax_op["args"]["table_name"] == "0_Config_Generales"


def test_stage_3_preparar_ops_nmax_op_none_si_sin_cambios() -> None:
    """Si nmax_block.todos esta vacio o sin 'actualizar', nmax_op es None."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.unified_todos = []
    fb._ctx.nmax_block = {
        "todos": [{"name": "N_MAX_ENTIDAD", "status": "sin_cambios", "nuevo": 16, "actual": 16}],
        "summary": {"actualizar": 0, "sin_cambios": 1},
    }

    import asyncio
    asyncio.run(fb._stage_3_preparar_ops())

    assert fb._ctx.nmax_op is None


def test_stage_3_preparar_ops_comment_ops_para_slot_con_valor() -> None:
    """Entities del Excel con plc_comentario no vacio -> 1 comment op por entity."""
    from dataclasses import dataclass

    @dataclass
    class _Ent:
        plc_tag: str
        numero: int
        plc_comentario: str = ""

    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.entities_ops = []
    fb._ctx.desired_entities = [
        _Ent("ENT_001", 1, "Linea 1"),
        _Ent("ENT_004", 4, "Linea 4"),
    ]
    fb._ctx.nmax_block = {"todos": [], "summary": {}}

    import asyncio
    asyncio.run(fb._stage_3_preparar_ops())

    assert len(fb._ctx.comment_ops) == 2
    assert fb._ctx.comment_ops[0] == {"kind": "update_comment", "slot": 1, "new_comment": "Linea 1"}
    assert fb._ctx.comment_ops[1] == {"kind": "update_comment", "slot": 4, "new_comment": "Linea 4"}


def test_stage_3_preparar_ops_ignora_slot_sin_comment_excel() -> None:
    """Entities sin plc_comentario (vacio) no generan comment op (preservacion)."""
    from dataclasses import dataclass

    @dataclass
    class _Ent:
        plc_tag: str
        numero: int
        plc_comentario: str = ""

    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.entities_ops = []
    fb._ctx.desired_entities = [
        _Ent("ENT_011", 11, ""),  # sin comment
    ]
    fb._ctx.nmax_block = {"todos": [], "summary": {}}

    import asyncio
    asyncio.run(fb._stage_3_preparar_ops())

    assert fb._ctx.constant_ops == []
    assert fb._ctx.comment_ops == []


def test_stage_4_tx_a_nmax_sin_op_es_noop() -> None:
    """Sin nmax_op, stage 4 no llama dispatch_async (no hay cambios)."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = None

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(),
    ) as dispatch_mock:
        import asyncio
        asyncio.run(fb._stage_4_tx_a_nmax())

    assert dispatch_mock.await_count == 0
    assert fb._ctx.nmax_result is None


def test_stage_4_tx_a_nmax_llama_execute_transactional_batch() -> None:
    """Con nmax_op, stage 4 llama execute_transactional_batch con 1 op y
    luego compile_blocks defensivo sobre el DB."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = {
        "command": "update_user_constant_value",
        "args": {
            "plc_name":      "ZC_PLC_STD",
            "table_name":    "0_Config_Generales",
            "constant_name": "N_MAX_ENTIDAD",
            "new_value":     20,
        },
    }

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(return_value={"updated": True, "constant": "N_MAX_ENTIDAD", "value": 20}),
    ) as dispatch_mock:
        import asyncio
        asyncio.run(fb._stage_4_tx_a_nmax())

    # Tx A + compile defensivo.
    assert dispatch_mock.await_count == 2
    tx_a_call = dispatch_mock.await_args_list[0]
    assert tx_a_call.args[1] == "execute_transactional_batch"
    assert "operations" in tx_a_call.args[2]
    assert len(tx_a_call.args[2]["operations"]) == 1
    assert tx_a_call.args[2]["operations"][0]["command"] == "update_user_constant_value"
    compile_call = dispatch_mock.await_args_list[1]
    assert compile_call.args[1] == "compile_blocks"
    assert compile_call.args[2]["block_names"] == ["DB6_ENT"]
    assert fb._ctx.nmax_result == {"updated": True, "constant": "N_MAX_ENTIDAD", "value": 20}


def test_stage_4_tx_a_nmax_compile_defensivo_si_falla_sigue() -> None:
    """Si el compile defensivo lanza excepcion, stage 4 no rompe
    (log warning y sigue). Stage 9 compila de nuevo tras Tx C."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = {
        "command": "update_user_constant_value",
        "args": {
            "plc_name":      "ZC_PLC_STD",
            "table_name":    "0_Config_Generales",
            "constant_name": "N_MAX_ENTIDAD",
            "new_value":     20,
        },
    }

    # Primer dispatch (Tx A) OK, segundo (compile) lanza excepcion.
    side_effects = [
        {"updated": True, "constant": "N_MAX_ENTIDAD", "value": 20},
        RuntimeError("compile rejected"),
    ]
    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(side_effect=side_effects),
    ):
        import asyncio
        asyncio.run(fb._stage_4_tx_a_nmax())

    # No raise, sigue. fb._ctx.nmax_result queda con el dict del Tx A OK.
    assert fb._ctx.nmax_result == {"updated": True, "constant": "N_MAX_ENTIDAD", "value": 20}


def test_stage_4_tx_a_nmax_si_worker_falla_raise() -> None:
    """Si dispatch_async retorna None (worker TIA falla), raise RuntimeError."""
    fb = _make_fb()
    _bootstrap_fb(fb)
    fb._ctx.nmax_op = {
        "command": "update_user_constant_value",
        "args": {
            "plc_name":      "ZC_PLC_STD",
            "table_name":    "0_Config_Generales",
            "constant_name": "N_MAX_ENTIDAD",
            "new_value":     20,
        },
    }

    with patch(
        "areas.alimentacion.functions.function_entidades_sincronizar"
        ".dispatch_async",
        new=AsyncMock(return_value=None),
    ):
        import asyncio
        with pytest.raises(RuntimeError, match="Tx A .NMAX update"):
            asyncio.run(fb._stage_4_tx_a_nmax())


# ============================================================================
# Tests para los helpers del modifier (D.2)
# ============================================================================


def test_modifier_remove_user_constants_by_name() -> None:
    """PlcUserConstantModifier.remove_user_constants_by_name borra por <Name>."""
    import xml.etree.ElementTree as ET
    from core.helpers.simatic_ml import PlcUserConstantModifier
    from pathlib import Path
    import tempfile

    xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Document>\n'
        '  <SW.Tags.PlcTagTable ID="0">\n'
        '    <ObjectList>\n'
        '      <SW.Tags.PlcUserConstant ID="1">\n'
        '        <AttributeList><Name>ENT_001</Name><Value>1</Value></AttributeList>\n'
        '      </SW.Tags.PlcUserConstant>\n'
        '      <SW.Tags.PlcUserConstant ID="2">\n'
        '        <AttributeList><Name>ENT_002</Name><Value>2</Value></AttributeList>\n'
        '      </SW.Tags.PlcUserConstant>\n'
        '      <SW.Tags.PlcUserConstant ID="3">\n'
        '        <AttributeList><Name>Constant_1</Name><Value>4</Value></AttributeList>\n'
        '      </SW.Tags.PlcUserConstant>\n'
        '    </ObjectList>\n'
        '  </SW.Tags.PlcTagTable>\n'
        '</Document>\n'
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", delete=False, encoding="utf-8"
    ) as f:
        f.write(xml_content)
        xml_path = Path(f.name)

    try:
        modifier = PlcUserConstantModifier(xml_path)
        removed = modifier.remove_user_constants_by_name({"Constant_1", "ENT_001"})

        assert removed == 2
        # Verify only ENT_002 remains.
        remaining_names = []
        for const in modifier._root.findall(".//{*}SW.Tags.PlcUserConstant"):
            name_el = const.find(".//{*}Name")
            if name_el is not None and name_el.text:
                remaining_names.append(name_el.text.strip())
        assert remaining_names == ["ENT_002"]
        assert modifier.was_modified()
    finally:
        xml_path.unlink()


def test_modifier_update_user_constant_comment() -> None:
    """update_user_constant_comment inyecta MultilingualText en la constant."""
    import tempfile
    from core.helpers.simatic_ml import PlcUserConstantModifier
    from pathlib import Path

    xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Document>\n'
        '  <SW.Tags.PlcTagTable ID="0">\n'
        '    <ObjectList>\n'
        '      <SW.Tags.PlcUserConstant ID="1">\n'
        '        <AttributeList><Name>ENT_001</Name><Value>1</Value></AttributeList>\n'
        '      </SW.Tags.PlcUserConstant>\n'
        '    </ObjectList>\n'
        '  </SW.Tags.PlcTagTable>\n'
        '</Document>\n'
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", delete=False, encoding="utf-8"
    ) as f:
        f.write(xml_content)
        xml_path = Path(f.name)

    try:
        modifier = PlcUserConstantModifier(xml_path)
        ok = modifier.update_user_constant_comment("ENT_001", "Linea 1")
        assert ok is True

        # Verificar que se inyectó el MultilingualText con el comment.
        const = next(
            c for c in modifier._root.findall(".//{*}SW.Tags.PlcUserConstant")
        )
        # <Text> vive dentro de <AttributeList>, no como hijo directo
        # de <MultilingualTextItem>. XPath con // para descender.
        text_el = const.find(".//{*}MultilingualTextItem//{*}Text")
        assert text_el is not None
        assert text_el.text == "Linea 1"
        assert modifier.was_modified()
    finally:
        xml_path.unlink()


def test_modifier_update_user_constant_comment_no_encontrado() -> None:
    """Si la constant no existe, devuelve False sin raise."""
    import tempfile
    from core.helpers.simatic_ml import PlcUserConstantModifier
    from pathlib import Path

    xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Document><SW.Tags.PlcTagTable ID="0"><ObjectList></ObjectList>'
        '</SW.Tags.PlcTagTable></Document>\n'
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", delete=False, encoding="utf-8"
    ) as f:
        f.write(xml_content)
        xml_path = Path(f.name)

    try:
        modifier = PlcUserConstantModifier(xml_path)
        ok = modifier.update_user_constant_comment("NO_EXISTE", "x")
        assert ok is False
        assert modifier.was_modified() is False
    finally:
        xml_path.unlink()


def test_modifier_update_user_constant_value_by_name() -> None:
    """update_user_constant_value_by_name actualiza el <Value> offline."""
    import tempfile
    from core.helpers.simatic_ml import PlcUserConstantModifier
    from pathlib import Path

    xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Document>\n'
        '  <SW.Tags.PlcTagTable ID="0">\n'
        '    <ObjectList>\n'
        '      <SW.Tags.PlcUserConstant ID="1">\n'
        '        <AttributeList><Name>N_MAX_ENTIDAD</Name><Value>16</Value></AttributeList>\n'
        '      </SW.Tags.PlcUserConstant>\n'
        '    </ObjectList>\n'
        '  </SW.Tags.PlcTagTable>\n'
        '</Document>\n'
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", delete=False, encoding="utf-8"
    ) as f:
        f.write(xml_content)
        xml_path = Path(f.name)

    try:
        modifier = PlcUserConstantModifier(xml_path)
        ok = modifier.update_user_constant_value_by_name("N_MAX_ENTIDAD", 20)
        assert ok is True
        const = next(
            c for c in modifier._root.findall(".//{*}SW.Tags.PlcUserConstant")
        )
        value_el = const.find(".//{*}Value")
        assert value_el is not None
        assert value_el.text == "20"
        assert modifier.was_modified()
    finally:
        xml_path.unlink()