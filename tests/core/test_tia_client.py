"""Tests unitarios de ``core.infrastructure.tia_loop.SyncTIAClient``.

Skeleton (Fase 4 / paso 4.1.1). Cubren:
  - register + dispatch + shape de retorno.
  - dispatch de comando desconocido -> error tipado.
  - register duplicado -> ValueError.
  - handler que lanza excepcion -> error capturado, no propagacion.
  - submit + dispatch_pending FIFO.
  - submit desde hilo distinto al del drain (thread-safety).
  - attach_wrapper + accessor.
  - has_command + registered_commands.
"""
from __future__ import annotations

import threading

import pytest

from core.infrastructure.tia.tia_loop import SyncTIAClient


def _new_client() -> SyncTIAClient:
    return SyncTIAClient()


def test_register_and_dispatch_returns_result() -> None:
    client = _new_client()
    client.register_command("ping", lambda args, _client: {"pong": True, "echoed": args})
    out = client.dispatch("ping", {"k": 1})
    assert out == {"ok": True, "result": {"pong": True, "echoed": {"k": 1}}}


def test_dispatch_unknown_command_returns_typed_error() -> None:
    client = _new_client()
    out = client.dispatch("nope")
    assert out == {"ok": False, "error": "unknown_command:nope"}


def test_register_duplicate_command_raises() -> None:
    client = _new_client()
    client.register_command("foo", lambda args, _client: {})
    try:
        client.register_command("foo", lambda args, _client: {})
    except ValueError as exc:
        assert "already registered" in str(exc)
        assert "foo" in str(exc)
    else:
        raise AssertionError("expected ValueError on duplicate register")


def test_dispatch_handler_exception_becomes_error_not_propagation() -> None:
    client = _new_client()

    def boom(args, _client):  # noqa: ARG001
        raise RuntimeError("exploto")

    client.register_command("boom", boom)
    out = client.dispatch("boom")
    assert out["ok"] is False
    assert "RuntimeError: exploto" in out["error"]


def test_dispatch_without_args_defaults_to_empty_dict() -> None:
    client = _new_client()
    client.register_command("noargs", lambda args, _client: {"got": args})
    out = client.dispatch("noargs")
    assert out == {"ok": True, "result": {"got": {}}}


@pytest.mark.skip(reason="obsoleto: submit() + dispatch_pending() eliminados al migrar a tia_loop")
def test_submit_then_dispatch_pending_drains_fifo() -> None:
    client = _new_client()
    captured: list[tuple[str, dict]] = []
    client.register_command(
        "echo",
        lambda args, _client: captured.append(("echo", args)) or {"echoed": args},
    )
    client.submit("echo", {"i": 1})
    client.submit("echo", {"i": 2})
    client.submit("echo", {"i": 3})
    processed = client.dispatch_pending()
    assert processed == 3
    assert [c[1] for c in captured] == [{"i": 1}, {"i": 2}, {"i": 3}]


@pytest.mark.skip(reason="obsoleto: idem")
def test_dispatch_pending_on_empty_queue_returns_zero() -> None:
    client = _new_client()
    assert client.dispatch_pending() == 0


@pytest.mark.skip(reason="obsoleto: idem")
def test_submit_from_another_thread_then_drain_is_fifo() -> None:
    client = _new_client()
    client.register_command("echo", lambda args, _client: args)

    def producer() -> None:
        for i in range(100):
            client.submit("echo", {"i": i})

    t = threading.Thread(target=producer, name="producer")
    t.start()
    t.join(timeout=2.0)
    assert not t.is_alive(), "producer thread hung"
    assert client.dispatch_pending() == 100


def test_attach_wrapper_and_accessor_returns_same_object() -> None:
    client = _new_client()
    sentinel = object()
    client.attach_wrapper(sentinel)
    assert client.wrapper is sentinel


def test_attach_ts_and_accessor_returns_same_object() -> None:
    client = _new_client()
    sentinel = object()
    client.attach_ts(sentinel)
    assert client.ts is sentinel


def test_wrapper_defaults_to_none_until_attached() -> None:
    client = _new_client()
    assert client.wrapper is None


def test_ts_defaults_to_none_until_attached() -> None:
    client = _new_client()
    assert client.ts is None


def test_dispatcher_passes_client_as_second_arg_to_handler() -> None:
    """El handler recibe (args, client). Verifica que `client` es la instancia."""
    client = _new_client()
    received: list = []

    def capture(args, c):
        received.append((args, c))
        return {"ok": True}

    client.register_command("cap", capture)
    client.dispatch("cap", {"x": 1})
    assert received == [({"x": 1}, client)]


def test_has_command_true_for_registered_false_otherwise() -> None:
    client = _new_client()
    client.register_command("a", lambda args, _client: {})
    client.register_command("b", lambda args, _client: {})
    assert client.has_command("a") is True
    assert client.has_command("b") is True
    assert client.has_command("c") is False


def test_registered_commands_returns_sorted_list() -> None:
    client = _new_client()
    client.register_command("z", lambda args, _client: {})
    client.register_command("a", lambda args, _client: {})
    client.register_command("m", lambda args, _client: {})
    assert client.registered_commands() == ["a", "m", "z"]


def test_dispatch_isolated_instances_have_independent_registries() -> None:
    """Dos SyncTIAClient no comparten handlers; singleton != obligatorio."""
    a, b = _new_client(), _new_client()
    a.register_command("only_in_a", lambda args, _client: {"a": True})
    assert a.has_command("only_in_a") is True
    assert b.has_command("only_in_a") is False
    assert b.dispatch("only_in_a") == {
        "ok": False,
        "error": "unknown_command:only_in_a",
    }
