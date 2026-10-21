"""Recuperacion del state machine de ``SyncTIAClient`` tras un fallo.

Cubren que un comando de operacion posterior a un handler que falla
puede devolver el estado a ``STATE_CONNECTED``.
"""
from __future__ import annotations

import queue
from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia.tia_loop import (
    STATE_CONNECTED,
    STATE_ERROR,
    SyncTIAClient,
    _execute_one,
)


@pytest.fixture
def client() -> SyncTIAClient:
    c = SyncTIAClient()
    wrapper = MagicMock()
    wrapper.get_process_id.return_value = 1234
    c.attach_wrapper(wrapper)
    c._set_state(STATE_CONNECTED)
    return c


def test_execute_one_recovers_to_connected_after_handler_failure(
    client: SyncTIAClient,
) -> None:
    def fail(args, _c):  # noqa: ARG001
        raise ValueError("simulated handler failure")

    def succeed(args, _c):  # noqa: ARG001
        return {"echoed": args}

    client.register_command("fail", fail)
    client.register_command("succeed", succeed)

    resp_q_a: queue.Queue = queue.Queue(maxsize=1)
    _execute_one(client, "fail", {}, resp_q_a)
    result_a = resp_q_a.get_nowait()
    assert result_a.get("ok") is False
    assert client.state == STATE_ERROR

    resp_q_b: queue.Queue = queue.Queue(maxsize=1)
    _execute_one(client, "succeed", {}, resp_q_b)
    result_b = resp_q_b.get_nowait()
    assert result_b == {"ok": True, "result": {"echoed": {}}}
    assert client.state == STATE_CONNECTED
