"""Tests de update_user_constant_value + update_user_constant_name +
delete_user_constant (Fase 4 / paso 4.1.2c3b).

Tests de _find_plc_tag_table + get_user_constants van en
test_tia_client_user_constants.py (commit 4.1.2c3a).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia_client import (
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
    """Mock que actualiza el estado en set_property para que la doble
    validacion (re-leer tras set) refleje el cambio."""
    c = MagicMock()
    state = {"Name": name, "Value": value}

    def fake_get(**kw):
        return state.get(kw.get("name"))

    def fake_set(**kw):
        state[kw.get("name")] = kw.get("value")
        return 0

    c.get_property.side_effect = fake_get
    c.set_property.side_effect = fake_set
    return c


# ------------------------------------------------------------ update_user_constant_value
def test_update_user_constant_value_happy_path():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    table = _table("T1")
    const = _constant("N_MAX", "100")
    table.get_user_constants.return_value = [const]
    plc.get_plc_tag_tables.return_value = [table]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "update_user_constant_value",
        {
            "plc_name": "PLC_1",
            "table_name": "T1",
            "constant_name": "N_MAX",
            "new_value": 200,
        },
    )
    assert out == {
        "ok": True,
        "result": {"updated": True, "constant": "N_MAX", "value": 200},
    }
    const.set_property.assert_called_once_with(name="Value", value="200")


def test_update_user_constant_value_raises_on_non_zero_return_code():
    """TIA V21: set_property puede retornar !=0 sin lanzar."""
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    table = _table("T1")
    const = _constant("N_MAX", "100")
    const.set_property.side_effect = lambda **kw: 1  # FALLO silencioso
    table.get_user_constants.return_value = [const]
    plc.get_plc_tag_tables.return_value = [table]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "update_user_constant_value",
        {
            "plc_name": "PLC_1",
            "table_name": "T1",
            "constant_name": "N_MAX",
            "new_value": 200,
        },
    )
    assert out["ok"] is False
    assert "rechazo" in out["error"]
    assert "codigo de retorno 1" in out["error"]


def test_update_user_constant_value_double_check_fails():
    """set_property retorna OK pero el valor real no se aplico."""
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    table = _table("T1")

    const = MagicMock()
    const.get_property.side_effect = lambda **kw: {
        "Name": "N_MAX",
        "Value": "100",  # no cambia tras set_property
    }.get(kw.get("name"))
    const.set_property.return_value = 0
    const.set_property.side_effect = lambda **kw: 0  # OK pero no muta

    table.get_user_constants.return_value = [const]
    plc.get_plc_tag_tables.return_value = [table]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "update_user_constant_value",
        {
            "plc_name": "PLC_1",
            "table_name": "T1",
            "constant_name": "N_MAX",
            "new_value": 200,
        },
    )
    assert out["ok"] is False
    assert "set_property retorno 0" in out["error"]
    assert "fallo silencioso" in out["error"]


def test_update_user_constant_value_raises_when_constant_not_found():
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
        "update_user_constant_value",
        {
            "plc_name": "PLC_1",
            "table_name": "T1",
            "constant_name": "N_MAX",
            "new_value": 200,
        },
    )
    assert out["ok"] is False
    assert "N_MAX" in out["error"]


# ------------------------------------------------------------ update_user_constant_name
def test_update_user_constant_name_happy_path():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    table = _table("T1")
    const = _constant("OLD_NAME", "1")
    table.get_user_constants.return_value = [const]
    plc.get_plc_tag_tables.return_value = [table]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "update_user_constant_name",
        {
            "plc_name": "PLC_1",
            "table_name": "T1",
            "current_name": "OLD_NAME",
            "new_name": "NEW_NAME",
        },
    )
    assert out == {
        "ok": True,
        "result": {"updated": True, "old_name": "OLD_NAME", "new_name": "NEW_NAME"},
    }


def test_update_user_constant_name_raises_on_silent_failure():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    table = _table("T1")
    const = _constant("OLD_NAME", "1")
    const.set_property.side_effect = lambda **kw: 1  # FALLO silencioso
    table.get_user_constants.return_value = [const]
    plc.get_plc_tag_tables.return_value = [table]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "update_user_constant_name",
        {
            "plc_name": "PLC_1",
            "table_name": "T1",
            "current_name": "OLD_NAME",
            "new_name": "NEW_NAME",
        },
    )
    assert out["ok"] is False
    assert "rechazo" in out["error"]


def test_update_user_constant_name_raises_when_not_found():
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
        "update_user_constant_name",
        {
            "plc_name": "PLC_1",
            "table_name": "T1",
            "current_name": "OLD_NAME",
            "new_name": "NEW_NAME",
        },
    )
    assert out["ok"] is False
    assert "OLD_NAME" in out["error"]


# ------------------------------------------------------------ delete_user_constant
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
