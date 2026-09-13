"""Tests de _find_plc_tag_table + get_user_constants (Fase 4 / paso 4.1.2c3a).

Tests de update_user_constant_value / update_user_constant_name /
delete_user_constant van en test_tia_client_user_constants_update.py
(commit 4.1.2c3b).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia_loop import (
    SyncTIAClient,
    _find_plc_tag_table,
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


# ------------------------------------------------------------ _find_plc_tag_table
def test_find_plc_tag_table_raises_on_empty_name():
    plc = MagicMock()
    try:
        _find_plc_tag_table(plc, "")
    except ValueError as exc:
        assert "table_name" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_find_plc_tag_table_returns_matching_table():
    t1 = _table("Tabla1")
    t2 = _table("Tabla2")
    plc = MagicMock()
    plc.get_plc_tag_tables.return_value = [t1, t2]
    assert _find_plc_tag_table(plc, "Tabla2") is t2


def test_find_plc_tag_table_raises_when_not_found():
    t1 = _table("Tabla1")
    plc = MagicMock()
    plc.get_plc_tag_tables.return_value = [t1]
    try:
        _find_plc_tag_table(plc, "Tabla_FAKE")
    except RuntimeError as exc:
        assert "Tabla_FAKE" in str(exc)
        assert "no encontrada" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_find_plc_tag_table_skips_tables_with_unicode_decode_error():
    """Tablas con UnicodeDecodeError no se matchean (no explotan)."""
    good = _table("TablaOK")
    bad = MagicMock()
    bad.get_name.side_effect = UnicodeDecodeError("ascii", b"\xff", 0, 1, "x")
    plc = MagicMock()
    plc.get_plc_tag_tables.return_value = [bad, good]
    assert _find_plc_tag_table(plc, "TablaOK") is good


# ------------------------------------------------------------ get_user_constants
def test_get_user_constants_requires_attached_portal():
    out = _client().dispatch(
        "get_user_constants", {"plc_name": "PLC_1", "table_name": "T1"}
    )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_get_user_constants_requires_plc_name():
    c = _client()
    c.attach_wrapper(MagicMock())
    out = c.dispatch("get_user_constants", {"table_name": "T1"})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_get_user_constants_happy_path():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    table = _table("T1")
    table.get_user_constants.return_value = [
        _constant("N_MAX", "100"),
        _constant("N_MIN", "10"),
    ]
    plc.get_plc_tag_tables.return_value = [table]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "get_user_constants", {"plc_name": "PLC_1", "table_name": "T1"}
    )
    assert out == {
        "ok": True,
        "result": {"constants": {"100": "N_MAX", "10": "N_MIN"}},
    }


def test_get_user_constants_skips_non_integer_values():
    """Constantes con Value no numerico se omiten silenciosamente."""
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    table = _table("T1")
    table.get_user_constants.return_value = [
        _constant("N_MAX", "100"),
        _constant("STR_VAL", "hello"),
        _constant("N_MIN", "10"),
    ]
    plc.get_plc_tag_tables.return_value = [table]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "get_user_constants", {"plc_name": "PLC_1", "table_name": "T1"}
    )
    assert out["result"]["constants"] == {"100": "N_MAX", "10": "N_MIN"}


def test_get_user_constants_raises_when_table_not_found():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_plc_tag_tables.return_value = []
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch(
        "get_user_constants", {"plc_name": "PLC_1", "table_name": "T_FAKE"}
    )
    assert out["ok"] is False
    assert "T_FAKE" in out["error"]
