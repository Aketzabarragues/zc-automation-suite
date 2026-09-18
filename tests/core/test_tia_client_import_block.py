"""Tests de _h_import_block (Fase 4 / paso 4.1.2c2)."""
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


def test_import_block_requires_attached_portal():
    with tempfile.TemporaryDirectory() as tmp:
        out = _client().dispatch(
            "import_block",
            {"plc_name": "PLC_1", "import_dir": tmp},
        )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_import_block_requires_plc_name():
    c = _client()
    c.attach_wrapper(MagicMock())
    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch("import_block", {"import_dir": tmp})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_import_block_requires_import_dir():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch("import_block", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "import_dir" in out["error"]


def test_import_block_raises_when_dir_missing():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch(
        "import_block",
        {"plc_name": "PLC_1", "import_dir": "/nonexistent"},
    )
    assert out["ok"] is False
    assert "no existe" in out["error"]


def test_import_block_raises_when_plc_not_found():
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
            "import_block",
            {"plc_name": "PLC_99", "import_dir": tmp},
        )
    assert out["ok"] is False
    assert "No se encontro ningun PLC" in out["error"]


def test_import_block_happy_path():
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
            "import_block",
            {"plc_name": "PLC_1", "import_dir": tmp},
        )

    assert out == {"ok": True, "result": {"imported_from": tmp}}
    # Sin ``target_folder`` explicito NO pasamos ``target_folder_path``
    # a TIA: su firma es
    # ``import_blocks(import_root_directory, target_folder_path=None)``.
    # Pasar ``""`` (string vacio) hace que TIA V21 NO haga match UPDATE
    # de bloques pre-existentes .
    plc.import_blocks.assert_called_once_with(import_root_directory=tmp)


def test_import_block_with_empty_target_folder_omits_param():
    """ fix: ``target_folder=""`` ya NO se traduce a
    ``target_folder_path=""`` en la llamada a TIA (que es lo que
    rompe el match UPDATE). En su lugar omitimos el parametro y
    dejamos que TIA use su default ``None``.
    """
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
            "import_block",
            {
                "plc_name": "PLC_1",
                "import_dir": tmp,
                "target_folder": "",
            },
        )

    assert out["ok"] is True
    plc.import_blocks.assert_called_once_with(import_root_directory=tmp)


def test_import_block_passes_target_folder():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        c.dispatch(
            "import_block",
            {
                "plc_name": "PLC_1",
                "import_dir": tmp,
                "target_folder": "MyGroup",
            },
        )

    plc.import_blocks.assert_called_once_with(
        import_root_directory=tmp,
        target_folder_path="MyGroup",
    )
