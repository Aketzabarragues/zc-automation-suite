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
        table_name: str = "",
        nmax: dict | None = None,
        nmax_names: dict | None = None,
    ) -> None:
        self.db_param_name = db_param
        self.db_alm_name = db_alm
        self.param_subpath = "PLC_X/Program blocks/DB_PARAM"
        self.alm_subpath = "PLC_X/Program blocks/DB_ALM"
        self.preal: list = []
        self.pint: list = []
        self.alm: list = []
        self.missing_blocks: list = []
        self.table_name = table_name
        self.nmax = nmax if nmax is not None else {}
        self.nmax_names = nmax_names if nmax_names is not None else {}

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


# ────────────────────────────────────────────────────────────────────────
# Tests E2E: proc_compute_nmax_ops (sept-2026 fix)
# ────────────────────────────────────────────────────────────────────────
def test_proc_compute_nmax_ops_uses_proc_table_path(tmp_path: Path) -> None:
    """E2E: proc_compute_nmax_ops calcula el diff contra la tabla del
    PROCESO (no la tabla global de disp). Si Excel dice preal=8 y
    current.xml dice 100_N_MAX_PREAL=5, retorna 1 op con constante
    '100_N_MAX_PREAL' (con prefijo uid), NO 'N_MAX_PREAL'.
    """
    # Carpeta preview_variables exportada por el preview.
    preview_dir = tmp_path / "preview_variables"
    preview_dir.mkdir()
    # Tabla del proceso 100_CPR (no la tabla global 000_Config_Dispositivos).
    proc_xml = preview_dir / "100_CPR.xml"
    proc_xml.write_text("<root/>", encoding="utf-8")

    sm = FakeSlotMap(
        table_name="100_CPR",
        nmax={"preal": 8, "pint": 10, "alm": 8},
        nmax_names={
            "preal": "100_N_MAX_PREAL",
            "pint": "100_N_MAX_PINT",
            "alm": "100_N_MAX_ALM",
        },
    )
    ctx = _ctx_with(slot_map=sm)
    ctx.build_cache_root = tmp_path  # build_cache.root = tmp_path
    # Pre-populamos tags_base para no depender de build_cache real.
    ctx.tags_base = preview_dir

    with patch(
        "areas.alimentacion.helpers.xml.disp_tag_table_parser."
        "SimaticMLTagParser.parse_user_constants",
        return_value={"100_N_MAX_PREAL": 5},
    ):
        from areas.alimentacion.helpers.proc.proc_sincronizar import (
            proc_compute_nmax_ops,
        )
        proc_compute_nmax_ops(ctx)

    # Encontramos las 3 ops (preal diff, pint nuevo, alm nuevo).
    by_name = {o["constant_name"]: o for o in ctx.nmax_ops}
    assert by_name["100_N_MAX_PREAL"]["new_value"] == 8
    assert by_name["100_N_MAX_PINT"]["new_value"] == 10
    assert by_name["100_N_MAX_ALM"]["new_value"] == 8
    assert all(o["table_name"] == "100_CPR" for o in ctx.nmax_ops)


def test_proc_compute_nmax_ops_raises_when_xml_not_exported(
    tmp_path: Path,
) -> None:
    """E2E: si la tabla del proceso NO esta exportada (el operario
    salto el preview), el helper raise y propagamos al FB.

    El operario lo valido 2026-09-18: 'si la tabla de variables no
    existe a la hora de sincronizar, hay que marcar como error'.
    """
    preview_dir = tmp_path / "preview_variables"
    preview_dir.mkdir()
    # NO creamos el XML de 100_CPR.xml -> simulamos tabla no exportada.

    sm = FakeSlotMap(
        table_name="100_CPR",
        nmax_names={"preal": "100_N_MAX_PREAL"},
        nmax={"preal": 8},
    )
    ctx = _ctx_with(slot_map=sm)
    ctx.tags_base = preview_dir

    from areas.alimentacion.helpers.proc.proc_sincronizar import (
        proc_compute_nmax_ops,
    )
    with pytest.raises(RuntimeError, match="preview"):
        proc_compute_nmax_ops(ctx)
