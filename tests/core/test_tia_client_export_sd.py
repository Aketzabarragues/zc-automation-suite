"""Tests de export_blocks_sd + export_udts_sd (Fase 4 / paso 4.1.2b3-handlers).

Tests de los helpers (_ensure_target_dir, _export_objects_sd) van en
test_tia_client_export_sd_helpers.py (4.1.2b3-helpers).
"""
from __future__ import annotations

import tempfile
from unittest.mock import MagicMock

from core.infrastructure.tia_loop import (
    SyncTIAClient,
    register_core_commands,
)


def _client():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


def _block():
    b = MagicMock()
    b.export = MagicMock()
    return b


# ------------------------------------------------------------ export_blocks_sd
def test_export_blocks_sd_requires_attached_portal():
    with tempfile.TemporaryDirectory() as tmp:
        out = _client().dispatch(
            "export_blocks_sd",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_export_blocks_sd_requires_plc_name():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch("export_blocks_sd", {"target_dir": "/tmp/x"})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_export_blocks_sd_raises_when_plc_not_found():
    other = MagicMock(spec=["get_name"])
    other.get_name.return_value = "PLC_OTHER"
    project = MagicMock()
    project.get_plcs.return_value = [other]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_blocks_sd",
            {"plc_name": "PLC_99", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "No se encontro ningun PLC" in out["error"]


def test_export_blocks_sd_happy_path():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_program_blocks.return_value = [_block(), _block()]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_blocks_sd",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 2
    assert out["result"]["exported_to"] == tmp


# ------------------------------------------------------------ export_udts_sd
def test_export_udts_sd_requires_attached_portal():
    with tempfile.TemporaryDirectory() as tmp:
        out = _client().dispatch(
            "export_udts_sd", {"plc_name": "PLC_1", "target_dir": tmp}
        )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_export_udts_sd_happy_path():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_user_data_types.return_value = [_block()]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_udts_sd",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 1
    assert out["result"]["exported_to"] == tmp
