"""Tests de ping y list_blocks (Fase 4 / paso 4.1.2a2a).

Separa estos tests del resto de inspection (4.1.2a3+) para mantener
<200 lineas por commit.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia_loop import (
    SyncTIAClient,
    register_core_commands,
)


def _client():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


# ------------------------------------------------------------ ping
def test_ping_without_portal_returns_error():
    out = _client().dispatch("ping", {})
    assert out == {"ok": False, "error": "RuntimeError: No hay portal attached"}


def test_ping_happy_path_returns_pid():
    portal = MagicMock()
    portal.get_process_id.return_value = 12345

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("ping", {})
    assert out == {"ok": True, "result": {"pid": 12345}}


def test_ping_propagates_com_exception_as_error():
    """TIA cerrado lanza COM/RPC; el dispatcher lo captura y reporta."""
    portal = MagicMock()

    class FakeCOMError(Exception):
        pass

    portal.get_process_id.side_effect = FakeCOMError("RCW disconnected")
    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("ping", {})
    assert out["ok"] is False
    assert "FakeCOMError" in out["error"]
    assert "RCW disconnected" in out["error"]


# ------------------------------------------------------------ list_blocks
def test_list_blocks_requires_attached_portal():
    out = _client().dispatch("list_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_list_blocks_requires_plc_name():
    portal = MagicMock()
    portal.get_project.return_value = MagicMock()
    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("list_blocks", {})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_list_blocks_raises_when_no_active_project():
    portal = MagicMock()
    portal.get_project.return_value = None
    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("list_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "No hay ningun proyecto abierto" in out["error"]


def test_list_blocks_happy_path():
    plc = MagicMock()
    block_a, block_b = MagicMock(), MagicMock()
    block_a.get_name.return_value = "OB1"
    block_b.get_name.return_value = "FB2"
    plc.get_program_blocks.return_value = [block_a, block_b]

    project = MagicMock()
    project.get_plcs.return_value = [plc]
    plc.get_name.return_value = "PLC_1"  # usado por _find_plc -> _safe_get_plc_name

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("list_blocks", {"plc_name": "PLC_1"})
    assert out == {
        "ok": True,
        "result": {"blocks": ["OB1", "FB2"], "plc_name": "PLC_1"},
    }
    plc.get_program_blocks.assert_called_once_with(folder_path="")


def test_list_blocks_passes_folder_path_when_provided():
    plc = MagicMock()
    plc.get_program_blocks.return_value = []
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    c.dispatch(
        "list_blocks",
        {"plc_name": "PLC_1", "folder_path": "SubFolder"},
    )
    plc.get_program_blocks.assert_called_once_with(folder_path="SubFolder")


def test_list_blocks_coerces_none_folder_path_to_empty_string():
    """TIA Portal V21: el wrapper .NET rechaza None; forzamos '' por compat."""
    plc = MagicMock()
    plc.get_program_blocks.return_value = []
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    c.dispatch("list_blocks", {"plc_name": "PLC_1", "folder_path": None})
    plc.get_program_blocks.assert_called_once_with(folder_path="")
