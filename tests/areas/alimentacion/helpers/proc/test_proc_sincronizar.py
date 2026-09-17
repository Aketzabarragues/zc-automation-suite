"""Tests del helper ``proc_sincronizar``.

Cubre las 5 funciones puras/async del helper:
  - ``proc_check_state_commit``       -> ctx.excel_loaded.
  - ``proc_check_blocks_commit``      -> ctx.bloques_loaded.
  - ``proc_build_slot_maps_commit``   -> ctx.slot_map.
  - ``proc_open_transaction``         -> ctx.tx_result (2 ops enviadas).
  - ``proc_done_summary_commit``      -> ctx.result (shape legacy).

Cada test mockea ``app_state``, ``config_manager``, ``tia_client`` y
``bloques_cache`` con ``MagicMock`` y valida que el ``ctx`` queda en
el estado esperado tras cada llamada.

Restricciones:
  - NO toca el gateway TIA real.
  - NO toca el sistema de archivos.
  - El helper es **libre de state machine**: cada test llama a UNA
    funcion del helper por vez y valida el efecto en el ``ctx``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.helpers.proc.proc_sincronizar import (
    ProcSyncContext,
    proc_build_slot_maps_commit,
    proc_check_blocks_commit,
    proc_check_state_commit,
    proc_done_summary_commit,
    proc_open_transaction,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_app_state() -> MagicMock:
    """AppState mockeado con ``excel_cache`` poblado."""
    state = MagicMock()
    state.excel_cache = MagicMock()
    return state


@pytest.fixture
def mock_app_state_no_excel() -> MagicMock:
    """AppState mockeado SIN ``excel_cache``."""
    state = MagicMock()
    state.excel_cache = None
    return state


@pytest.fixture
def mock_config_manager() -> MagicMock:
    """ConfigManager mockeado con ``get_tia_folder_proceso``."""
    cm = MagicMock()
    cm.get_tia_folder_proceso = MagicMock(return_value="Procesos/")
    return cm


@pytest.fixture
def mock_bloques_cache() -> MagicMock:
    """DataBloqueCache mockeado con plc_name."""
    cache = MagicMock()
    cache.plc_name = "S7-1500"
    return cache


@pytest.fixture
def mock_tia_client() -> MagicMock:
    """Gateway mockeado.

    El gateway real (``SyncTIAClient``) no expone ``export_block`` ni
    ``execute_transactional_batch`` como metodos directos, sino como
    comandos despachados via ``submit_and_wait(command, args,
    timeout_s)``. Los tests mockean ``submit_and_wait`` retornando
    el shape esperado (``{"ok": True, "result": {"operations_executed": N, ...}}``).
    """
    client = MagicMock()
    client.submit_and_wait = MagicMock(
        return_value={
            "ok": True,
            "result": {
                "operations_executed": 2,
                "details": [
                    {"command": "update_proc_comments_db_param", "ok": True},
                    {"command": "update_proc_comments_db_alm", "ok": True},
                ],
            },
        }
    )
    return client


@pytest.fixture
def make_ctx(
    mock_app_state: MagicMock,
    mock_config_manager: MagicMock,
    mock_tia_client: MagicMock,
    mock_bloques_cache: MagicMock,
):
    """Factory de contextos de prueba con deps inyectadas."""
    def _make(**overrides: Any) -> ProcSyncContext:
        defaults: dict[str, Any] = {
            "plc_name": "S7-1500",
            "proc_uid": 42,
            "tia_client": mock_tia_client,
            "config_manager": mock_config_manager,
            "app_state": mock_app_state,
            "build_cache_root": Path("/tmp/.build_cache"),
            "bloques_cache": mock_bloques_cache,
        }
        defaults.update(overrides)
        return ProcSyncContext(**defaults)
    return _make


# ── Helpers para fake slot_map ───────────────────────────────────────


@dataclass
class FakeSlotMap:
    """Replica minima de ``DataProcSlotMap`` para tests."""

    preal: dict[int, str] = field(default_factory=dict)
    pint: dict[int, str] = field(default_factory=dict)
    alm: dict[int, str] = field(default_factory=dict)
    db_param_name: str = "DB42_CPR_PARAM"
    db_alm_name: str = "DB42_CPR_ALM"
    param_subpath: str = "Procesos/100_CPR/"
    alm_subpath: str = "Procesos/100_CPR/"
    table_name: str = "42_CPR"
    nmax_names: dict[str, str] = field(default_factory=dict)
    nmax: dict[str, int] = field(default_factory=dict)
    missing_blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── proc_check_state_commit ──────────────────────────────────────────


def test_check_state_commit_ok(
    make_ctx: Any,
) -> None:
    """Excel cargado -> ctx.excel_loaded = True."""
    ctx = make_ctx()
    proc_check_state_commit(ctx)
    assert ctx.excel_loaded is True


def test_check_state_commit_no_excel(
    mock_app_state_no_excel: MagicMock,
    make_ctx: Any,
) -> None:
    """Sin excel_cache -> ctx.excel_loaded = False."""
    ctx = make_ctx(app_state=mock_app_state_no_excel)
    proc_check_state_commit(ctx)
    assert ctx.excel_loaded is False


# ── proc_check_blocks_commit ─────────────────────────────────────────


def test_check_blocks_commit_ok(
    make_ctx: Any,
) -> None:
    """bloques_cache presente -> ctx.bloques_loaded = True."""
    ctx = make_ctx()
    proc_check_blocks_commit(ctx)
    assert ctx.bloques_loaded is True


def test_check_blocks_commit_none(
    make_ctx: Any,
) -> None:
    """bloques_cache None -> ctx.bloques_loaded = False."""
    ctx = make_ctx(bloques_cache=None)
    proc_check_blocks_commit(ctx)
    assert ctx.bloques_loaded is False


# ── proc_build_slot_maps_commit ──────────────────────────────────────


def test_build_slot_maps_commit_returns_slot_map(
    make_ctx: Any,
) -> None:
    """Happy path: delega en ``proc_build_slot_maps`` de data_ProcSlotMap."""
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod

    fake_sm = FakeSlotMap(preal={1: "Bomba 1"}, pint={1: "Param 1"}, alm={1: "Alarma 1"})
    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx()
        proc_build_slot_maps_commit(ctx)

    assert ctx.slot_map is fake_sm


def test_build_slot_maps_commit_propagates_runtime_error(
    make_ctx: Any,
) -> None:
    """Si proc_build_slot_maps lanza RuntimeError, se propaga al caller."""
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod

    with patch.object(
        data_mod, "proc_build_slot_maps",
        side_effect=RuntimeError("uid 99 no esta en el Excel"),
    ):
        ctx = make_ctx()
        with pytest.raises(RuntimeError, match="uid 99"):
            proc_build_slot_maps_commit(ctx)


# ── proc_open_transaction ────────────────────────────────────────────


def test_open_transaction_happy_path(
    make_ctx: Any,
) -> None:
    """Happy path: 2 ops enviadas al gateway, ctx.tx_result poblado."""
    import asyncio
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod

    fake_sm = FakeSlotMap(
        preal={1: "Bomba 1", 2: "Bomba 2"},
        pint={1: "Param 1"},
        alm={1: "Alarma 1"},
    )

    # Mockear export_block para que NO haga nada (modo degradado,
    # no detecta "eliminar", solo procesa los slots del Excel).
    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx()
        proc_build_slot_maps_commit(ctx)
        asyncio.run(proc_open_transaction(ctx))

    # El gateway recibio 2 ops.
    assert ctx.tx_result is not None
    assert ctx.tx_result["operations_executed"] == 2
    # Verificamos que se llamo al gateway con las 2 ops correctas.
    # ``submit_and_wait`` recibe (``command``, ``args``, ``timeout_s``).
    call_args = ctx.tia_client.submit_and_wait.call_args
    assert call_args is not None
    command_name = call_args.args[0] if call_args.args else call_args.kwargs.get("command")
    args = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("args", {})
    assert command_name == "execute_transactional_batch"
    assert "operations" in args
    assert len(args["operations"]) == 2
    commands = {op["command"] for op in args["operations"]}
    assert commands == {"update_proc_comments_db_param", "update_proc_comments_db_alm"}
    # La op de PARAM contiene preal_slot_map + pint_slot_map.
    param_op = next(
        op for op in args["operations"]
        if op["command"] == "update_proc_comments_db_param"
    )
    assert "preal_slot_map" in param_op["args"]
    assert "pint_slot_map" in param_op["args"]
    assert param_op["args"]["preal_slot_map"]["1"] == "Bomba 1"
    assert param_op["args"]["pint_slot_map"]["1"] == "Param 1"
    # La op de ALM contiene slot_map (string keys).
    alm_op = next(
        op for op in args["operations"]
        if op["command"] == "update_proc_comments_db_alm"
    )
    assert alm_op["args"]["array_name"] == "ALM"
    assert alm_op["args"]["slot_map"]["1"] == "Alarma 1"


def test_open_transaction_undo_text_contains_codigo(
    make_ctx: Any,
) -> None:
    """El undo_text incluye el codigo extraido de ``db_param_name``."""
    import asyncio
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod

    fake_sm = FakeSlotMap(
        db_param_name="DB42_CPR_PARAM",
        preal={1: "Bomba 1"},
    )
    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx()
        proc_build_slot_maps_commit(ctx)
        asyncio.run(proc_open_transaction(ctx))

    call_args = ctx.tia_client.submit_and_wait.call_args
    args = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("args", {})
    assert "CPR" in args["undo_text"]
    assert "S7-1500" in args["undo_text"]


def test_open_transaction_propagates_gateway_error(
    make_ctx: Any,
) -> None:
    """Si el gateway falla, la excepcion se propaga al caller (rollback atomico)."""
    import asyncio
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod

    fake_sm = FakeSlotMap(preal={1: "Bomba 1"})

    # ``submit_and_wait`` falla con RuntimeError para el batch.
    mock_tia = MagicMock()
    mock_tia.submit_and_wait = MagicMock(
        side_effect=RuntimeError("Bloque DB42_CPR_PARAM no encontrado en TIA")
    )

    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx(tia_client=mock_tia)
        proc_build_slot_maps_commit(ctx)
        with pytest.raises(RuntimeError, match="Bloque DB42_CPR_PARAM"):
            asyncio.run(proc_open_transaction(ctx))

    assert ctx.tx_result is None


def test_open_transaction_continues_when_re_export_fails(
    make_ctx: Any,
) -> None:
    """Si el re-export para detectar 'eliminar' falla, sigue solo con Excel."""
    import asyncio
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod

    fake_sm = FakeSlotMap(
        preal={1: "Bomba 1"},
        pint={1: "Param 1"},
        alm={1: "Alarma 1"},
    )

    # ``submit_and_wait`` falla para export_block, pero funciona para
    # execute_transactional_batch (modo degradado).
    def fake_submit_and_wait(command: str, args: dict, timeout_s: float) -> dict:
        if command == "export_block":
            raise RuntimeError("TIA no responde")
        return {
            "ok": True,
            "result": {"operations_executed": 2, "details": []},
        }

    mock_tia = MagicMock()
    mock_tia.submit_and_wait = MagicMock(side_effect=fake_submit_and_wait)

    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx(tia_client=mock_tia)
        proc_build_slot_maps_commit(ctx)
        # NO debe abortar; sigue con los slots del Excel.
        asyncio.run(proc_open_transaction(ctx))

    assert ctx.tx_result is not None
    assert ctx.tx_result["operations_executed"] == 2


def test_re_export_current_writes_to_exports_subpath(
    make_ctx: Any,
) -> None:
    """``_re_export_current`` escribe a ``exports/<subpath>/``, NO a ``modified/``.

    Fix 2026-09-17: el helper antiguo exportaba a ``modified_bloques``
    (raiz), lo que dejaba archivos stale que el ``import_block`` del
    sync handler reescaneaba y marcaba como ``already exists``.
    Ahora replica el patron del sync handler: export a ``exports/<subpath>/``
    y deja que el handler haga el copytree a ``modified/<subpath>/``.
    """
    import asyncio
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod

    fake_sm = FakeSlotMap(
        preal={1: "Bomba 1"},
        pint={1: "Param 1"},
        alm={1: "Alarma 1"},
        param_subpath="ZC_Plantillas/50010_ProcesoEstandar/53010_Parametros/",
        alm_subpath="ZC_Plantillas/50010_ProcesoEstandar/55010_Alarmas/",
    )

    # Capturamos TODOS los args de submit_and_wait para validar
    # que el primer export_block (de _re_export_current) va a
    # exports/<subpath>/, NO a modified/.
    captured_calls: list[tuple[str, dict]] = []

    def fake_submit_and_wait(command: str, args: dict, timeout_s: float) -> dict:
        captured_calls.append((command, args))
        if command == "export_block":
            return {"ok": True, "result": {}}
        return {
            "ok": True,
            "result": {"operations_executed": 2, "details": []},
        }

    mock_tia = MagicMock()
    mock_tia.submit_and_wait = MagicMock(side_effect=fake_submit_and_wait)

    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx(tia_client=mock_tia)
        proc_build_slot_maps_commit(ctx)
        asyncio.run(proc_open_transaction(ctx))

    # Filtramos solo los export_block.
    export_calls = [
        (cmd, args) for cmd, args in captured_calls if cmd == "export_block"
    ]
    # Hay 2 export_block via submit_and_wait: ambos de
    # ``_re_export_current`` (1 PARAM + 1 ALM). El sync handler
    # ``update_proc_comments_db_param/_alm`` tambien exporta
    # internamente, pero via ``tia_client._handlers["export_block"]``
    # directo en el worker OT, no via submit_and_wait.
    assert len(export_calls) == 2

    # Los 2 calls son de _re_export_current. Verificamos que
    # sus target_dir apuntan a exports/<subpath>/, NO a modified/.
    first_param_export = export_calls[0][1]
    first_alm_export = export_calls[1][1]
    assert "exports" in first_param_export["target_dir"], (
        f"_re_export_current para PARAM debe escribir a exports/<subpath>/, "
        f"obtuvo: {first_param_export['target_dir']}"
    )
    assert "modified" not in first_param_export["target_dir"], (
        f"_re_export_current para PARAM NO debe escribir a modified/, "
        f"obtuvo: {first_param_export['target_dir']}"
    )
    assert "ZC_Plantillas" in first_param_export["target_dir"]
    assert "53010_Parametros" in first_param_export["target_dir"]

    assert "exports" in first_alm_export["target_dir"], (
        f"_re_export_current para ALM debe escribir a exports/<subpath>/, "
        f"obtuvo: {first_alm_export['target_dir']}"
    )
    assert "modified" not in first_alm_export["target_dir"], (
        f"_re_export_current para ALM NO debe escribir a modified/, "
        f"obtuvo: {first_alm_export['target_dir']}"
    )
    assert "55010_Alarmas" in first_alm_export["target_dir"]


def test_proc_satellites_alias_resolves_to_constant():
    """``_PROC_SATELLITES`` en extra_commands es alias de la constante de data_ProcSlotMap.

    Verifica el DRY: ambos consumers (preview + sync) leen del mismo
    dict. Antes (sept-2026) la constante local en ``extra_commands.py``
    estaba hardcodeada con tuplas vacias -> el sync no propagaba
    comentarios a ``PReal_Vis``, ``PInt_Vis`` ni a ``Aux.*``.
    """
    from areas.alimentacion.helpers.tia import extra_commands
    from areas.alimentacion.data.data_ProcSlotMap import (
        PROC_SATELLITES_BY_ARRAY,
    )

    # El alias en extra_commands apunta a la constante del data module.
    assert extra_commands._PROC_SATELLITES is PROC_SATELLITES_BY_ARRAY

    # Y la constante tiene los 4 satelites esperados + 1 vacio (ALM).
    assert PROC_SATELLITES_BY_ARRAY == {
        "preal": ("PReal_Vis", "Aux.PReal_ValorAnterior"),
        "pint": ("PInt_Vis", "Aux.PInt_ValorAnterior"),
        "alm": (),
    }


def test_slot_map_default_satellites_by_array():
    """``DataProcSlotMap()`` expone ``satellites_by_array`` con los 4 satelites."""
    from areas.alimentacion.data.data_ProcSlotMap import DataProcSlotMap

    sm = DataProcSlotMap()
    assert sm.satellites_by_array == {
        "preal": ("PReal_Vis", "Aux.PReal_ValorAnterior"),
        "pint": ("PInt_Vis", "Aux.PInt_ValorAnterior"),
        "alm": (),
    }


# ── proc_done_summary_commit ────────────────────────────────────────


def test_done_summary_commit_happy_path(
    make_ctx: Any,
) -> None:
    """Con tx_result poblado, el shape legacy es correcto."""
    ctx = make_ctx()
    ctx.tx_result = {
        "operations_executed": 2,
        "details": [
            {"command": "update_proc_comments_db_param", "ok": True},
            {"command": "update_proc_comments_db_alm", "ok": True},
        ],
    }
    proc_done_summary_commit(ctx)
    assert ctx.result["proc_uid"] == 42
    assert ctx.result["plc_name"] == "S7-1500"
    assert ctx.result["success"] is True
    assert ctx.result["applied"] is True
    assert ctx.result["operations_executed"] == 2
    assert len(ctx.result["details"]) == 2


def test_done_summary_commit_no_tx_result(
    make_ctx: Any,
) -> None:
    """Sin tx_result (commit fallo antes), el summary tiene operaciones=0."""
    ctx = make_ctx()
    # tx_result es None por defecto.
    proc_done_summary_commit(ctx)
    assert ctx.result["operations_executed"] == 0
    assert ctx.result["success"] is True
    assert ctx.result["applied"] is True


def test_done_summary_commit_includes_slot_map_warnings(
    make_ctx: Any,
) -> None:
    """Los warnings del slot_map se propagan al result."""
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod

    fake_sm = FakeSlotMap(warnings=["warning de prueba"])
    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx()
        proc_build_slot_maps_commit(ctx)
        proc_done_summary_commit(ctx)

    assert ctx.result["warnings"] == ["warning de prueba"]
