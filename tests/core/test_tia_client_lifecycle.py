"""Tests de los handlers lifecycle de ``core.infrastructure.tia_loop``.

Cubren (Fase 4 / paso 4.1.2a1):
  - register_core_commands() registra los 4 comandos en el target.
  - open_new_portal: ts ausente / args vacios / archivo no existe / happy path.
  - open_project: wrapper ausente / args vacios / archivo no existe / happy path.
  - save_project: wrapper ausente / sin proyecto / happy path.
  - close_project: wrapper ausente / sin proyecto / happy path.
"""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia_loop import (
    SyncTIAClient,
    register_core_commands,
)


@pytest.fixture
def client_with_handlers():
    c = SyncTIAClient()
    register_core_commands(c)
    return c


# ------------------------------------------------------------ register_core_commands
def test_register_core_commands_includes_lifecycle_handlers(client_with_handlers):
    """Los 4 comandos lifecycle + los de inspection (4.1.2a2-5) estan registrados."""
    expected = {
        # 4.1.2a1
        "open_new_portal",
        "open_project",
        "save_project",
        "close_project",
        # 4.1.2a2
        "ping",
        "list_blocks",
        # 4.1.2a3-5
        "list_plcs",
        "get_project_info",
        "scan_blocks",
    }
    assert expected <= set(client_with_handlers.registered_commands())


# ------------------------------------------------------------ open_new_portal
def test_open_new_portal_requires_ts_module(client_with_handlers):
    """Sin ts attached -> RuntimeError claro (no AttributeError)."""
    out = client_with_handlers.dispatch(
        "open_new_portal", {"project_file_path": "/x"}
    )
    assert out["ok"] is False
    assert "Modulo siemens_tia_scripting no attached" in out["error"]


def test_open_new_portal_requires_project_file_path(client_with_handlers):
    client_with_handlers.attach_ts(MagicMock())
    out = client_with_handlers.dispatch("open_new_portal", {})
    assert out["ok"] is False
    assert "project_file_path" in out["error"]


def test_open_new_portal_raises_when_project_file_missing(client_with_handlers):
    client_with_handlers.attach_ts(MagicMock())
    out = client_with_handlers.dispatch(
        "open_new_portal", {"project_file_path": "/nonexistent/path.apxx"}
    )
    assert out["ok"] is False
    assert "no existe" in out["error"]


def test_open_new_portal_happy_path(client_with_handlers):
    ts = MagicMock()
    new_portal = MagicMock()
    ts.open_portal.return_value = new_portal

    client_with_handlers.attach_ts(ts)

    # Crear un archivo de proyecto temporal valido
    with tempfile.NamedTemporaryFile(suffix=".apxx", delete=False) as f:
        project_path = f.name

    try:
        out = client_with_handlers.dispatch(
            "open_new_portal", {"project_file_path": project_path}
        )
        assert out == {
            "ok": True,
            "result": {
                "opened": True,
                "project_file_path": project_path,
                "state": "connected",
            },
        }
        ts.open_portal.assert_called_once_with(
            portal_mode=ts.Enums.PortalMode.AnyUserInterface
        )
        new_portal.open_project.assert_called_once_with(
            project_file_path=project_path
        )
        # OB1 model: tras open_new_portal, el portal queda attached
        # al tia_client para uso persistente.
        assert client_with_handlers.wrapper is new_portal
    finally:
        os.unlink(project_path)


def test_open_new_portal_raises_when_open_portal_returns_none(
    client_with_handlers,
):
    ts = MagicMock()
    ts.open_portal.return_value = None
    client_with_handlers.attach_ts(ts)

    with tempfile.NamedTemporaryFile(suffix=".apxx", delete=False) as f:
        project_path = f.name
    try:
        out = client_with_handlers.dispatch(
            "open_new_portal", {"project_file_path": project_path}
        )
        assert out["ok"] is False
        assert "open_portal retorno None" in out["error"]
    finally:
        os.unlink(project_path)


# ------------------------------------------------------------ open_project
def test_open_project_requires_attached_portal(client_with_handlers):
    out = client_with_handlers.dispatch(
        "open_project", {"project_file_path": "/x"}
    )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_open_project_requires_project_file_path(client_with_handlers):
    client_with_handlers.attach_wrapper(MagicMock())
    out = client_with_handlers.dispatch("open_project", {})
    assert out["ok"] is False
    assert "project_file_path" in out["error"]


def test_open_project_raises_when_project_file_missing(client_with_handlers):
    client_with_handlers.attach_wrapper(MagicMock())
    out = client_with_handlers.dispatch(
        "open_project", {"project_file_path": "/nonexistent/path.apxx"}
    )
    assert out["ok"] is False
    assert "no existe" in out["error"]


def test_open_project_happy_path(client_with_handlers):
    portal = MagicMock()
    client_with_handlers.attach_wrapper(portal)

    with tempfile.NamedTemporaryFile(suffix=".apxx", delete=False) as f:
        project_path = f.name

    try:
        out = client_with_handlers.dispatch(
            "open_project", {"project_file_path": project_path}
        )
        assert out == {
            "ok": True,
            "result": {"opened": True, "project_file_path": project_path},
        }
        portal.open_project.assert_called_once_with(
            project_file_path=project_path
        )
    finally:
        os.unlink(project_path)


# save_project y close_project se prueban en test_tia_client_save_close.py
# (commit separado 4.1.2a1b para mantener <200 lineas).
