"""Tests de happy paths y defensive fallbacks de _h_scan_blocks (4.1.2a5c2)."""
from __future__ import annotations

import re
from unittest.mock import MagicMock

from core.infrastructure.tia_client import (
    SyncTIAClient,
    register_core_commands,
)


def _client():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


def _block(nombre: str):
    b = MagicMock(spec=["get_name"])
    b.get_name.return_value = nombre
    return b


def test_scan_blocks_happy_path_returns_full_payload():
    target_plc = MagicMock()
    target_plc.get_program_blocks.return_value = [_block("DB1"), _block("FB2")]
    target_plc.get_plc_tag_tables.return_value = [_block("TablaTags_1"), _block("TablaTags_2")]
    target_plc.get_user_data_types.return_value = [_block("UDT10")]

    project = MagicMock()
    project.get_plcs.return_value = [target_plc]
    target_plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is True
    result = out["result"]

    assert result["plc_name"] == "PLC_1"
    assert len(result["blocks"]) == 2
    assert result["blocks"][0]["nombre"] == "DB1"
    assert result["blocks"][1]["nombre"] == "FB2"
    assert len(result["tag_tables"]) == 2
    assert result["tag_tables"][0]["nombre"] == "TablaTags_1"
    assert len(result["udts"]) == 1
    assert result["udts"][0]["nombre"] == "UDT10"

    # scanned_at es ISO 8601.
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", result["scanned_at"])


def test_scan_blocks_tag_tables_failure_returns_empty_not_error():
    target_plc = MagicMock()
    target_plc.get_program_blocks.return_value = [_block("DB1")]
    target_plc.get_plc_tag_tables.side_effect = RuntimeError("COM transient")
    target_plc.get_user_data_types.return_value = []

    project = MagicMock()
    project.get_plcs.return_value = [target_plc]
    target_plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is True
    assert out["result"]["blocks"] == [{"nombre": "DB1", "numero": 1, "tipo": "DB", "ruta": ""}]
    assert out["result"]["tag_tables"] == []
    assert out["result"]["udts"] == []


def test_scan_blocks_udts_failure_returns_empty_not_error():
    """Si TIA no expone get_user_data_types -> udts=[] y sigue."""
    target_plc = MagicMock()
    target_plc.get_program_blocks.return_value = [_block("DB1")]
    target_plc.get_plc_tag_tables.return_value = []
    target_plc.get_user_data_types.side_effect = AttributeError(
        "method not exposed"
    )

    project = MagicMock()
    project.get_plcs.return_value = [target_plc]
    target_plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is True
    assert out["result"]["udts"] == []


def test_scan_blocks_empty_plc_returns_empty_lists():
    target_plc = MagicMock()
    target_plc.get_program_blocks.return_value = []
    target_plc.get_plc_tag_tables.return_value = []
    target_plc.get_user_data_types.return_value = []

    project = MagicMock()
    project.get_plcs.return_value = [target_plc]
    target_plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is True
    assert out["result"]["blocks"] == []
    assert out["result"]["tag_tables"] == []
    assert out["result"]["udts"] == []
