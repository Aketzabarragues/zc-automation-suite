"""Tests de _safe_get_block_name / _safe_get_block_path / _safe_get_table_name
(Fase 4 / paso 4.1.2a5a). Helpers defensivos que usa scan_blocks.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia_client import (
    _safe_get_block_name,
    _safe_get_block_path,
    _safe_get_table_name,
)


# ------------------------------------------------------------ _safe_get_block_name
def test_safe_get_block_name_uses_get_name():
    block = MagicMock()
    block.get_name.return_value = "OB1"
    assert _safe_get_block_name(block) == "OB1"


def test_safe_get_block_name_falls_back_to_name_attribute():
    block = MagicMock(spec=["Name"])
    block.Name = "FB2"
    assert _safe_get_block_name(block) == "FB2"


def test_safe_get_block_name_returns_none_on_unicode_error():
    block = MagicMock()
    block.get_name.side_effect = UnicodeDecodeError("ascii", b"\xff", 0, 1, "x")
    assert _safe_get_block_name(block) is None


def test_safe_get_block_name_returns_none_on_generic_exception():
    block = MagicMock()
    block.get_name.side_effect = RuntimeError("COM transient")
    assert _safe_get_block_name(block) is None


def test_safe_get_block_name_returns_none_when_no_name_method():
    """Objeto sin get_name ni Name -> None (no explotar)."""
    block = object()
    assert _safe_get_block_name(block) is None


# ------------------------------------------------------------ _safe_get_block_path
def test_safe_get_block_path_uses_get_path():
    block = MagicMock()
    block.get_path.return_value = "/PlcTags/Group1/OB1"
    assert _safe_get_block_path(block) == "/PlcTags/Group1/OB1"


def test_safe_get_block_path_falls_back_to_path_attribute():
    block = MagicMock(spec=["Path"])
    block.Path = "/PlcTags/OB1"
    assert _safe_get_block_path(block) == "/PlcTags/OB1"


def test_safe_get_block_path_returns_empty_string_on_exception():
    block = MagicMock()
    block.get_path.side_effect = RuntimeError("COM transient")
    assert _safe_get_block_path(block) == ""


def test_safe_get_block_path_returns_empty_string_when_no_path_method():
    block = object()
    assert _safe_get_block_path(block) == ""


# ------------------------------------------------------------ _safe_get_table_name
def test_safe_get_table_name_returns_normal_value():
    table = MagicMock()
    table.get_name.return_value = "TablaTags"
    assert _safe_get_table_name(table) == "TablaTags"


def test_safe_get_table_name_returns_none_on_unicode_error():
    table = MagicMock()
    table.get_name.side_effect = UnicodeDecodeError("ascii", b"\xff", 0, 1, "x")
    assert _safe_get_table_name(table) is None


def test_safe_get_table_name_returns_none_on_generic_exception():
    table = MagicMock()
    table.get_name.side_effect = RuntimeError("COM transient")
    assert _safe_get_table_name(table) is None
