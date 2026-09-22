"""Tests de _h_import_plc_tags_xml (Fase 4 / paso 4.1.2b6)."""
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


def test_import_plc_tags_xml_requires_attached_portal():
    with tempfile.TemporaryDirectory() as tmp:
        out = _client().dispatch(
            "import_plc_tags_xml",
            {"plc_name": "PLC_1", "import_dir": tmp},
        )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_import_plc_tags_xml_requires_plc_name():
    c = _client()
    c.attach_wrapper(MagicMock())
    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch("import_plc_tags_xml", {"import_dir": tmp})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_import_plc_tags_xml_requires_import_dir():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch(
        "import_plc_tags_xml", {"plc_name": "PLC_1"}
    )
    assert out["ok"] is False
    assert "import_dir" in out["error"]


def test_import_plc_tags_xml_raises_when_dir_missing():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch(
        "import_plc_tags_xml",
        {"plc_name": "PLC_1", "import_dir": "/nonexistent"},
    )
    assert out["ok"] is False
    assert "no existe" in out["error"]


def test_import_plc_tags_xml_raises_when_plc_not_found():
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
            "import_plc_tags_xml",
            {"plc_name": "PLC_99", "import_dir": tmp},
        )
    assert out["ok"] is False
    assert "No se encontro ningun PLC" in out["error"]


def test_import_plc_tags_xml_happy_path():
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
            "import_plc_tags_xml",
            {"plc_name": "PLC_1", "import_dir": tmp},
        )

    assert out == {"ok": True, "result": {"imported_from": tmp}}
    plc.import_plc_tags.assert_called_once_with(
        import_root_directory=tmp,
        target_folder_path="",
    )
