"""Tests de export_tag_table (Fase 4 / paso 4.1.2c1b).

Tests de export_block van en test_tia_client_granular.py (commit 4.1.2c1a).
"""
from __future__ import annotations

import tempfile
from unittest.mock import MagicMock

from core.infrastructure.tia.tia_loop import (
    SyncTIAClient)
from core.infrastructure.tia.tia_commands_catalog import register_all_commands


def _client():
    c = SyncTIAClient()
    register_all_commands(c)
    return c


def _table(nombre: str):
    t = MagicMock()
    t.get_name.return_value = nombre
    t.export = MagicMock()
    return t


def test_export_tag_table_requires_table_name():
    with tempfile.TemporaryDirectory() as tmp:
        c = _client()
        c.attach_wrapper(MagicMock())
        out = c.dispatch(
            "export_tag_table",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "table_name" in out["error"]


def test_export_tag_table_happy_path():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_plc_tag_tables.return_value = [_table("Tabla1"), _table("Tabla2")]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_tag_table",
            {
                "plc_name": "PLC_1",
                "table_name": "Tabla2",
                "target_dir": tmp,
            },
        )

    assert out["ok"] is True
    assert out["result"]["table_name"] == "Tabla2"
    assert out["result"]["exported_to"] == tmp


def test_export_tag_table_raises_when_table_not_found():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_plc_tag_tables.return_value = [_table("Tabla1")]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_tag_table",
            {
                "plc_name": "PLC_1",
                "table_name": "Tabla_FAKE",
                "target_dir": tmp,
            },
        )
    assert out["ok"] is False
    assert "Tabla_FAKE" in out["error"]
    assert "no encontrada" in out["error"]
