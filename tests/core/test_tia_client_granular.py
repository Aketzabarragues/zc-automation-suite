"""Tests de export_block (Fase 4 / paso 4.1.2c1a).

Tests de export_tag_table van en test_tia_client_granular_export_block.py
(commit 4.1.2c1b). Tests de import_tag_table van en
test_tia_client_granular_import.py (commit 4.1.2c1-import).
"""
from __future__ import annotations

import tempfile
from unittest.mock import MagicMock

from core.infrastructure.tia.tia_loop import (
    SyncTIAClient,
    register_core_commands,
)


def _client():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


def _block(nombre: str):
    b = MagicMock()
    b.get_name.return_value = nombre
    b.export = MagicMock()
    return b


def test_export_block_requires_attached_portal():
    with tempfile.TemporaryDirectory() as tmp:
        out = _client().dispatch(
            "export_block",
            {"plc_name": "PLC_1", "block_name": "DB1", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_export_block_requires_block_name():
    with tempfile.TemporaryDirectory() as tmp:
        c = _client()
        c.attach_wrapper(MagicMock())
        out = c.dispatch(
            "export_block",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "block_name" in out["error"]


def test_export_block_happy_path():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_program_blocks.return_value = [_block("DB1"), _block("DB2")]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_block",
            {"plc_name": "PLC_1", "block_name": "DB2", "target_dir": tmp},
        )

    assert out["ok"] is True
    assert out["result"]["block_name"] == "DB2"
    assert out["result"]["exported_to"] == tmp


def test_export_block_raises_when_block_not_found():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_program_blocks.return_value = [_block("DB1")]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_block",
            {"plc_name": "PLC_1", "block_name": "DB_FAKE", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "DB_FAKE" in out["error"]
    assert "no encontrado" in out["error"]


def test_export_block_skips_blocks_with_unicode_in_name():
    """Bloques con UnicodeDecodeError no se matchean (no explotan)."""
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"

    bad = MagicMock()
    bad.get_name.side_effect = UnicodeDecodeError("ascii", b"\xff", 0, 1, "x")
    bad.export = MagicMock()
    good = _block("DB_OK")

    plc.get_program_blocks.return_value = [bad, good]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_block",
            {"plc_name": "PLC_1", "block_name": "DB_OK", "target_dir": tmp},
        )
    assert out["ok"] is True
    bad.export.assert_not_called()
    good.export.assert_called_once()
