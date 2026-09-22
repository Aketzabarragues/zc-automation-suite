"""Tests de error paths de _h_compile_blocks (Fase 4 / paso 4.1.2b2a).

Tests de happy paths van en test_tia_client_compile_blocks_happy.py (4.1.2b2b).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia.tia_loop import (
    SyncTIAClient)
from core.infrastructure.tia.tia_commands_catalog import register_all_commands


def _client():
    c = SyncTIAClient()
    register_all_commands(c)
    return c


def test_compile_blocks_requires_attached_portal():
    out = _client().dispatch(
        "compile_blocks", {"plc_name": "PLC_1", "block_names": ["DB1"]}
    )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_compile_blocks_requires_plc_name():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch("compile_blocks", {"block_names": ["DB1"]})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_compile_blocks_requires_non_empty_block_names():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch("compile_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "block_names" in out["error"]


def test_compile_blocks_rejects_empty_list():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch(
        "compile_blocks", {"plc_name": "PLC_1", "block_names": []}
    )
    assert out["ok"] is False
    assert "block_names" in out["error"]


def test_compile_blocks_raises_when_plc_not_found():
    other = MagicMock(spec=["get_name"])
    other.get_name.return_value = "PLC_OTHER"
    project = MagicMock()
    project.get_plcs.return_value = [other]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "compile_blocks", {"plc_name": "PLC_99", "block_names": ["DB1"]}
    )
    assert out["ok"] is False
    assert "No se encontro ningun PLC" in out["error"]
