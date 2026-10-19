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
    """DB con S7_BlockTitle + S7_BlockComment + base con author/version.

    Title/Comment se resuelven de MLC IDs a texto en espanol via el
    ``.s7res`` hermano (DB2000_ED.s7dcl + DB2000_ED.s7res).
    """
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
    assert result["title"] == "DB2000_ED"
    assert result["comment"] == "Bloque de datos entrada digital"
    assert result["author"] == "HCR"
    assert result["version"] == "1.0"


def test_parse_extended_props_from_sd_udt_preserves_none() -> None:
    """UDT sin author/version en TIA: base con None se preserva.

    Title/Comment se resuelven de MLC IDs a texto en espanol via el
    ``.s7res`` hermano (UDT_ZC_CONTADOR_MINUTOS.s7dcl +
    UDT_ZC_CONTADOR_MINUTOS.s7res).
    """
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
    assert result["title"] == "ZC_CONTADOR_MINUTOS"
    assert result["comment"] == "Tipo de dato contador minutos"
    assert result["author"] is None
    assert result["version"] is None


def test_parse_extended_props_from_sd_ob_missing_comment() -> None:
    """OB sin S7_BlockComment: title se popula, comment queda None.

    Title se resuelve de MLC ID a texto en espanol via el ``.s7res``
    hermano (OB1_MAIN.s7dcl + OB1_MAIN.s7res).
    """
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
    assert result["title"] == "PRINCIPAL"
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
    """Round-trip: base con todo None, SCL solo popula title + comment.

    Title/Comment se resuelven a texto en espanol via ``.s7res``.
    """
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
    assert result["title"] == "DB2000_ED"
    assert result["comment"] == "Bloque de datos entrada digital"
    assert result["author"] is None
    assert result["version"] is None
    assert result["programming_language"] is None
    assert result["memory_layout"] is None


def test_parse_extended_props_from_sd_fb2017_resolves_both() -> None:
    """FB2017_ZC_M_SINA: title + comment ambos resueltos a texto es-ES."""
    base: dict = {
        "title": None,
        "comment": None,
        "author": None,
        "version": None,
        "programming_language": None,
        "memory_layout": None,
    }
    result = parse_extended_props_from_sd(
        _fixture("FB2017_ZC_M_SINA.s7dcl"), base
    )
    assert result["title"] == "FB2017_M_SINA"
    assert result["comment"] == (
        "Bloque de funcion para gestion de dispositivo motor sinamics"
    )


def test_parse_extended_props_from_sd_fc2000_resolves_both() -> None:
    """FC2000_ZC_ED: title + comment ambos resueltos a texto es-ES."""
    base: dict = {
        "title": None,
        "comment": None,
        "author": None,
        "version": None,
        "programming_language": None,
        "memory_layout": None,
    }
    result = parse_extended_props_from_sd(
        _fixture("FC2000_ZC_ED.s7dcl"), base
    )
    assert result["title"] == "FC2000_ED"
    assert result["comment"] == "Modelo de dispositivo Entrada digital"


def test_parse_extended_props_from_sd_no_res_file_keeps_mlc_id(tmp_path: Path) -> None:
    """Sin ``.s7res`` hermano: title/comment = MLC ID (fallback visible)."""
    sdcl = tmp_path / "DB2000_ED.s7dcl"
    sdcl.write_text(
        '{ S7_BlockTitle := "MLC_wT"; S7_BlockComment := "MLC_32c" }',
        encoding="utf-8",
    )
    base: dict = {
        "title": None,
        "comment": None,
        "author": None,
        "version": None,
        "programming_language": None,
        "memory_layout": None,
    }
    result = parse_extended_props_from_sd(sdcl, base)
    assert result["title"] == "MLC_wT"
    assert result["comment"] == "MLC_32c"


def test_parse_extended_props_from_sd_res_without_mlc_keeps_id(tmp_path: Path) -> None:
    """``.s7res`` existe pero no contiene el MLC del bloque: fallback al ID."""
    sdcl = tmp_path / "DB2000_ED.s7dcl"
    sdcl.write_text(
        '{ S7_BlockTitle := "MLC_abc"; S7_BlockComment := "MLC_def" }',
        encoding="utf-8",
    )
    res = sdcl.with_suffix(".s7res")
    res.write_text(
        "MultiLingualTexts:\n"
        "  - id: MLC_other1\n"
        "    es-ES: Otro texto 1\n"
        "  - id: MLC_other2\n"
        "    es-ES: Otro texto 2\n",
        encoding="utf-8",
    )
    base: dict = {
        "title": None,
        "comment": None,
        "author": None,
        "version": None,
        "programming_language": None,
        "memory_layout": None,
    }
    result = parse_extended_props_from_sd(sdcl, base)
    assert result["title"] == "MLC_abc"
    assert result["comment"] == "MLC_def"


def test_parse_extended_props_from_sd_corrupt_res_keeps_mlc_id(tmp_path: Path) -> None:
    """``.s7res`` corrupto: no rompe, fallback al MLC ID del .s7dcl."""
    sdcl = tmp_path / "DB2000_ED.s7dcl"
    sdcl.write_text(
        '{ S7_BlockTitle := "MLC_wT"; S7_BlockComment := "MLC_32c" }',
        encoding="utf-8",
    )
    res = sdcl.with_suffix(".s7res")
    res.write_text(
        "esto no es YAML valido: [[[\n  - : sin clave\n",
        encoding="utf-8",
    )
    base: dict = {
        "title": None,
        "comment": None,
        "author": None,
        "version": None,
        "programming_language": None,
        "memory_layout": None,
    }
    result = parse_extended_props_from_sd(sdcl, base)
    assert result["title"] == "MLC_wT"
    assert result["comment"] == "MLC_32c"
