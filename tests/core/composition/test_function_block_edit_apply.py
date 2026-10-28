"""Tests del FB core ``FunctionBlockEditApply``.

Cubre:

  - Happy path: 3 bloques con cambios Name+Number -> 3 ops en batch.
  - No-op: edits que coinciden 1:1 con el cache -> sin dispatch.
  - Mixto: 5 bloques en cache, 3 con cambios, 2 sin cambios -> 3 ops.
  - Rollback simulado: batch retorna ``success=False`` -> FB raise.
  - ``edits`` con key no permitida (``"title"``) -> ``ValueError`` en ``on_start``.
  - PLC sin cache de prepare -> ``RuntimeError`` con mensaje claro.
  - ``tia_client=None`` -> ``RuntimeError`` en el primer step.

Mockeamos:

  - ``core.composition.function_block_edit_apply.dispatch_batch_async``
    con ``AsyncMock`` que devuelve la shape del worker OT.
  - ``core.composition.function_block_edit_apply.scan_plc_blocks``
    con ``MagicMock`` que devuelve un cache mock con ``.blocks``
    (la funcion es sync).

Usamos ``AppCache`` real + ``ProgressTracker`` real (mismo patron que
el test del FB ``block_edit_prepare``) para verificar el flujo de
states y stages sin necesidad de mockear internals.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.composition.function_block_edit_apply import FunctionBlockEditApply
from core.data.data_block_plc import DataBloquePLC
from core.infrastructure.tia.tia_loop import SyncTIAClient
from core.runtime.app_cache import AppCache
from core.runtime.progress_buffer import ProgressTracker


# ── Helpers ─────────────────────────────────────────────────────────


def _make_dto(
    name: str,
    number: int,
    ruta: str = "",
    tipo: str = "DB",
) -> DataBloquePLC:
    """DTO extendido minimo para poblar ``block_edit_prepared``."""
    return DataBloquePLC(
        nombre=name,
        numero=number,
        tipo=tipo,
        ruta=ruta,
        title=None,
        comment=None,
        author=None,
        version=None,
        programming_language=None,
        memory_layout=None,
    )


def _seed_cache(
    app_cache: AppCache,
    plc_name: str,
    blocks: list[DataBloquePLC],
) -> None:
    """Inicializa ``app_cache`` con los bloques preparados via helper."""
    app_cache.set_block_edit_prepared(
        plc_name, {b.nombre: b for b in blocks},
    )


def _make_tia_client(wrapper_present: bool = True) -> MagicMock:
    """Mock de ``SyncTIAClient`` con ``wrapper`` configurable."""
    client = MagicMock(spec=SyncTIAClient)
    client.wrapper = MagicMock() if wrapper_present else None
    return client


def _make_dispatch_mock(
    ok: bool = True,
    success: bool = True,
    operations_executed: int = 0,
    details: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> AsyncMock:
    """Mock de ``dispatch_batch_async`` con la shape del worker OT."""
    inner: dict[str, Any] = {
        "success": success,
        "operations_executed": operations_executed,
        "details": details or [],
    }
    if error is not None:
        inner["error"] = error
    return AsyncMock(return_value={"ok": ok, "result": inner})


def _make_scan_mock(n_blocks: int = 3) -> MagicMock:
    """Mock de ``scan_plc_blocks`` que devuelve un cache con N bloques.

    ``scan_plc_blocks`` es sync: el FB la invoca sin await.
    """
    cache = MagicMock()
    cache.blocks = [MagicMock() for _ in range(n_blocks)]
    return MagicMock(return_value=cache)


@pytest.fixture
def real_progress() -> ProgressTracker:
    return ProgressTracker()


@pytest.fixture
def app_cache() -> AppCache:
    return AppCache()


def _make_fb(
    app_cache: AppCache,
    tia_client: MagicMock | None,
    progress: ProgressTracker,
) -> FunctionBlockEditApply:
    return FunctionBlockEditApply(
        nombre="block_edit_apply",
        tia_client=tia_client,
        app_cache=app_cache,
        tracker=progress,
    )


def _drive_fb_to_done(fb: FunctionBlockEditApply) -> None:
    """Tickea el FB hasta ``n_done`` (o ``n_error`` si algo revienta).

    1 arrancar + 5 steps + 1 finalizar = 7 ticks para el flujo completo.
    Se sale del bucle si llega a un estado terminal.
    """
    for _ in range(10):
        if fb.is_terminal():
            break
        asyncio.run(fb.tick())


# ── 1. Happy path: 3 bloques, 3 ops ───────────────────────────────


def test_apply_happy_path_3_blocks(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """3 bloques con edits mixtos Name+Number -> 3 ops en batch."""
    blocks = [
        _make_dto("DB2000_ED", 2000, tipo="DB"),
        _make_dto("FC2000_ZC_ED", 2000, tipo="FC"),
        _make_dto("OB1_MAIN", 1, ruta="", tipo="OB"),
    ]
    _seed_cache(app_cache, "PLC_1", blocks)
    tia_client = _make_tia_client(wrapper_present=True)
    fb = _make_fb(app_cache, tia_client, real_progress)

    dispatch_mock = _make_dispatch_mock(
        ok=True, success=True, operations_executed=3,
        details=[{"step": i + 1, "command": "update_block_property"}
                 for i in range(3)],
    )
    scan_mock = _make_scan_mock(n_blocks=3)

    with patch(
        "core.composition.function_block_edit_apply.dispatch_batch_async",
        new=dispatch_mock,
    ), patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        started = asyncio.run(fb.start(
            plc_name="PLC_1",
            edits={
                "DB2000_ED": {"number": 2001},
                "FC2000_ZC_ED": {"name": "FC2000_ZC_ED_NEW"},
                "OB1_MAIN": {"name": "OB1_MOD"},
            },
        ))
        assert started is True
        _drive_fb_to_done(fb)

    assert fb.nStep == fb.n_done
    assert fb.error_msg is None
    assert fb.result is not None
    assert fb.result["ok"] is True
    assert fb.result["plc_name"] == "PLC_1"
    assert fb.result["n_ops"] == 3
    assert fb.result["operations_executed"] == 3
    assert fb.result["no_op"] is False

    # dispatch_batch_async recibio 3 ops, todas ``update_block_property``.
    assert dispatch_mock.await_count == 1
    args, _ = dispatch_mock.call_args
    ops = args[1]  # positional: tia_client, ops, timeout_s
    assert len(ops) == 3
    for op in ops:
        assert op["command"] == "update_block_property"
        assert op["args"]["plc_name"] == "PLC_1"
        assert op["args"]["property_name"] in ("Name", "Number")
        # El worker localiza el bloque por nombre: la ruta no viaja.
        assert set(op["args"].keys()) == {
            "plc_name", "block_name", "property_name", "new_value",
        }

    # Ops concretas (shape matching por pares property/value).
    pairs = sorted(
        (op["args"]["block_name"], op["args"]["property_name"],
         op["args"]["new_value"])
        for op in ops
    )
    assert pairs == [
        ("DB2000_ED", "Number", 2001),
        ("FC2000_ZC_ED", "Name", "FC2000_ZC_ED_NEW"),
        ("OB1_MAIN", "Name", "OB1_MOD"),
    ]

    # scan_plc_blocks se llamo con force_refresh=True.
    scan_args, scan_kwargs = scan_mock.call_args
    assert scan_args[0] == "PLC_1"
    assert scan_kwargs.get("force_refresh") is True
    assert scan_kwargs.get("tia_client") is tia_client
    assert scan_kwargs.get("app_cache") is app_cache

    # El cache de prepare quedo limpio tras refresh_cache.
    assert app_cache.get_block_edit_prepared("PLC_1") == {}


# ── 2. No-op: cambios que ya coinciden con cache ───────────────────


def test_apply_no_op_when_no_changes(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """Edits identicos al cache -> sin dispatch, ``no_op=True``."""
    blocks = [_make_dto("DB2000_ED", 2000)]
    _seed_cache(app_cache, "PLC_1", blocks)
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    dispatch_mock = _make_dispatch_mock()
    scan_mock = _make_scan_mock()

    with patch(
        "core.composition.function_block_edit_apply.dispatch_batch_async",
        new=dispatch_mock,
    ), patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        asyncio.run(fb.start(
            plc_name="PLC_1",
            edits={"DB2000_ED": {"number": 2000}},  # mismo que cache
        ))
        _drive_fb_to_done(fb)

    assert fb.nStep == fb.n_done
    assert fb.result["no_op"] is True
    assert fb.result["n_ops"] == 0
    assert fb.result["operations_executed"] == 0
    assert dispatch_mock.await_count == 0  # NO se llamo


# ── 3. Mixto: 5 bloques, 2 sin cambios, 3 con cambios ──────────────


def test_apply_mixed_some_changes_some_no_changes(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """5 bloques en cache, edits cambian 3 -> 3 ops."""
    blocks = [
        _make_dto(f"BLOCK_{i}", 1000 + i, tipo="DB")
        for i in range(5)
    ]
    _seed_cache(app_cache, "PLC_1", blocks)
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    dispatch_mock = _make_dispatch_mock(
        ok=True, success=True, operations_executed=3,
    )
    scan_mock = _make_scan_mock(n_blocks=5)

    with patch(
        "core.composition.function_block_edit_apply.dispatch_batch_async",
        new=dispatch_mock,
    ), patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        asyncio.run(fb.start(
            plc_name="PLC_1",
            edits={
                "BLOCK_0": {"number": 1000},     # mismo -> skip
                "BLOCK_1": {"number": 9999},     # cambia
                "BLOCK_2": {"number": 1002},     # mismo -> skip
                "BLOCK_3": {"name": "BLOCK_3_NEW"},  # cambia
                "BLOCK_4": {"name": "BLOCK_4_NEW"},  # cambia
            },
        ))
        _drive_fb_to_done(fb)

    assert fb.nStep == fb.n_done
    assert fb.result["n_ops"] == 3
    assert fb.result["operations_executed"] == 3

    args, _ = dispatch_mock.call_args
    ops = args[1]
    assert len(ops) == 3
    block_names = sorted(op["args"]["block_name"] for op in ops)
    assert block_names == ["BLOCK_1", "BLOCK_3", "BLOCK_4"]


# ── 4. Rollback simulado: batch retorna success=False ───────────────


def test_apply_rollback_when_batch_returns_success_false(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """Worker OT reporta ``success=False`` -> FB raise con error claro."""
    blocks = [_make_dto("DB2000_ED", 2000)]
    _seed_cache(app_cache, "PLC_1", blocks)
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    dispatch_mock = _make_dispatch_mock(
        ok=True, success=False, operations_executed=0,
        error="rollback: Number colisiona con DB2001",
    )
    scan_mock = _make_scan_mock()

    with patch(
        "core.composition.function_block_edit_apply.dispatch_batch_async",
        new=dispatch_mock,
    ), patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        asyncio.run(fb.start(
            plc_name="PLC_1",
            edits={"DB2000_ED": {"number": 2001}},
        ))
        _drive_fb_to_done(fb)

    # El FB cae en n_error con mensaje que mencione el rollback.
    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "success=False" in fb.error_msg or "rollback" in fb.error_msg

    # scan_plc_blocks NO se invoca tras el rollback.
    assert scan_mock.call_count == 0


# ── 5. edits contiene key no permitida -> ValueError ────────────────


def test_apply_raises_when_edits_contains_disallowed_field(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``edits=[...]['title']`` -> ``ValueError`` fail-fast en ``on_start``."""
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    asyncio.run(fb.start(
        plc_name="PLC_1",
        edits={"DB2000_ED": {"title": "MLC_NEW"}},
    ))
    asyncio.run(fb.tick())

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    # Mensaje debe mencionar la key prohibida.
    assert "title" in fb.error_msg
    # Y opcionalmente la whitelist valida.
    assert "no permitida" in fb.error_msg or "permitidas" in fb.error_msg


# ── 6. PLC no en cache de prepare -> RuntimeError ───────────────────


def test_apply_raises_when_plc_not_in_prepared_cache(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """PLC con cache de otro nombre -> raise mencionando ``block_edit_prepare``."""
    blocks = [_make_dto("DB2000_ED", 2000)]
    _seed_cache(app_cache, "PLC_OTHER", blocks)
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    dispatch_mock = _make_dispatch_mock()
    scan_mock = _make_scan_mock()

    with patch(
        "core.composition.function_block_edit_apply.dispatch_batch_async",
        new=dispatch_mock,
    ), patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        asyncio.run(fb.start(
            plc_name="PLC_1",  # no es PLC_OTHER
            edits={"DB2000_ED": {"number": 2001}},
        ))
        _drive_fb_to_done(fb)

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    msg = fb.error_msg.lower()
    assert ("no preparado" in msg
            or "no esta" in msg
            or "block_edit_prepare" in fb.error_msg)

    # Sin dispatch ni scan.
    assert dispatch_mock.await_count == 0


# ── 7. tia_client=None -> RuntimeError en el primer step ────────────


def test_apply_requires_tia_client(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``tia_client=None`` -> primer step run_step raise ``RuntimeError``."""
    blocks = [_make_dto("DB2000_ED", 2000)]
    _seed_cache(app_cache, "PLC_1", blocks)
    fb = _make_fb(app_cache, None, real_progress)

    asyncio.run(fb.start(
        plc_name="PLC_1",
        edits={"DB2000_ED": {"number": 2001}},
    ))

    # tick #1: arrancar -> ejecutar (on_start pasa).
    asyncio.run(fb.tick())
    assert fb.nStep == fb.n_ejecutar

    # tick #2: ``validar`` dispara el check de tia_client.
    asyncio.run(fb.tick())

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "requiere tia_client" in fb.error_msg
