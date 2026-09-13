"""Tests de happy paths y defensive fallbacks de compile_blocks (4.1.2b2b).

Tests de error paths van en test_tia_client_compile_blocks.py (4.1.2b2a).
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


def _block_consistent(nombre: str):
    b = MagicMock(spec=["get_name", "is_consistent", "compile"])
    b.get_name.return_value = nombre
    b.is_consistent.return_value = True
    return b


def _block_inconsistent(nombre: str, had_errors: bool = False):
    b = MagicMock(spec=["get_name", "is_consistent", "compile"])
    b.get_name.return_value = nombre
    b.is_consistent.return_value = False
    b.compile.return_value = had_errors
    return b


def test_compile_blocks_happy_path_mixed_consistent_and_inconsistent():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_program_blocks.return_value = [
        _block_consistent("DB1"),
        _block_inconsistent("DB2", had_errors=False),
        _block_inconsistent("DB3", had_errors=True),
    ]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "compile_blocks",
        {"plc_name": "PLC_1", "block_names": ["DB1", "DB2", "DB3"]},
    )
    assert out == {
        "ok": True,
        "result": {
            "compiled": [
                {"name": "DB2", "had_errors": False, "was_inconsistent": True},
                {"name": "DB3", "had_errors": True, "was_inconsistent": True},
            ],
            "skipped_unchanged": ["DB1"],
            "not_found": [],
            "errors": [],
        },
    }


def test_compile_blocks_skips_not_found():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_program_blocks.return_value = [_block_inconsistent("DB2")]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "compile_blocks",
        {"plc_name": "PLC_1", "block_names": ["DB_FAKE", "DB2"]},
    )
    assert out == {
        "ok": True,
        "result": {
            "compiled": [{"name": "DB2", "had_errors": False, "was_inconsistent": True}],
            "skipped_unchanged": [],
            "not_found": ["DB_FAKE"],
            "errors": [],
        },
    }


def test_compile_blocks_captures_block_compile_exception():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"

    bad_block = MagicMock(spec=["get_name", "is_consistent", "compile"])
    bad_block.get_name.return_value = "DB_BAD"
    bad_block.is_consistent.return_value = False
    bad_block.compile.side_effect = RuntimeError("syntax error")

    plc.get_program_blocks.return_value = [bad_block]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "compile_blocks",
        {"plc_name": "PLC_1", "block_names": ["DB_BAD"]},
    )
    assert out == {
        "ok": True,
        "result": {
            "compiled": [],
            "skipped_unchanged": [],
            "not_found": [],
            "errors": [{"name": "DB_BAD", "error": "RuntimeError: syntax error"}],
        },
    }


def test_compile_blocks_is_consistent_exception_treated_as_inconsistent():
    """Si is_consistent() lanza (raro), asumimos inconsistente y compilamos."""
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"

    weird_block = MagicMock(spec=["get_name", "is_consistent", "compile"])
    weird_block.get_name.return_value = "DB_WEIRD"
    weird_block.is_consistent.side_effect = RuntimeError("weird COM transient")
    weird_block.compile.return_value = False

    plc.get_program_blocks.return_value = [weird_block]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "compile_blocks",
        {"plc_name": "PLC_1", "block_names": ["DB_WEIRD"]},
    )
    assert out == {
        "ok": True,
        "result": {
            "compiled": [{"name": "DB_WEIRD", "had_errors": False, "was_inconsistent": True}],
            "skipped_unchanged": [],
            "not_found": [],
            "errors": [],
        },
    }


def test_compile_blocks_handles_blocks_with_unicode_in_name():
    """Bloques con UnicodeDecodeError se omiten del index, no rompen."""
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"

    bad_name = MagicMock(spec=["get_name", "is_consistent", "compile"])
    bad_name.get_name.side_effect = UnicodeDecodeError("ascii", b"\xff", 0, 1, "x")
    good_block = _block_inconsistent("DB_OK")

    plc.get_program_blocks.return_value = [bad_name, good_block]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "compile_blocks",
        {"plc_name": "PLC_1", "block_names": ["DB_OK"]},
    )
    assert out["result"]["compiled"] == [
        {"name": "DB_OK", "had_errors": False, "was_inconsistent": True}
    ]
