"""Tests de error paths de _h_scan_blocks (Fase 4 / paso 4.1.2a5c1).

Tests de happy paths / defensive fallbacks van en
test_tia_client_scan_blocks_happy.py (commit 4.1.2a5c2).
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


def test_scan_blocks_requires_attached_portal():
    out = _client().dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_scan_blocks_requires_plc_name():
    out = _client().dispatch("scan_blocks", {})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_scan_blocks_raises_when_no_active_project():
    portal = MagicMock()
    portal.get_project.return_value = None
    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "No hay ningun proyecto abierto" in out["error"]


def test_scan_blocks_raises_when_plc_not_found():
    plc_a = MagicMock(spec=["get_name"])
    plc_a.get_name.return_value = "PLC_OTHER"

    project = MagicMock()
    project.get_plcs.return_value = [plc_a]

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_99"})
    assert out["ok"] is False
    assert "No se encontro ningun PLC" in out["error"]
