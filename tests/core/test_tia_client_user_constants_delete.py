"""Tests de _h_delete_user_constant (Fase 4 / paso 4.1.2c3a).

Tests de helpers + get_user_constants en test_tia_client_user_constants.py.
Tests de update_user_constant_value + update_user_constant_name en
test_tia_client_user_constants_update.py (commit 4.1.2c3b).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia.tia_loop import (
    SyncTIAClient,
    register_core_commands,
)


def _client():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


def _table(nombre: str):
    t = MagicMock()
    t.get_name.return_value = nombre
    return t


def _constant(name: str, value: str):
    c = MagicMock()
    c.get_property.side_effect = lambda **kw: {
        "Name": name,
        "Value": value,
    }.get(kw.get("name"))
    return c


def test_delete_user_constant_happy_path():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    table = _table("T1")
    const = _constant("TO_DELETE", "1")
    table.get_user_constants.return_value = [const]
    plc.get_plc_tag_tables.return_value = [table]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "delete_user_constant",
        {
            "plc_name": "PLC_1",
            "table_name": "T1",
            "constant_name": "TO_DELETE",
        },
    )
    assert out == {
        "ok": True,
        "result": {"deleted": True, "constant": "TO_DELETE"},
    }
    const.delete.assert_called_once_with()


def test_delete_user_constant_raises_when_not_found():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    table = _table("T1")
    table.get_user_constants.return_value = [_constant("OTHER", "1")]
    plc.get_plc_tag_tables.return_value = [table]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "delete_user_constant",
        {
            "plc_name": "PLC_1",
            "table_name": "T1",
            "constant_name": "TO_DELETE",
        },
    )
    assert out["ok"] is False
    assert "TO_DELETE" in out["error"]
