"""Tests de _h_compile_plc (Fase 4 / paso 4.1.2b1)."""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia_loop import (
    SyncTIAClient,
    register_core_commands,
)


def _client():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


def test_compile_plc_requires_attached_portal():
    out = _client().dispatch("compile_plc", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_compile_plc_requires_plc_name():
    out = _client().dispatch("compile_plc", {})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_compile_plc_raises_when_no_active_project():
    portal = MagicMock()
    portal.get_project.return_value = None
    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("compile_plc", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "No hay ningun proyecto abierto" in out["error"]


def test_compile_plc_raises_when_plc_not_found():
    other = MagicMock(spec=["get_name"])
    other.get_name.return_value = "PLC_OTHER"

    project = MagicMock()
    project.get_plcs.return_value = [other]

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("compile_plc", {"plc_name": "PLC_99"})
    assert out["ok"] is False
    assert "No se encontro ningun PLC" in out["error"]


def test_compile_plc_happy_path_no_errors():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.compile_software.return_value = False  # False = sin errores

    project = MagicMock()
    project.get_plcs.return_value = [plc]

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("compile_plc", {"plc_name": "PLC_1"})
    assert out == {"ok": True, "result": {"had_errors": False}}
    plc.compile_software.assert_called_once_with()


def test_compile_plc_returns_had_errors_true_on_errors():
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.compile_software.return_value = True  # True = hay errores

    project = MagicMock()
    project.get_plcs.return_value = [plc]

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("compile_plc", {"plc_name": "PLC_1"})
    assert out == {"ok": True, "result": {"had_errors": True}}
