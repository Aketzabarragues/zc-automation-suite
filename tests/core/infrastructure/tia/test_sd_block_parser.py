"""Tests para ``core.infrastructure.tia.sd_block_parser.parse_block_header``.

Usa fixtures reales copiados de ``_source/Bloques/`` a
``tests/fixtures/source/Bloques/``. Cubren los 5 tipos de bloque
(OB/UDT/DB/FC/FB) y 3 casos defensivos (vacio, sin header, BOM).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.infrastructure.tia.sd_block_parser import parse_block_header

FIXTURES_DIR = (
    Path(__file__).parent.parent.parent.parent / "fixtures" / "source" / "Bloques"
)


def _fixture(name: str) -> Path:
    return FIXTURES_DIR / name


@pytest.fixture(scope="module")
def ob1_header() -> dict[str, str]:
    return parse_block_header(_fixture("OB1_MAIN.s7dcl"))


@pytest.fixture(scope="module")
def udt_header() -> dict[str, str]:
    return parse_block_header(_fixture("UDT_ZC_CONTADOR_MINUTOS.s7dcl"))


@pytest.fixture(scope="module")
def db_header() -> dict[str, str]:
    return parse_block_header(_fixture("DB2000_ED.s7dcl"))


@pytest.fixture(scope="module")
def fc_header() -> dict[str, str]:
    return parse_block_header(_fixture("FC2000_ZC_ED.s7dcl"))


@pytest.fixture(scope="module")
def fb_header() -> dict[str, str]:
    return parse_block_header(_fixture("FB2017_ZC_M_SINA.s7dcl"))


def test_parse_ob1_main_returns_5_attrs(ob1_header: dict[str, str]) -> None:
    assert set(ob1_header.keys()) == {
        "S7_BlockTitle",
        "S7_IECCheck",
        "S7_Optimized",
        "S7_PreferredLanguage",
        "S7_Version",
    }
    assert ob1_header["S7_BlockTitle"] == "MLC_3ck"
    assert ob1_header["S7_IECCheck"] == "TRUE"
    assert ob1_header["S7_Optimized"] == "TRUE"
    assert ob1_header["S7_PreferredLanguage"] == "LAD"
    assert ob1_header["S7_Version"] == "0.1"


def test_parse_udt_returns_2_attrs(udt_header: dict[str, str]) -> None:
    assert set(udt_header.keys()) == {
        "S7_BlockComment",
        "S7_BlockTitle",
    }
    assert udt_header["S7_BlockComment"] == "MLC_4ts"
    assert udt_header["S7_BlockTitle"] == "MLC_55C"


def test_parse_db_returns_8_attrs(db_header: dict[str, str]) -> None:
    assert set(db_header.keys()) == {
        "S7_Author",
        "S7_BlockComment",
        "S7_BlockNumber",
        "S7_BlockTitle",
        "S7_Family",
        "S7_Optimized",
        "S7_StandardRetain",
        "S7_Version",
    }
    assert db_header["S7_Author"] == "HCR"
    assert db_header["S7_BlockComment"] == "MLC_32c"
    assert db_header["S7_BlockNumber"] == "2000"
    assert db_header["S7_BlockTitle"] == "MLC_wT"
    assert db_header["S7_Family"] == "ZeusControl"
    assert db_header["S7_Optimized"] == "TRUE"
    assert db_header["S7_StandardRetain"] == "TRUE"
    assert db_header["S7_Version"] == "1.0"


def test_parse_fc_returns_8_attrs(fc_header: dict[str, str]) -> None:
    assert set(fc_header.keys()) == {
        "S7_Author",
        "S7_BlockComment",
        "S7_BlockNumber",
        "S7_BlockTitle",
        "S7_EditorMode",
        "S7_Family",
        "S7_Optimized",
        "S7_Version",
    }
    assert fc_header["S7_EditorMode"] == "SCL"
    assert fc_header["S7_BlockNumber"] == "2000"
    assert fc_header["S7_Family"] == "ZeusControl"
    assert fc_header["S7_BlockTitle"] == "MLC_49Z"


def test_parse_fb_returns_8_attrs(fb_header: dict[str, str]) -> None:
    assert set(fb_header.keys()) == {
        "S7_Author",
        "S7_BlockComment",
        "S7_BlockNumber",
        "S7_BlockTitle",
        "S7_EditorMode",
        "S7_Family",
        "S7_Optimized",
        "S7_Version",
    }
    assert fb_header["S7_Author"] == "ABH"
    assert fb_header["S7_BlockNumber"] == "2017"
    assert fb_header["S7_EditorMode"] == "SCL"
    assert fb_header["S7_BlockTitle"] == "MLC_58v"


def test_parse_empty_file_returns_empty_dict(tmp_path: Path) -> None:
    empty = tmp_path / "empty.s7dcl"
    empty.write_text("", encoding="utf-8")
    assert parse_block_header(empty) == {}


def test_parse_file_without_header_returns_empty_dict(tmp_path: Path) -> None:
    no_header = tmp_path / "noheader.s7dcl"
    no_header.write_text("FOO BAR BAZ\n", encoding="utf-8")
    assert parse_block_header(no_header) == {}


def test_parse_strips_utf8_bom(tmp_path: Path) -> None:
    with_bom = tmp_path / "bom.s7dcl"
    with_bom.write_bytes(b"\xef\xbb\xbf{\n    S7_Author := \"HCR\"\n}\n")
    assert parse_block_header(with_bom) == {"S7_Author": "HCR"}
