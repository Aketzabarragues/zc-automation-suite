"""Tests para los sub-steps publicos de Tx B
(``proc_tx_b_*``) y un E2E de ``proc_open_transaction``.

Sept-2026: refactor del flujo Tx B en 5 fases testeables
independientemente.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from areas.alimentacion.helpers.proc.proc_sincronizar import (
    ProcSyncContext,
    proc_open_transaction,
    proc_tx_b_calcular_apply_maps,
    proc_tx_b_construir_ops,
    proc_tx_b_detectar_eliminar_read,
    proc_tx_b_limpiar,
)


# ────────────────────────────────────────────────────────────────────────
# Fakes
# ────────────────────────────────────────────────────────────────────────
class FakeSlotMap:
    def __init__(
        self,
        preal: dict[int, str] | None = None,
        pint: dict[int, str] | None = None,
        alm: dict[int, str] | None = None,
    ) -> None:
        self.db_param_name = "DB53100_TEST_PARAM"
        self.db_alm_name = "DB55100_TEST_ALM"
        self.param_subpath = "PLC_X/Program/DB_PARAM"
        self.alm_subpath = "PLC_X/Program/DB_ALM"
        self.preal = preal or {}
        self.pint = pint or {}
        self.alm = alm or {}
        self.missing_blocks: list = []
        self.warnings: list = []


def _ctx_with(
    *,
    slot_map: FakeSlotMap | None = None,
    tia_client: Any = None,
    bloques_cache: Any = None,
    proc_uid: int = 1,
    plc_name: str = "PLC_X",
) -> ProcSyncContext:
    return ProcSyncContext(
        plc_name=plc_name,
        proc_uid=proc_uid,
        tia_client=tia_client,
        config_manager=MagicMock(),
        app_state=MagicMock(),
        build_cache_root=Path("/tmp/fake_build_cache"),
        bloques_cache=bloques_cache,
        slot_map=slot_map,
    )


# ────────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────────
def test_proc_tx_b_limpiar_sets_workdir_paths() -> None:
    """Fase 1: limpia workdir + guarda paths en ctx."""
    ctx = _ctx_with()
    fake_proc_ctx = MagicMock()
    with patch(
        "areas.alimentacion.helpers.build_cache.build_cache",
        return_value=MagicMock(procesos=fake_proc_ctx),
    ):
        proc_tx_b_limpiar(ctx)

    fake_proc_ctx.clean.assert_called_once()
    assert ctx.work_dir == fake_proc_ctx.modified_bloques
    assert ctx.exports_subdir == fake_proc_ctx.exports_bloques


def test_proc_tx_b_calcular_apply_maps_merges_excel_with_delete() -> None:
    """Fase 4: mezcla Excel con los slots a eliminar (``"."``)."""
    sm = FakeSlotMap(
        preal={1: "Bomba 1", 2: "Bomba 2"},
        pint={1: "Param 1"},
        alm={1: "Alarma 1"},
    )
    ctx = _ctx_with(slot_map=sm)

    # En TIA hay un slot extra (slot=99) que no esta en el Excel.
    current = (
        {1: "Bomba 1", 2: "Bomba 2", 99: "Bomba vieja"},  # PReal
        {1: "Param 1"},                                     # PInt
        {1: "Alarma 1"},                                    # ALM
    )

    preal_apply, pint_apply, alm_apply = proc_tx_b_calcular_apply_maps(
        ctx, *current
    )

    assert preal_apply == {"1": "Bomba 1", "2": "Bomba 2", "99": "."}
    assert pint_apply == {"1": "Param 1"}
    assert alm_apply == {"1": "Alarma 1"}
    # Tambien los guarda en ctx para construir ops despues.
    assert ctx.apply_preal_map == preal_apply
    assert ctx.apply_pint_map == pint_apply
    assert ctx.apply_alm_map == alm_apply


def test_proc_tx_b_calcular_apply_maps_no_deep_merge_when_match() -> None:
    """Fase 4: si TIA == Excel, NO genera "eliminar" (sin stale)."""
    sm = FakeSlotMap(
        preal={1: "Bomba 1", 2: "Bomba 2"},
        pint={1: "Param 1"},
        alm={1: "Alarma 1"},
    )
    ctx = _ctx_with(slot_map=sm)
    current = (
        {1: "Bomba 1", 2: "Bomba 2"},
        {1: "Param 1"},
        {1: "Alarma 1"},
    )

    preal_apply, pint_apply, alm_apply = proc_tx_b_calcular_apply_maps(
        ctx, *current
    )

    # Sin "eliminar" (mismas keys).
    assert preal_apply == {"1": "Bomba 1", "2": "Bomba 2"}
    assert pint_apply == {"1": "Param 1"}
    assert alm_apply == {"1": "Alarma 1"}


def test_proc_tx_b_calcular_apply_maps_skips_empty_strings() -> None:
    """Fase 4: slot actual vacio (``""``) NO se interpreta como eliminar."""
    sm = FakeSlotMap(preal={1: "Bomba 1"})
    ctx = _ctx_with(slot_map=sm)
    # TIA tiene slot 99 con texto vacio (no es realmente eliminable).
    current = ({1: "Bomba 1", 99: ""}, {}, {})

    preal_apply, _, _ = proc_tx_b_calcular_apply_maps(ctx, *current)

    # Slot 99 con texto vacio se ignora (no se anyade "eliminar").
    assert preal_apply == {"1": "Bomba 1"}


def test_proc_tx_b_construir_ops_composes_2_commands() -> None:
    """Fase 5: construye las 2 OT ops con los apply_maps del ctx."""
    sm = FakeSlotMap()
    ctx = _ctx_with(
        slot_map=sm,
    )
    # Simulamos que fase 4 ya se ejecuto:
    ctx.apply_preal_map = {"1": "Bomba 1"}
    ctx.apply_pint_map = {"1": "Param 1"}
    ctx.apply_alm_map = {"1": "Alarma 1"}
    ctx.work_dir = Path("/fake/modified")
    ctx.exports_subdir = Path("/fake/exports")
    ctx.config_manager.get_tia_folder_proceso.return_value = "PLC_X/Program"

    ops = proc_tx_b_construir_ops(ctx)

    assert len(ops) == 2
    assert ops[0]["command"] == "update_proc_comments_db_param"
    assert ops[1]["command"] == "update_proc_comments_db_alm"

    # DB_PARAM op: ambos PReal + PInt en la misma op.
    args_param = ops[0]["args"]
    assert args_param["db_name"] == "DB53100_TEST_PARAM"
    assert args_param["db_subpath"] == "PLC_X/Program/DB_PARAM"
    assert args_param["preal_slot_map"] == {"1": "Bomba 1"}
    assert args_param["pint_slot_map"] == {"1": "Param 1"}

    # DB_ALM op: solo ALM.
    args_alm = ops[1]["args"]
    assert args_alm["db_name"] == "DB55100_TEST_ALM"
    assert args_alm["db_subpath"] == "PLC_X/Program/DB_ALM"
    assert args_alm["array_name"] == "ALM"
    assert args_alm["slot_map"] == {"1": "Alarma 1"}

    # Tambien guarda en ctx para audit.
    assert ctx.tx_b_ops == ops


# ────────────────────────────────────────────────────────────────────────
# E2E: proc_open_transaction orquesta las 5 fases + dispatch
# ────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_proc_open_transaction_e2e_all_5_phases() -> None:
    """E2E: verify que ``proc_open_transaction`` ejecuta las 5 fases
    en orden y termina dispatchando el batch.

    Mockeamos dispatch_async para verificar:
      1. export_block x2 (Phase 2)
      2. execute_transactional_batch x1 (Final)

    Phase 3 (read) + Phase 4 (calcular) las verificamos por sus
    side-effects sobre ctx (apply_*_map, exports_param_dir).
    """
    sm = FakeSlotMap(
        preal={1: "Bomba 1", 2: "Bomba 2"},
        pint={1: "Param 1"},
        alm={1: "Alarma 1"},
    )
    bloques_cache = MagicMock()
    bloques_cache.plc_name = "PLC_X"
    ctx = _ctx_with(
        slot_map=sm,
        bloques_cache=bloques_cache,
    )
    # Mockeamos build_cache para no tocar filesystem.
    fake_proc_ctx = MagicMock()
    fake_proc_ctx.modified_bloques = Path("/fake/modified")
    fake_proc_ctx.exports_bloques = Path("/fake/exports")

    # Para Phase 3 (read): creamos un par .s7dcl vacios que el
    # ``SdPair`` pueda construir, y un ProcCommentUpdater que devuelve
    # current vacio (modo "todo en Excel", sin eliminar).
    export_calls = []
    batch_calls = []

    async def fake_dispatch(tia_client, command, args, **kwargs):
        if command == "export_block":
            export_calls.append((command, args))
            # Crear el archivo vacio para que SdPair no falle.
            args_block_dir = Path(args["target_dir"])
            args_block_dir.mkdir(parents=True, exist_ok=True)
            (args_block_dir / f"{args['block_name']}.s7dcl").write_text(
                "DATA_BLOCK DBxxx\nEND_DATA_BLOCK\n"
            )
            (args_block_dir / f"{args['block_name']}.s7res").write_text(
                "MultiLingualTexts:\n"
            )
            return {"ok": True, "result": {}}
        if command == "execute_transactional_batch":
            batch_calls.append((command, args))
            return {
                "ok": True,
                "result": {"operations_executed": 2, "details": []},
            }
        return {"ok": True, "result": {}}

    with patch(
        "areas.alimentacion.helpers.build_cache.build_cache",
        return_value=MagicMock(procesos=fake_proc_ctx),
    ), patch(
        "areas.alimentacion.helpers.proc.proc_sincronizar.dispatch_async",
        side_effect=fake_dispatch,
    ):
        await proc_open_transaction(ctx)

    # Phase 1: clean() llamado.
    fake_proc_ctx.clean.assert_called_once()
    # Phase 2: 2 export_block (PARAM + ALM) a exports/<subpath>/.
    assert len(export_calls) == 2
    assert export_calls[0][1]["block_name"] == "DB53100_TEST_PARAM"
    assert export_calls[1][1]["block_name"] == "DB55100_TEST_ALM"
    # Phase 4: ctx.apply_*_map poblados.
    assert ctx.apply_preal_map == {"1": "Bomba 1", "2": "Bomba 2"}
    assert ctx.apply_pint_map == {"1": "Param 1"}
    assert ctx.apply_alm_map == {"1": "Alarma 1"}
    # Phase 5 (sept-2026 DRY): commit inline -> 7 operaciones
    # (6 arrays PARAM + 1 ALM). NO hay execute_transactional_batch.
    assert len(batch_calls) == 0
    assert ctx.tx_result["operations_executed"] == 7
    arrays = [d["array"] for d in ctx.tx_result["details"]]
    assert arrays == [
        "PReal", "PReal_Vis", "Aux.PReal_ValorAnterior",
        "PInt", "PInt_Vis", "Aux.PInt_ValorAnterior",
        "ALM",
    ]
    # tx_b_ops queda obsoleto post-DRY (Phase 5 ya no construye ops).
    assert ctx.tx_b_ops == []


@pytest.mark.asyncio
async def test_proc_open_transaction_degraded_when_export_fails() -> None:
    """E2E degradado: si export_block falla, sigue sin 'eliminar'."""
    sm = FakeSlotMap(
        preal={1: "Bomba 1"},
        pint={1: "Param 1"},
        alm={1: "Alarma 1"},
    )
    bloques_cache = MagicMock()
    bloques_cache.plc_name = "PLC_X"
    ctx = _ctx_with(slot_map=sm, bloques_cache=bloques_cache)

    fake_proc_ctx = MagicMock()
    fake_proc_ctx.modified_bloques = Path("/fake/modified")
    fake_proc_ctx.exports_bloques = Path("/fake/exports")

    async def fake_dispatch(tia_client, command, args, **kwargs):
        if command == "export_block":
            raise RuntimeError("TIA no responde")
        if command == "execute_transactional_batch":
            return {
                "ok": True,
                "result": {"operations_executed": 2, "details": []},
            }
        return {"ok": True, "result": {}}

    with patch(
        "areas.alimentacion.helpers.build_cache.build_cache",
        return_value=MagicMock(procesos=fake_proc_ctx),
    ), patch(
        "areas.alimentacion.helpers.proc.proc_sincronizar.dispatch_async",
        side_effect=fake_dispatch,
    ):
        await proc_open_transaction(ctx)

    # Modo degradado: apply maps = solo Excel (sin "eliminar").
    assert ctx.apply_preal_map == {"1": "Bomba 1"}
    assert ctx.apply_pint_map == {"1": "Param 1"}
    assert ctx.apply_alm_map == {"1": "Alarma 1"}
    # Sept-2026 DRY: el commit inline (Phase 5) se SKIP porque
    # ``exports_param_dir`` quedo None. ``operations_executed=0``.
    assert ctx.tx_result["operations_executed"] == 0
    assert ctx.tx_result["details"] == []
