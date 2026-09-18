"""Tests para los nuevos steps ``sync_nmax`` + ``compile_proc_blocks``
del helper de proc."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Evitar imports circulares via 'areas.alimentacion.helpers.proc'.
from areas.alimentacion.helpers.proc.proc_sincronizar import ProcSyncContext


# ────────────────────────────────────────────────────────────────────────
# Fakes
# ────────────────────────────────────────────────────────────────────────
class FakeSlotMap:
    """Replica ``DataProcSlotMap`` con los 4 campos que el helper usa."""

    def __init__(
        self,
        db_param: str = "DB53100_TEST_PARAM",
        db_alm: str = "DB55100_TEST_ALM",
    ) -> None:
        self.db_param_name = db_param
        self.db_alm_name = db_alm
        self.param_subpath = "PLC_X/Program blocks/DB_PARAM"
        self.alm_subpath = "PLC_X/Program blocks/DB_ALM"
        self.preal: list = []
        self.pint: list = []
        self.alm: list = []
        self.missing_blocks: list = []

    @property
    def satellites_by_array(self) -> dict[str, list[str]]:
        return {}


def _ctx_with(
    *,
    slot_map: FakeSlotMap | None = None,
    tia_client: Any = None,
    nmax_ops: list[dict] | None = None,
) -> ProcSyncContext:
    return ProcSyncContext(
        plc_name="PLC_X",
        proc_uid=1,
        tia_client=tia_client,
        config_manager=MagicMock(),
        app_state=MagicMock(),
        build_cache_root=Path("/tmp/fake_build_cache"),
        bloques_cache=MagicMock(),
        slot_map=slot_map,
        nmax_ops=list(nmax_ops) if nmax_ops is not None else [],
    )


# ────────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_proc_sync_nmax_dispatches_with_empty_ops() -> None:
    """INCONDICIONAL (requisito Aketza): aunque ``nmax_ops=[]``, el FB
    despacha el handler. TIA no aplicara nada, pero el flujo se ejecuta
    completo."""
    ctx = _ctx_with(tia_client=MagicMock())
    with patch(
        "areas.alimentacion.helpers.proc.proc_sincronizar.dispatch_async",
        new=AsyncMock(return_value={"ok": True, "result": {"applied": 0}}),
    ) as da:
        from areas.alimentacion.helpers.proc.proc_sincronizar import proc_sync_nmax
        await proc_sync_nmax(ctx)

    assert da.called
    args = da.call_args
    assert args.args[1] == "commit_user_constants_online"
    payload = args.args[2]
    assert payload["plc_name"] == "PLC_X"
    assert payload["nmax_ops"] == []
    assert payload["rename_ops"] == []


@pytest.mark.asyncio
async def test_proc_sync_nmax_dispatches_with_diff() -> None:
    """Cuando hay diff, se pasan las ops al handler."""
    ops = [
        {"table_name": "000_Config_Dispositivos",
         "constant_name": "N_MAX_PREAL", "new_value": 30},
    ]
    ctx = _ctx_with(
        tia_client=MagicMock(),
        nmax_ops=ops,
    )
    with patch(
        "areas.alimentacion.helpers.proc.proc_sincronizar.dispatch_async",
        new=AsyncMock(return_value={"ok": True, "result": {"applied": 1}}),
    ) as da:
        from areas.alimentacion.helpers.proc.proc_sincronizar import proc_sync_nmax
        await proc_sync_nmax(ctx)

    payload = da.call_args.args[2]
    assert payload["nmax_ops"] == ops
    assert ctx.nmax_result == {"applied": 1}


@pytest.mark.asyncio
async def test_proc_sync_nmax_propagates_error() -> None:
    """Si el handler falla (ok=False), propaga RuntimeError con detalle."""
    ctx = _ctx_with(tia_client=MagicMock(), nmax_ops=[
        {"table_name": "T", "constant_name": "X", "new_value": 1}
    ])
    with patch(
        "areas.alimentacion.helpers.proc.proc_sincronizar.dispatch_async",
        new=AsyncMock(return_value={"ok": False, "error": "tabla no existe"}),
    ):
        from areas.alimentacion.helpers.proc.proc_sincronizar import proc_sync_nmax
        with pytest.raises(RuntimeError, match="tabla no existe"):
            await proc_sync_nmax(ctx)


def test_proc_discover_compile_dbs_returns_param_and_alm() -> None:
    """Devuelve SIEMPRE los 2 nombres del proceso: DB PARAM + DB ALM."""
    sm = FakeSlotMap(db_param="DB53010_X_PARAM", db_alm="DB55200_Y_ALM")
    ctx = _ctx_with(slot_map=sm)

    from areas.alimentacion.helpers.proc.proc_sincronizar import (
        proc_discover_compile_dbs,
    )
    assert proc_discover_compile_dbs(ctx) == [
        "DB53010_X_PARAM", "DB55200_Y_ALM",
    ]


def test_proc_discover_compile_dbs_empty_without_slot_map() -> None:
    """Si el step se llama antes de tiempo (slot_map=None), retorna []."""
    ctx = _ctx_with(slot_map=None)

    from areas.alimentacion.helpers.proc.proc_sincronizar import (
        proc_discover_compile_dbs,
    )
    assert proc_discover_compile_dbs(ctx) == []


@pytest.mark.asyncio
async def test_proc_compile_blocks_dispatches_with_both_db_names() -> None:
    """El handler ``compile_blocks`` recibe ``block_names=[param, alm]``."""
    sm = FakeSlotMap(db_param="DB53100_P", db_alm="DB55100_A")
    ctx = _ctx_with(slot_map=sm, tia_client=MagicMock())
    with patch(
        "areas.alimentacion.helpers.proc.proc_sincronizar.dispatch_async",
        new=AsyncMock(return_value={
            "ok": True,
            "result": {"compiled": [], "errors": [], "not_found": []},
        }),
    ) as da:
        from areas.alimentacion.helpers.proc.proc_sincronizar import (
            proc_compile_blocks,
        )
        await proc_compile_blocks(ctx)

    payload = da.call_args.args[2]
    assert payload["block_names"] == ["DB53100_P", "DB55100_A"]
    assert payload["plc_name"] == "PLC_X"
    assert ctx.compile_ok is True
    assert ctx.compile_error is None


@pytest.mark.asyncio
async def test_proc_compile_blocks_marks_error_on_partial_failures() -> None:
    """Si TIA reporta ``had_errors``, ``compile_ok=False`` y mensaje."""
    sm = FakeSlotMap()
    ctx = _ctx_with(slot_map=sm, tia_client=MagicMock())
    with patch(
        "areas.alimentacion.helpers.proc.proc_sincronizar.dispatch_async",
        new=AsyncMock(return_value={
            "ok": True,
            "result": {
                "compiled": [{"name": "DB53100_P", "had_errors": True}],
                "errors": ["compile exception"],
                "not_found": [],
            },
        }),
    ):
        from areas.alimentacion.helpers.proc.proc_sincronizar import (
            proc_compile_blocks,
        )
        await proc_compile_blocks(ctx)

    assert ctx.compile_ok is False
    assert "1 bloque(s) con errores" in ctx.compile_error
    assert "1 excepcion(es)" in ctx.compile_error


@pytest.mark.asyncio
async def test_proc_compile_blocks_marks_error_on_gateway_fail() -> None:
    """Si dispatch_async devuelve ``ok=False``, ``compile_ok=False``."""
    sm = FakeSlotMap()
    ctx = _ctx_with(slot_map=sm, tia_client=MagicMock())
    with patch(
        "areas.alimentacion.helpers.proc.proc_sincronizar.dispatch_async",
        new=AsyncMock(return_value={"ok": False, "error": "TIA no responde"}),
    ):
        from areas.alimentacion.helpers.proc.proc_sincronizar import (
            proc_compile_blocks,
        )
        await proc_compile_blocks(ctx)

    assert ctx.compile_ok is False
    assert "TIA no responde" in ctx.compile_error
