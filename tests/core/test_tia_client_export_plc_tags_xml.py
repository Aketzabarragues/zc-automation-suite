"""Tests de _h_export_plc_tags_xml (Fase 4 / paso 4.1.2b4)."""
from __future__ import annotations

import tempfile
from unittest.mock import MagicMock

from core.infrastructure.tia_client import (
    SyncTIAClient,
    register_core_commands,
)


def _client():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


def _table(name: str):
    t = MagicMock()
    t.get_name.return_value = name
    t.export = MagicMock()
    return t


# ------------------------------------------------------------ error paths
def test_export_plc_tags_xml_requires_attached_portal():
    with tempfile.TemporaryDirectory() as tmp:
        out = _client().dispatch(
            "export_plc_tags_xml",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_export_plc_tags_xml_requires_plc_name():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch("export_plc_tags_xml", {"target_dir": "/tmp/x"})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_export_plc_tags_xml_raises_when_plc_not_found():
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
            "export_plc_tags_xml",
            {"plc_name": "PLC_99", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "No se encontro ningun PLC" in out["error"]


# ------------------------------------------------------------ happy paths
def test_export_plc_tags_xml_exports_all_tables_when_no_filter():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    t1, t2 = _table("Tabla1"), _table("Tabla2")
    plc.get_plc_tag_tables.return_value = [t1, t2]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_plc_tags_xml",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 2
    assert out["result"]["exported_to"] == tmp
    t1.export.assert_called_once_with(
        target_directory_path=tmp, keep_folder_structure=True
    )
    t2.export.assert_called_once_with(
        target_directory_path=tmp, keep_folder_structure=True
    )


def test_export_plc_tags_xml_filters_by_table_names_whitelist():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    t1, t2, t3 = _table("Tabla1"), _table("Tabla2"), _table("Tabla3")
    plc.get_plc_tag_tables.return_value = [t1, t2, t3]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_plc_tags_xml",
            {
                "plc_name": "PLC_1",
                "target_dir": tmp,
                "table_names": ["Tabla1", "Tabla3"],
            },
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 2
    t1.export.assert_called_once()
    t2.export.assert_not_called()
    t3.export.assert_called_once()


def test_export_plc_tags_xml_skips_tables_with_unicode_decode_error():
    """Tablas con UnicodeDecodeError no estan en whitelist -> se omiten."""
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"

    bad_table = MagicMock()
    bad_table.get_name.side_effect = UnicodeDecodeError(
        "ascii", b"\xff", 0, 1, "x"
    )
    bad_table.export = MagicMock()

    good_table = _table("TablaOK")

    plc.get_plc_tag_tables.return_value = [bad_table, good_table]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_plc_tags_xml",
            {
                "plc_name": "PLC_1",
                "target_dir": tmp,
                "table_names": ["TablaOK"],
            },
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 1
    bad_table.export.assert_not_called()


def test_export_plc_tags_xml_empty_table_list():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_plc_tag_tables.return_value = []
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_plc_tags_xml",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out == {
        "ok": True,
        "result": {"exported_to": tmp, "count": 0},
    }
