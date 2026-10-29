"""Tests del FB core ``FunctionBlockEditApply``.

Cubre el camino de ejecucion sync del OB1 (``fb.execute(**params)``),
que es el que usa el dispatcher: ``on_start`` -> ``run_step`` x N ->
``on_finish``, sin event loop.

Casos cubiertos:

  - Happy path: 3 bloques con cambios Name+Number -> 3 ops en batch.
  - No-op: edits que coinciden 1:1 con el cache -> sin dispatch.
  - Mixto: 5 bloques en cache, 3 con cambios, 2 sin cambios -> 3 ops.
  - Rollback simulado: batch retorna ``success=False`` -> FB a ``n_error``.
  - ``edits`` con key no permitida (``"title"``) -> ``n_error`` en el
    pre-flight.
  - PLC sin cache de prepare -> ``n_error`` con mensaje claro.
  - ``tia_client=None`` -> ``n_error`` en el primer step.
  - ``run_step`` es sync (contrato del hilo OB1) y ``execute()`` completa
    el FB sin event loop.

En el camino sync las excepciones de runtime no se propagan: el FB las
captura, fija ``error_msg`` con el formato ``"<TipoError>: <mensaje>"`` y
transiciona a ``n_error``. Por eso los asserts de error se apoyan en
``fb.nStep == fb.n_error`` y en el contenido de ``fb.error_msg``.

Mockeamos:

  - ``tia_client.submit_and_wait`` con ``MagicMock`` que devuelve la
    shape del worker OT (el FB es sync: llama al worker OT directamente,
    sin event loop).
  - ``core.composition.function_block_edit_apply.scan_plc_blocks``
    con ``MagicMock`` que devuelve un cache mock con ``.blocks``
    (la funcion es sync).

Usamos ``AppCache`` real + ``ProgressTracker`` real (mismo patron que
el test del FB ``block_edit_prepare``) para verificar el flujo de
states y stages sin necesidad de mockear internals.
"""
from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

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


def _make_submit_and_wait_mock(
    ok: bool = True,
    success: bool = True,
    operations_executed: int = 0,
    details: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> MagicMock:
    """Mock de ``tia_client.submit_and_wait`` con la shape del worker OT."""
    inner: dict[str, Any] = {
        "success": success,
        "operations_executed": operations_executed,
        "details": details or [],
    }
    if error is not None:
        inner["error"] = error
    return MagicMock(return_value={"ok": ok, "result": inner})


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


# ── 1. Happy path: 3 bloques, 3 ops ───────────────────────────────


def test_apply_execute_happy_path_3_blocks(
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

    submit_mock = _make_submit_and_wait_mock(
        ok=True, success=True, operations_executed=3,
        details=[{"step": i + 1, "command": "update_block_property"}
                 for i in range(3)],
    )
    tia_client.submit_and_wait = submit_mock
    scan_mock = _make_scan_mock(n_blocks=3)

    with patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        fb.execute(
            plc_name="PLC_1",
            edits={
                "DB2000_ED": {"number": 2001},
                "FC2000_ZC_ED": {"name": "FC2000_ZC_ED_NEW"},
                "OB1_MAIN": {"name": "OB1_MOD"},
            },
        )

    assert fb.nStep == fb.n_done
    assert fb.error_msg is None
    assert fb.result is not None
    assert fb.result["ok"] is True
    assert fb.result["plc_name"] == "PLC_1"
    assert fb.result["n_ops"] == 3
    assert fb.result["operations_executed"] == 3
    assert fb.result["no_op"] is False

    # submit_and_wait recibio 1 batch transaccional con 3 ops, todas
    # ``update_block_property``.
    assert submit_mock.call_count == 1
    args, kwargs = submit_mock.call_args
    assert args[0] == "execute_transactional_batch"
    ops = args[1]["operations"]
    assert kwargs.get("timeout") == fb.STEP_TIMEOUT_S
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


def test_apply_execute_no_op_when_no_changes(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """Edits identicos al cache -> sin dispatch, ``no_op=True``."""
    blocks = [_make_dto("DB2000_ED", 2000)]
    _seed_cache(app_cache, "PLC_1", blocks)
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    submit_mock = _make_submit_and_wait_mock()
    tia_client.submit_and_wait = submit_mock
    scan_mock = _make_scan_mock()

    with patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        fb.execute(
            plc_name="PLC_1",
            edits={"DB2000_ED": {"number": 2000}},  # mismo que cache
        )

    assert fb.nStep == fb.n_done
    assert fb.error_msg is None
    assert fb.result["no_op"] is True
    assert fb.result["n_ops"] == 0
    assert fb.result["operations_executed"] == 0
    assert submit_mock.call_count == 0  # NO se llamo


# ── 3. Mixto: 5 bloques, 2 sin cambios, 3 con cambios ──────────────


def test_apply_execute_mixed_some_changes_some_no_changes(
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

    submit_mock = _make_submit_and_wait_mock(
        ok=True, success=True, operations_executed=3,
    )
    tia_client.submit_and_wait = submit_mock
    scan_mock = _make_scan_mock(n_blocks=5)

    with patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        fb.execute(
            plc_name="PLC_1",
            edits={
                "BLOCK_0": {"number": 1000},     # mismo -> skip
                "BLOCK_1": {"number": 9999},     # cambia
                "BLOCK_2": {"number": 1002},     # mismo -> skip
                "BLOCK_3": {"name": "BLOCK_3_NEW"},  # cambia
                "BLOCK_4": {"name": "BLOCK_4_NEW"},  # cambia
            },
        )

    assert fb.nStep == fb.n_done
    assert fb.error_msg is None
    assert fb.result["n_ops"] == 3
    assert fb.result["operations_executed"] == 3

    args, _ = submit_mock.call_args
    ops = args[1]["operations"]
    assert len(ops) == 3
    block_names = sorted(op["args"]["block_name"] for op in ops)
    assert block_names == ["BLOCK_1", "BLOCK_3", "BLOCK_4"]


# ── 4. Rollback simulado: batch retorna success=False ───────────────


def test_apply_execute_rollback_when_batch_returns_success_false(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """Worker OT reporta ``success=False`` -> FB a ``n_error``."""
    blocks = [_make_dto("DB2000_ED", 2000)]
    _seed_cache(app_cache, "PLC_1", blocks)
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    submit_mock = _make_submit_and_wait_mock(
        ok=True, success=False, operations_executed=0,
        error="rollback: Number colisiona con DB2001",
    )
    tia_client.submit_and_wait = submit_mock
    scan_mock = _make_scan_mock()

    with patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        fb.execute(
            plc_name="PLC_1",
            edits={"DB2000_ED": {"number": 2001}},
        )

    # El FB cae en n_error con mensaje que mencione el rollback.
    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "success=False" in fb.error_msg or "rollback" in fb.error_msg

    # scan_plc_blocks NO se invoca tras el rollback.
    assert scan_mock.call_count == 0


# ── 5. edits contiene key no permitida -> n_error ──────────────────


def test_apply_execute_fails_when_edits_contains_disallowed_field(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``edits=[...]['title']`` -> ``n_error`` fail-fast en el pre-flight."""
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    fb.execute(
        plc_name="PLC_1",
        edits={"DB2000_ED": {"title": "MLC_NEW"}},
    )

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    # Mensaje debe mencionar la key prohibida.
    assert "title" in fb.error_msg
    # Y opcionalmente la whitelist valida.
    assert "no permitida" in fb.error_msg or "permitidas" in fb.error_msg


# ── 6. PLC no en cache de prepare -> n_error ───────────────────────


def test_apply_execute_fails_when_plc_not_in_prepared_cache(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """PLC con cache de otro nombre -> ``n_error`` mencionando
    ``block_edit_prepare``."""
    blocks = [_make_dto("DB2000_ED", 2000)]
    _seed_cache(app_cache, "PLC_OTHER", blocks)
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    submit_mock = _make_submit_and_wait_mock()
    tia_client.submit_and_wait = submit_mock
    scan_mock = _make_scan_mock()

    with patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        fb.execute(
            plc_name="PLC_1",  # no es PLC_OTHER
            edits={"DB2000_ED": {"number": 2001}},
        )

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    msg = fb.error_msg.lower()
    assert ("no preparado" in msg
            or "no esta" in msg
            or "block_edit_prepare" in fb.error_msg)

    # Sin dispatch ni scan.
    assert submit_mock.call_count == 0


# ── 7. tia_client=None -> n_error en el primer step ───────────────


def test_apply_execute_fails_when_tia_client_missing(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``tia_client=None`` -> el primer step falla y el FB va a
    ``n_error``."""
    blocks = [_make_dto("DB2000_ED", 2000)]
    _seed_cache(app_cache, "PLC_1", blocks)
    fb = _make_fb(app_cache, None, real_progress)

    fb.execute(
        plc_name="PLC_1",
        edits={"DB2000_ED": {"number": 2001}},
    )

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "requiere tia_client" in fb.error_msg


# ── 8. Contrato sync para el hilo del OB1 ─────────────────────────


def test_apply_run_step_is_not_a_coroutine() -> None:
    """``run_step`` es sync: el hilo del OB1 lo invoca sin event loop."""
    assert not inspect.iscoroutinefunction(FunctionBlockEditApply.run_step)


def test_apply_executes_via_sync_ob1_path(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``execute()`` (camino sync del OB1) completa el FB de punta a punta."""
    blocks = [_make_dto("DB2000_ED", 2000)]
    _seed_cache(app_cache, "PLC_1", blocks)
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    submit_mock = _make_submit_and_wait_mock(
        ok=True, success=True, operations_executed=1,
    )
    tia_client.submit_and_wait = submit_mock
    scan_mock = _make_scan_mock(n_blocks=1)

    with patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=scan_mock,
    ):
        fb.execute(
            plc_name="PLC_1",
            edits={"DB2000_ED": {"number": 2001}},
        )

    assert fb.nStep == fb.n_done
    assert fb.error_msg is None
    assert fb.result is not None
    assert fb.result["ok"] is True
    assert fb.result["n_ops"] == 1
    assert fb.result["operations_executed"] == 1
    assert fb.result["no_op"] is False

    # El worker OT se llamo una vez, con el batch transaccional.
    assert submit_mock.call_count == 1
    args, kwargs = submit_mock.call_args
    assert args[0] == "execute_transactional_batch"
    assert len(args[1]["operations"]) == 1
    assert kwargs.get("timeout") == fb.STEP_TIMEOUT_S
