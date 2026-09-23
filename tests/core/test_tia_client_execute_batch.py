"""Tests de _h_execute_batch (modo read-only, sin transaccion).

Cubre: empty list / sin portal / happy path / best-effort ante
excepciones / best-effort ante False / nesting rechazado / _wait
valido / start/end_transaction NO se llaman.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia.tia_loop import SyncTIAClient
from core.infrastructure.tia.tia_commands_catalog import register_all_commands


def _client():
    c = SyncTIAClient()
    register_all_commands(c)
    return c


def _setup_with_portal():
    """Crea tia_client + portal + project (sin start/end_transaction
    mockeados: queremos verificar que NO se llaman)."""
    portal = MagicMock()
    project = MagicMock()
    project.get_plcs.return_value = []
    portal.get_project.return_value = project
    c = _client()
    c.attach_wrapper(portal)
    return c, portal, project


# ------------------------------------------------------------ error paths
def test_batch_requires_attached_portal():
    out = _client().dispatch(
        "execute_batch",
        {"operations": [{"command": "ping"}]},
    )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_batch_requires_non_empty_operations():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch("execute_batch", {"operations": []})
    assert out["ok"] is False
    assert "vacia" in out["error"]


def test_batch_rejects_nested_execute_batch():
    """execute_batch dentro de si mismo -> rechazado en su step."""
    c, _, project = _setup_with_portal()

    out = c.dispatch(
        "execute_batch",
        {"operations": [{"command": "execute_batch", "args": {}}]},
    )

    assert out["ok"] is True  # El lote como tal termina OK
    assert out["result"]["success"] is False
    assert out["result"]["operations_executed"] == 1
    assert out["result"]["operations_failed"] == 1
    details = out["result"]["details"]
    assert len(details) == 1
    assert details[0]["ok"] is False
    assert "nesting" in details[0]["error"]
    # CRITICO: NO se abrio ninguna transaccion (es read-only).
    project.start_transaction.assert_not_called()
    project.end_transaction.assert_not_called()


def test_batch_reports_unknown_command_in_details():
    """Sub-comando desconocido -> ok=False en su detail; el lote sigue."""
    c, _, project = _setup_with_portal()
    c.register_command("good_op", lambda args, client: {"a": 1})

    out = c.dispatch(
        "execute_batch",
        {
            "operations": [
                {"command": "no_existe"},
                {"command": "good_op"},
            ],
        },
    )

    assert out["ok"] is True
    assert out["result"]["success"] is False
    assert out["result"]["operations_executed"] == 2
    assert out["result"]["operations_failed"] == 1
    details = out["result"]["details"]
    assert details[0]["ok"] is False
    assert "no_existe" in details[0]["error"]
    assert details[1]["ok"] is True  # el segundo op SI se ejecuto
    project.end_transaction.assert_not_called()


def test_batch_reports_false_return_in_details():
    """Sub-comando retorna False -> se anota en details y se sigue."""
    c, _, project = _setup_with_portal()
    c.register_command("returns_false", lambda args, client: False)

    out = c.dispatch(
        "execute_batch",
        {"operations": [{"command": "returns_false"}]},
    )

    assert out["result"]["success"] is False
    assert out["result"]["operations_failed"] == 1
    details = out["result"]["details"]
    assert details[0]["ok"] is False
    assert "False" in details[0]["error"]
    project.end_transaction.assert_not_called()


def test_batch_swallows_exception_continues():
    """Sub-comando lanza excepcion -> el lote CONTINUA con los siguientes."""
    c, _, project = _setup_with_portal()
    c.register_command(
        "boom",
        lambda args, client: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    c.register_command("after_boom", lambda args, client: {"ok": "yes"})

    out = c.dispatch(
        "execute_batch",
        {
            "operations": [
                {"command": "boom"},
                {"command": "after_boom"},
            ],
        },
    )

    assert out["result"]["operations_executed"] == 2
    assert out["result"]["operations_failed"] == 1
    assert out["result"]["success"] is False
    details = out["result"]["details"]
    assert details[0]["ok"] is False
    assert "boom" in details[0]["error"]
    assert details[1]["ok"] is True
    project.start_transaction.assert_not_called()


# ------------------------------------------------------------ happy paths
def test_batch_happy_path_executes_all_with_registered_handler():
    """Batch con un handler registrado -> ejecuta y reporta ok."""
    c, _, project = _setup_with_portal()

    table = MagicMock()
    table.get_name.return_value = "T1"
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_plc_tag_tables.return_value = [table]
    project.get_plcs.return_value = [plc]

    # ``ping`` esta en el catalogo core.
    out = c.dispatch(
        "execute_batch",
        {"operations": [{"command": "ping"}]},
    )

    assert out["ok"] is True
    assert out["result"]["success"] is True
    assert out["result"]["operations_executed"] == 1
    assert out["result"]["operations_failed"] == 0
    details = out["result"]["details"]
    assert details[0]["step"] == 1
    assert details[0]["command"] == "ping"
    assert details[0]["ok"] is True
    # El handler ping retorna {"pid": N} (real); solo validamos el shape.
    assert isinstance(details[0]["result"], dict)
    # CRITICO: el modo read-only NO toca start/end_transaction.
    project.start_transaction.assert_not_called()
    project.end_transaction.assert_not_called()


def test_batch_executes_multiple_operations_in_order():
    """3 ops -> todas ejecutadas, details indexados por step."""
    c, _, project = _setup_with_portal()
    c.register_command("op1", lambda args, client: {"n": 1})
    c.register_command("op2", lambda args, client: {"n": 2})
    c.register_command("op3", lambda args, client: {"n": 3})

    out = c.dispatch(
        "execute_batch",
        {
            "operations": [
                {"command": "op1"},
                {"command": "op2"},
                {"command": "op3"},
            ],
        },
    )

    assert out["result"]["success"] is True
    assert out["result"]["operations_executed"] == 3
    assert out["result"]["operations_failed"] == 0
    details = out["result"]["details"]
    assert len(details) == 3
    assert details[0]["step"] == 1 and details[0]["result"] == {"n": 1}
    assert details[1]["step"] == 2 and details[1]["result"] == {"n": 2}
    assert details[2]["step"] == 3 and details[2]["result"] == {"n": 3}


def test_batch_wait_subcommand_executes_sleep():
    """``_wait`` es valido y produce un sleep bloqueante local."""
    c, _, project = _setup_with_portal()

    import time as _time
    sleeps: list[float] = []
    original_sleep = _time.sleep

    def fake_sleep(s):
        sleeps.append(s)
        return None

    _time.sleep = fake_sleep
    try:
        out = c.dispatch(
            "execute_batch",
            {"operations": [{"command": "_wait", "args": {"seconds": 0.05}}]},
        )
    finally:
        _time.sleep = original_sleep

    assert out["result"]["success"] is True
    assert sleeps == [0.05]
    assert out["result"]["details"][0]["command"] == "_wait"
    assert "sleep" in out["result"]["details"][0]["result"]
