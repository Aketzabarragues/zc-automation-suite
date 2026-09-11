"""Tests de list_plcs y _safe_short_designation (Fase 4 / paso 4.1.2a3).

Cubre:
  - _safe_short_designation: 4 paths (no getter, normal, vacio, exception).
  - list_plcs: wrapper=None / sin proyecto / happy / short_designation None
    cuando falla.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia_client import (
    SyncTIAClient,
    _safe_short_designation,
    register_core_commands,
)


def _client():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


# ------------------------------------------------------------ _safe_short_designation
def test_safe_short_designation_returns_none_when_no_getter():
    plc = object()  # sin get_property
    assert _safe_short_designation(plc) is None


def test_safe_short_designation_returns_normal_value():
    plc = MagicMock()
    plc.get_property.return_value = "CPU 1518-4 PN/DP"
    assert _safe_short_designation(plc) == "CPU 1518-4 PN/DP"
    plc.get_property.assert_called_once_with(name="ShortDesignation")


def test_safe_short_designation_returns_none_when_value_is_none():
    plc = MagicMock()
    plc.get_property.return_value = None
    assert _safe_short_designation(plc) is None


def test_safe_short_designation_returns_none_on_exception():
    plc = MagicMock()
    plc.get_property.side_effect = RuntimeError("PermissionDenied")
    assert _safe_short_designation(plc) is None


def test_safe_short_designation_returns_none_when_blank_string():
    plc = MagicMock()
    plc.get_property.return_value = "   "
    assert _safe_short_designation(plc) is None


# ------------------------------------------------------------ list_plcs
def test_list_plcs_requires_attached_portal():
    out = _client().dispatch("list_plcs", {})
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_list_plcs_raises_when_no_active_project():
    portal = MagicMock()
    portal.get_project.return_value = None
    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("list_plcs", {})
    assert out["ok"] is False
    assert "No hay ningun proyecto abierto" in out["error"]


def test_list_plcs_happy_path_with_short_designation():
    plc1 = MagicMock()
    plc1.get_name.return_value = "PLC_1"
    plc1.get_property.return_value = "CPU 1518-4 PN/DP"
    plc2 = MagicMock()
    plc2.get_name.return_value = "PLC_2"
    plc2.get_property.return_value = "IM 155-6 PN"

    project = MagicMock()
    project.get_plcs.return_value = [plc1, plc2]

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("list_plcs", {})
    assert out == {
        "ok": True,
        "result": {
            "plcs": [
                {"name": "PLC_1", "short_designation": "CPU 1518-4 PN/DP"},
                {"name": "PLC_2", "short_designation": "IM 155-6 PN"},
            ],
        },
    }


def test_list_plcs_returns_short_designation_none_when_property_fails():
    """Si get_property falla (e.g. PermissionDenied), short_designation=None."""
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_property.side_effect = RuntimeError("PermissionDenied")

    project = MagicMock()
    project.get_plcs.return_value = [plc]

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("list_plcs", {})
    assert out == {
        "ok": True,
        "result": {"plcs": [{"name": "PLC_1", "short_designation": None}]},
    }


def test_list_plcs_returns_short_designation_none_when_property_absent():
    """Si el PLC no tiene get_property (modelo raro), short_designation=None."""
    plc = MagicMock(spec=["get_name"])  # sin get_property
    plc.get_name.return_value = "PLC_OLD"

    project = MagicMock()
    project.get_plcs.return_value = [plc]

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("list_plcs", {})
    assert out == {
        "ok": True,
        "result": {"plcs": [{"name": "PLC_OLD", "short_designation": None}]},
    }


def test_list_plcs_returns_empty_list_when_no_plcs():
    project = MagicMock()
    project.get_plcs.return_value = []

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("list_plcs", {})
    assert out == {"ok": True, "result": {"plcs": []}}
