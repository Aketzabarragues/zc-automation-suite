"""Tests de import_tag_table (Fase 4 / paso 4.1.2c1-import).

Tests de export_block + export_tag_table van en
test_tia_client_granular.py (commit 4.1.2c1-export).
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


def test_import_tag_table_requires_attached_portal():
    with tempfile.TemporaryDirectory() as tmp:
        out = _client().dispatch(
            "import_tag_table",
            {"plc_name": "PLC_1", "import_dir": tmp},
        )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_import_tag_table_requires_import_dir():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch("import_tag_table", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "import_dir" in out["error"]


def test_import_tag_table_raises_when_dir_missing():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch(
        "import_tag_table",
        {"plc_name": "PLC_1", "import_dir": "/nonexistent"},
    )
    assert out["ok"] is False
    assert "no existe" in out["error"]


def test_import_tag_table_happy_path():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "import_tag_table",
            {"plc_name": "PLC_1", "import_dir": tmp},
        )

    assert out == {"ok": True, "result": {"imported_from": tmp}}
    plc.import_plc_tags.assert_called_once_with(
        import_root_directory=tmp,
        target_folder_path="",
    )
