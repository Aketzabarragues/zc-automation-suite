"""Tests para ``core.infrastructure.tia.tia_helpers.parse_extended_props_from_sd``.

Cruza ``base_props`` (de ``_extract_extended_properties``) con el header SCL
del ``.s7dcl``. Title y Comment vienen del SCL; author/version/programming
language/memory_layout se preservan del dict base. Usa fixtures reales de
``tests/fixtures/source/Bloques/`` (los mismos 5 bloques que
``test_sd_block_parser.py``) mas ``tmp_path`` para el caso de archivo
inexistente.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.infrastructure.tia.tia_helpers import parse_extended_props_from_sd

FIXTURES_DIR = (
    Path(__file__).parent.parent.parent.parent / "fixtures" / "source" / "Bloques"
)


def _fixture(name: str) -> Path:
    return FIXTURES_DIR / name


def test_parse_extended_props_from_sd_happy_path_db() -> None:
    """DB con S7_BlockTitle + S7_BlockComment + base con author/version."""
    base: dict = {
        "title": None,
        "comment": None,
        "author": "HCR",
        "version": "1.0",
        "programming_language": None,
        "memory_layout": None,
    }
    result = parse_extended_props_from_sd(
        _fixture("DB2000_ED.s7dcl"), base
    )
    assert result["title"] == "MLC_wT"
    assert result["comment"] == "MLC_32c"
    assert result["author"] == "HCR"
    assert result["version"] == "1.0"


def test_parse_extended_props_from_sd_udt_preserves_none() -> None:
    """UDT sin author/version en TIA: base con None se preserva."""
    base: dict = {
        "title": None,
        "comment": None,
        "author": None,
        "version": None,
        "programming_language": None,
        "memory_layout": None,
    }
    result = parse_extended_props_from_sd(
        _fixture("UDT_ZC_CONTADOR_MINUTOS.s7dcl"), base
    )
    assert result["title"] == "MLC_55C"
    assert result["comment"] == "MLC_4ts"
    assert result["author"] is None
    assert result["version"] is None


def test_parse_extended_props_from_sd_ob_missing_comment() -> None:
    """OB sin S7_BlockComment: title se popula, comment queda None."""
    base: dict = {
        "title": None,
        "comment": None,
        "author": None,
        "version": None,
        "programming_language": None,
        "memory_layout": None,
    }
    result = parse_extended_props_from_sd(
        _fixture("OB1_MAIN.s7dcl"), base
    )
    assert result["title"] == "MLC_3ck"
    assert result["comment"] is None


def test_parse_extended_props_from_sd_missing_file_returns_base(tmp_path: Path) -> None:
    """Archivo inexistente: retorna copia de base sin modificar."""
    base: dict = {
        "title": "X",
        "comment": "Y",
        "author": "A",
        "version": "2.0",
        "programming_language": "SCL",
        "memory_layout": "Optimized",
    }
    result = parse_extended_props_from_sd(
        tmp_path / "nonexistent.s7dcl", base
    )
    assert result == base
    assert result is not base


def test_parse_extended_props_from_sd_roundtrip_db2000_ed() -> None:
    """Round-trip: base con todo None, SCL solo popula title + comment."""
    base: dict = {
        "title": None,
        "comment": None,
        "author": None,
        "version": None,
        "programming_language": None,
        "memory_layout": None,
    }
    result = parse_extended_props_from_sd(
        _fixture("DB2000_ED.s7dcl"), base
    )
    assert result["title"] == "MLC_wT"
    assert result["comment"] == "MLC_32c"
    assert result["author"] is None
    assert result["version"] is None
    assert result["programming_language"] is None
    assert result["memory_layout"] is None
