"""Tests del helper ``_extract_extended_properties`` tras el fix 1.6.

El helper lee propiedades via ``block.get_property(name=tia_name)`` por
cada campo. NO usa ``block.get_properties()`` (esa devuelve una lista de
nombres, no un dict con valores).

Mockeamos un ``PlcBlock`` donde ``block.get_property(name=...)`` devuelve
el valor de la propiedad solicitada (string, ``None``, o lanza una
excepcion). Esto refleja la realidad confirmada por el smoke script
``prop_bloques.py``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia.tia_helpers import _extract_extended_properties


def _make_block(prop_values: dict):
    """Crea un mock block donde ``block.get_property(name=X)`` devuelve ``prop_values[X]``.

    Si ``prop_values[X]`` es ``Exception``, mock lanza esa excepcion al llamar.
    Si ``prop_values`` no tiene ``X``, devuelve ``None``.
    """
    block = MagicMock()

    def _getter(name):
        if name in prop_values:
            val = prop_values[name]
            if isinstance(val, Exception):
                raise val
            return val
        return None

    block.get_property.side_effect = _getter
    return block


def test_happy_path_all_fields_populated():
    """Los 5 campos se populan correctamente desde ``get_property``."""
    block = _make_block({
        "HeaderName": "My title",
        "HeaderAuthor": "Aketza",
        "HeaderVersion": "1.0",
        "ProgrammingLanguage": "SCL",
        "MemoryLayout": "Optimized",
    })

    result = _extract_extended_properties(block)

    assert result["title"] == "My title"
    assert result["author"] == "Aketza"
    assert result["version"] == "1.0"
    assert result["programming_language"] == "SCL"
    assert result["memory_layout"] == "Optimized"


def test_empty_strings_normalized_to_none():
    """Strings vacios (caso header nunca release) -> ``None``."""
    block = _make_block({
        "HeaderName": "",
        "HeaderAuthor": "",
        "HeaderVersion": "0.1",
        "ProgrammingLanguage": "LAD",
        "MemoryLayout": "Optimized",
    })

    result = _extract_extended_properties(block)

    assert result["title"] is None  # vacio -> None
    assert result["author"] is None  # vacio -> None
    assert result["version"] == "0.1"  # no vacio -> "0.1"
    assert result["programming_language"] == "LAD"


def test_one_property_raises_others_still_populated():
    """Si una prop lanza excepcion (e.g. utf-8 decode), el resto sigue OK."""
    block = _make_block({
        "HeaderName": "Title",
        "HeaderAuthor": RuntimeError("utf-8 decode error"),
        "HeaderVersion": "1.0",
        "ProgrammingLanguage": "SCL",
        "MemoryLayout": "Optimized",
    })

    result = _extract_extended_properties(block)

    assert result["title"] == "Title"
    assert result["author"] is None  # lanzo excepcion -> None
    assert result["version"] == "1.0"
    assert result["programming_language"] == "SCL"
    assert result["memory_layout"] == "Optimized"


def test_block_has_no_get_property_returns_all_none():
    """Si el bloque no soporta ``get_property`` (no es ``ProgramBlock``), todo ``None``."""
    block = MagicMock(spec=[])  # sin ``get_property``

    result = _extract_extended_properties(block)

    assert result["title"] is None
    assert result["author"] is None
    assert result["version"] is None
    assert result["programming_language"] is None
    assert result["memory_layout"] is None


def test_block_get_property_returns_none_for_all():
    """Si ``get_property`` siempre devuelve ``None``, todos los campos son ``None``."""
    block = _make_block({})

    result = _extract_extended_properties(block)

    assert all(v is None for v in result.values())


def test_whitespace_stripped():
    """Strings con whitespace alrededor se trimean."""
    block = _make_block({
        "HeaderName": "  Title with spaces  ",
        "HeaderAuthor": "\tAketza\n",
    })

    result = _extract_extended_properties(block)

    assert result["title"] == "Title with spaces"
    assert result["author"] == "Aketza"


def test_returns_exactly_five_keys():
    """El helper devuelve exactamente 5 keys (sin ``comment`` -- FASE 3)."""
    block = _make_block({})
    result = _extract_extended_properties(block)

    assert set(result.keys()) == {
        "title", "author", "version",
        "programming_language", "memory_layout",
    }