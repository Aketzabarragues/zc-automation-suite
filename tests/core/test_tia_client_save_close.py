"""Tests de save_project y close_project (Fase 4 / paso 4.1.2a1b).

Separa estos tests del resto del lifecycle (4.1.2a1a) para mantener
<200 lineas por commit.
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


# ------------------------------------------------------------ save_project
def test_save_project_requires_attached_portal():
    out = _client().dispatch("save_project", {})
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_save_project_raises_when_no_active_project():
    portal = MagicMock()
    portal.get_project.return_value = None

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("save_project", {})
    assert out["ok"] is False
    assert "No hay ningun proyecto abierto" in out["error"]


def test_save_project_happy_path():
    project = MagicMock()
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("save_project", {})
    assert out == {"ok": True, "result": {"saved": True}}
    project.save.assert_called_once_with()


# ------------------------------------------------------------ close_project
def test_close_project_requires_attached_portal():
    out = _client().dispatch("close_project", {})
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_close_project_raises_when_no_active_project():
    portal = MagicMock()
    portal.get_project.return_value = None

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("close_project", {})
    assert out["ok"] is False
    assert "No hay ningun proyecto abierto" in out["error"]


def test_close_project_happy_path():
    project = MagicMock()
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("close_project", {})
    assert out == {"ok": True, "result": {"closed": True}}
    project.close.assert_called_once_with()
