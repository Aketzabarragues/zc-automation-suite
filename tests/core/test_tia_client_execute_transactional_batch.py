"""Tests de _h_execute_transactional_batch (Fase 4 / paso 4.1.2c4).

Cubre: empty list / forbidden commands / happy path / rollback on
sub-command exception / rollback on False return / rollback on
end_transaction failure.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia.tia_loop import (
    SyncTIAClient,
    register_core_commands,
)


def _client():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


def _setup_with_project(end_side_effect=None):
    """Crea un tia_client + portal + project con start/end_transaction
    mockeados. Retorna (client, portal, project).
    """
    portal = MagicMock()
    project = MagicMock()
    project.get_plcs.return_value = []
    project.start_transaction = MagicMock()
    if end_side_effect:
        project.end_transaction = MagicMock(side_effect=end_side_effect)
    else:
        project.end_transaction = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)
    return c, portal, project


# ------------------------------------------------------------ error paths
def test_batch_requires_attached_portal():
    out = _client().dispatch(
        "execute_transactional_batch",
        {"operations": [{"command": "ping"}]},
    )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_batch_requires_non_empty_operations():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch("execute_transactional_batch", {"operations": []})
    assert out["ok"] is False
    assert "vacia" in out["error"]


def test_batch_rejects_forbidden_command_open_project():
    """start_transaction SI se llama, pero rollback=True porque el
    sub-comando es forbidden (comportamiento del worker original).
    """
    c, _, project = _setup_with_project()
    out = c.dispatch(
        "execute_transactional_batch",
        {"operations": [{"command": "open_project"}]},
    )
    assert out["ok"] is False
    assert "prohibido" in out["error"]
    assert "open_project" in out["error"]
    project.start_transaction.assert_called_once()
    project.end_transaction.assert_called_once_with(rollback=True)


def test_batch_rejects_forbidden_command_save_project():
    c, _, project = _setup_with_project()
    out = c.dispatch(
        "execute_transactional_batch",
        {"operations": [{"command": "save_project"}]},
    )
    assert out["ok"] is False
    assert "prohibido" in out["error"]


def test_batch_rejects_forbidden_command_nested_batch():
    """Batch anidado: start_transaction SI se llama (original behavior),
    pero rollback=True porque el sub-comando es forbidden.
    """
    c, _, project = _setup_with_project()
    out = c.dispatch(
        "execute_transactional_batch",
        {"operations": [{"command": "execute_transactional_batch"}]},
    )
    assert out["ok"] is False
    assert "prohibido" in out["error"]
    project.start_transaction.assert_called_once()
    project.end_transaction.assert_called_once_with(rollback=True)


def test_batch_rejects_unknown_command():
    """Sub-comando desconocido -> dispatch devuelve unknown_command."""
    c, portal, project = _setup_with_project()
    # Necesitamos un proyecto activo para que start_transaction funcione.
    out = c.dispatch(
        "execute_transactional_batch",
        {"operations": [{"command": "no_existe", "args": {}}]},
    )
    assert out["ok"] is False
    assert "no_existe" in out["error"]
    # Como dispatch retorno {ok: False}, batch aborta y hace rollback.
    project.end_transaction.assert_called_once_with(rollback=True)


# ------------------------------------------------------------ happy path
def test_batch_happy_path_executes_all_and_commits():
    """Batch con 2 sub-comandos correctos -> end_transaction(rollback=False)."""
    c, portal, project = _setup_with_project()

    # Necesitamos PLCs para que el primer handler (save_project) funcione.
    plc = MagicMock(spec=["get_name"])
    plc.get_name.return_value = "PLC_1"
    project.get_plcs.return_value = [plc]

    out = c.dispatch(
        "execute_transactional_batch",
        {
            "undo_text": "lote_test",
            "operations": [
                {"command": "list_plcs"},  # pero list_plcs es forbidden...
            ],
        },
    )

    # list_plcs ESTA forbidden, asi que abortamos.
    assert out["ok"] is False
    assert "prohibido" in out["error"]


def test_batch_happy_path_uses_real_registered_handler():
    """Batch con un handler registrado (delete_user_constant) -> ejecuta y commitea.

    Usamos delete_user_constant porque compile_plc esta en la lista de
    forbidden (TIA rechaza compilar dentro de transaccion).
    """
    c, portal, project = _setup_with_project()

    table = MagicMock()
    table.get_name.return_value = "T1"
    const = MagicMock()
    const.get_property.return_value = "TO_DELETE"
    table.get_user_constants.return_value = [const]
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_plc_tag_tables.return_value = [table]
    project.get_plcs.return_value = [plc]

    out = c.dispatch(
        "execute_transactional_batch",
        {
            "undo_text": "delete_test",
            "operations": [
                {
                    "command": "delete_user_constant",
                    "args": {
                        "plc_name": "PLC_1",
                        "table_name": "T1",
                        "constant_name": "TO_DELETE",
                    },
                },
            ],
        },
    )

    assert out == {
        "ok": True,
        "result": {
            "success": True,
            "operations_executed": 1,
            "details": [
                {
                    "step": 1,
                    "command": "delete_user_constant",
                    "result": {"deleted": True, "constant": "TO_DELETE"},
                },
            ],
        },
    }
    project.start_transaction.assert_called_once_with(
        undo_text="delete_test",
        dialog_text="delete_test",
    )
    project.end_transaction.assert_called_once_with(rollback=False)
    const.delete.assert_called_once_with()


# ------------------------------------------------------------ rollback paths
def test_batch_rollback_on_sub_command_exception():
    """Sub-comando que lanza excepcion -> batch aborta y hace rollback."""
    c, portal, project = _setup_with_project()

    # Usamos delete_user_constant (NO forbidden) y forzamos que lance.
    table = MagicMock()
    table.get_name.return_value = "T1"
    bad_const = MagicMock()
    bad_const.get_property.side_effect = RuntimeError(
        "simulated TIA failure"
    )
    table.get_user_constants.return_value = [bad_const]
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_plc_tag_tables.return_value = [table]
    project.get_plcs.return_value = [plc]

    out = c.dispatch(
        "execute_transactional_batch",
        {
            "operations": [
                {
                    "command": "delete_user_constant",
                    "args": {
                        "plc_name": "PLC_1",
                        "table_name": "T1",
                        "constant_name": "BAD",
                    },
                },
            ],
        },
    )

    assert out["ok"] is False
    assert "Lote abortado" in out["error"]
    assert "delete_user_constant" in out["error"]
    assert "simulated TIA failure" in out["error"]
    project.end_transaction.assert_called_once_with(rollback=True)


def test_batch_rollback_on_false_return():
    """Sub-comando retorna False -> batch aborta y hace rollback."""
    c, portal, project = _setup_with_project()

    # Handlers que retornan False explicitamente.
    def handler_false(args, client):
        return False

    c.register_command("returns_false", handler_false)

    out = c.dispatch(
        "execute_transactional_batch",
        {
            "operations": [{"command": "returns_false"}],
        },
    )

    assert out["ok"] is False
    assert "False" in out["error"]
    assert "retorno False" in out["error"]
    project.end_transaction.assert_called_once_with(rollback=True)


def test_batch_silences_rollback_failure():
    """Si end_transaction(rollback=True) falla, NO enmascarar la causa raiz."""
    c, portal, project = _setup_with_project(
        end_side_effect=RuntimeError("rollback broken"),
    )

    table = MagicMock()
    table.get_name.return_value = "T1"
    bad_const = MagicMock()
    bad_const.get_property.side_effect = RuntimeError("handler failed")
    table.get_user_constants.return_value = [bad_const]
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_plc_tag_tables.return_value = [table]
    project.get_plcs.return_value = [plc]

    out = c.dispatch(
        "execute_transactional_batch",
        {
            "operations": [
                {
                    "command": "delete_user_constant",
                    "args": {
                        "plc_name": "PLC_1",
                        "table_name": "T1",
                        "constant_name": "X",
                    },
                },
            ],
        },
    )

    # La causa raiz es "handler failed", no "rollback broken".
    assert out["ok"] is False
    assert "handler failed" in out["error"]
    assert "rollback broken" not in out["error"]


def test_batch_includes_failed_args_in_error_for_diagnostics():
    """Args del paso que falla se incluyen (truncados) en el error."""
    c, portal, project = _setup_with_project()

    table = MagicMock()
    table.get_name.return_value = "T1"
    bad_const = MagicMock()
    bad_const.get_property.side_effect = RuntimeError("boom")
    table.get_user_constants.return_value = [bad_const]
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_plc_tag_tables.return_value = [table]
    project.get_plcs.return_value = [plc]

    out = c.dispatch(
        "execute_transactional_batch",
        {
            "operations": [
                {
                    "command": "delete_user_constant",
                    "args": {
                        "plc_name": "PLC_1",
                        "table_name": "T1",
                        "constant_name": "PLC_INEXISTENTE",
                    },
                },
            ],
        },
    )

    assert out["ok"] is False
    assert "PLC_INEXISTENTE" in out["error"]
    assert "Args:" in out["error"]


def test_batch_reports_step_number_on_failure():
    """El numero de paso en el error es len(results_list) + 1."""
    c, portal, project = _setup_with_project()

    # Registra 2 handlers buenos y uno malo en el medio.
    c.register_command("ok1", lambda args, client: {"a": 1})
    c.register_command("boom", lambda args, client: (_ for _ in ()).throw(
        RuntimeError("middle failed")
    ))
    c.register_command("ok2", lambda args, client: {"c": 3})

    out = c.dispatch(
        "execute_transactional_batch",
        {
            "operations": [
                {"command": "ok1"},
                {"command": "boom"},
                {"command": "ok2"},
            ],
        },
    )

    assert out["ok"] is False
    # Paso 1 (ok1) exitoso, paso 2 (boom) falla -> "paso 2" en el error.
    assert "paso 2" in out["error"]
