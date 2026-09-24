"""Tests de los helpers internos de ``core.infrastructure.tia_loop``.

Cubren (Fase 4 / paso 4.1.2a helpers):
  - _get_active_project: retorna project si existe; RuntimeError si None/falsy.
  - _safe_get_plc_name: retorna name o None si UnicodeDecodeError.
  - _find_plc: retorna PLC matching; ValueError si plc_name vacio;
    RuntimeError si no existe.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia.tia_helpers import (
    _find_plc,
    _get_active_project,
    _safe_get_plc_name,
)


# ------------------------------------------------------------ _get_active_project
def test_get_active_project_returns_project_when_present() -> None:
    portal = MagicMock()
    project = MagicMock(name="project")
    portal.get_project.return_value = project
    assert _get_active_project(portal) is project
    portal.get_project.assert_called_once_with()


def test_get_active_project_raises_runtime_when_none() -> None:
    portal = MagicMock()
    portal.get_project.return_value = None
    with pytest.raises(RuntimeError, match="No hay ningun proyecto abierto"):
        _get_active_project(portal)


def test_get_active_project_raises_runtime_when_falsy() -> None:
    portal = MagicMock()
    portal.get_project.return_value = False
    with pytest.raises(RuntimeError):
        _get_active_project(portal)


# ------------------------------------------------------------ _safe_get_plc_name
def test_safe_get_plc_name_returns_normal_string() -> None:
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    assert _safe_get_plc_name(plc) == "PLC_1"


def test_safe_get_plc_name_returns_none_on_unicode_decode_error() -> None:
    plc = MagicMock()
    plc.get_name.side_effect = UnicodeDecodeError(
        "ascii", b"\xff\xfe", 0, 1, "bad"
    )
    assert _safe_get_plc_name(plc) is None


# ------------------------------------------------------------ _find_plc
def test_find_plc_returns_matching_plc() -> None:
    p1 = MagicMock(); p1.get_name.return_value = "PLC_1"
    p2 = MagicMock(); p2.get_name.return_value = "PLC_2"
    project = MagicMock()
    project.get_plcs.return_value = [p1, p2]

    assert _find_plc(project, "PLC_2") is p2


def test_find_plc_raises_value_error_when_plc_name_empty() -> None:
    project = MagicMock()
    with pytest.raises(ValueError, match="plc_name"):
        _find_plc(project, "")


def test_find_plc_raises_runtime_when_not_found() -> None:
    p1 = MagicMock(); p1.get_name.return_value = "PLC_1"
    project = MagicMock()
    project.get_plcs.return_value = [p1]
    with pytest.raises(RuntimeError, match="No se encontro ningun PLC"):
        _find_plc(project, "PLC_99")


def test_find_plc_ignores_plc_with_unicode_error_in_name() -> None:
    bad = MagicMock(); bad.get_name.side_effect = UnicodeDecodeError(
        "ascii", b"\xff", 0, 1, "x"
    )
    p1 = MagicMock(); p1.get_name.return_value = "PLC_1"
    project = MagicMock()
    project.get_plcs.return_value = [bad, p1]

    assert _find_plc(project, "PLC_1") is p1
