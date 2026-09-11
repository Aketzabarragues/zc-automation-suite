"""Tests de get_project_info (Fase 4 / paso 4.1.2a4)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from core.infrastructure.tia_client import (
    SyncTIAClient,
    register_core_commands,
)


def _client():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


def test_get_project_info_requires_attached_portal():
    out = _client().dispatch("get_project_info", {})
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_get_project_info_raises_when_no_active_project():
    portal = MagicMock()
    portal.get_project.return_value = None
    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("get_project_info", {})
    assert out["ok"] is False
    assert "No hay ningun proyecto abierto" in out["error"]


def test_get_project_info_minimal_only_name():
    """Solo Name presente, resto None -> solo `name` en result."""
    project = MagicMock()
    project.get_property.return_value = None
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("get_project_info", {})
    assert out == {"ok": True, "result": {"name": None}}


def test_get_project_info_with_all_primitive_properties():
    """Properties primitivas se incluyen tal cual en el result."""
    project = MagicMock()

    def fake_get_property(name: str = ""):
        table = {
            "Name": "MiProyecto",
            "Path": "C:/proys/MiProyecto.apxx",
            "Author": "operario@planta",
            "Version": "V18",
        }
        return table.get(name)

    project.get_property.side_effect = fake_get_property

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("get_project_info", {})
    assert out == {
        "ok": True,
        "result": {
            "name": "MiProyecto",
            "path": "C:/proys/MiProyecto.apxx",
            "author": "operario@planta",
            "version": "V18",
        },
    }


def test_get_project_info_serializes_datetime_to_iso8601():
    """Datetimes .NET se convierten a ISO 8601 string."""
    dt = datetime(2026, 9, 11, 12, 34, 56)

    project = MagicMock()

    def fake_get_property(name: str = ""):
        table = {
            "Name": "MiProyecto",
            "CreationTime": dt,
            "LastModified": dt,
        }
        return table.get(name)

    project.get_property.side_effect = fake_get_property

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("get_project_info", {})
    assert out["ok"] is True
    result = out["result"]
    assert result["name"] == "MiProyecto"
    assert result["creation_time"] == "2026-09-11T12:34:56"
    assert result["last_modified"] == "2026-09-11T12:34:56"
    # Propiedades no pedidas no aparecen
    assert "path" not in result
    assert "author" not in result


def test_get_project_info_skips_properties_that_raise():
    """Si una property lanza al leerla, se omite (no tumbar el handler)."""
    project = MagicMock()

    def fake_get_property(name: str = ""):
        if name == "Name":
            return "Proyecto"
        if name == "Path":
            raise PermissionError("acceso denegado")
        if name == "Author":
            return "operario"
        return None

    project.get_property.side_effect = fake_get_property

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("get_project_info", {})
    assert out == {
        "ok": True,
        "result": {"name": "Proyecto", "author": "operario"},
    }
