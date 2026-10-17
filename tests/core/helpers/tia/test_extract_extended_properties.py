"""Tests del helper ``_extract_extended_properties``.

Verifica el comportamiento defensivo ante tres shapes posibles del
retorno de ``ProgramBlock.get_properties()`` (manual TIA §2.29.11 no
documenta la forma exacta):

  1. Objeto con atributos directos (``props.Title``, ``props.Comment``).
  2. Dict plano (``props["Title"]``).
  3. ``get_properties()`` lanza (COM transitorio / tipo de bloque sin
     la propiedad) o devuelve ``None``.
  4. El bloque ni siquiera expone ``get_properties`` (no es un
     ``ProgramBlock``).

Mockeamos ``get_properties`` con ``MagicMock`` y los distintos retornos
para validar cada rama sin tocar el SDK .NET real.

Nota sobre ``MagicMock``: ``MagicMock()`` auto-genera atributos al
acceder (no respeta asignaciones a atributos no accedidos antes), lo
que introduce falsos positivos en casos con ``None`` explicito o
valores vacios. Para validar la rama de normalizacion de strings
vacias usamos ``types.SimpleNamespace`` (objeto Python real sin
auto-creacion).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia.tia_helpers import _extract_extended_properties


def _make_block(props_obj):
    """Crea un mock de bloque donde ``get_properties()`` devuelve ``props_obj``."""
    block = MagicMock()
    block.get_properties.return_value = props_obj
    return block


def test_getattr_path_finds_all_six_fields():
    """Caso 1: ``props`` expone atributos directos (Title, Comment, ...)."""
    props = MagicMock()
    props.Title = "My title"
    props.Comment = "My comment"
    props.Author = "Aketza"
    props.Version = "1.0"
    props.ProgrammingLanguage = "SCL"
    props.MemoryLayout = "Optimized"

    result = _extract_extended_properties(_make_block(props))

    assert result["title"] == "My title"
    assert result["comment"] == "My comment"
    assert result["author"] == "Aketza"
    assert result["version"] == "1.0"
    assert result["programming_language"] == "SCL"
    assert result["memory_layout"] == "Optimized"


def test_dict_path_finds_all_six_fields():
    """Caso 2: ``props`` es un dict plano; ``get()`` resuelve."""
    props = {
        "Title": "Dict title",
        "Comment": "Dict comment",
        "Author": "Dict author",
        "Version": "2.0",
        "ProgrammingLanguage": "LAD",
        "MemoryLayout": "Standard",
    }

    result = _extract_extended_properties(_make_block(props))

    assert result["title"] == "Dict title"
    assert result["comment"] == "Dict comment"
    assert result["author"] == "Dict author"
    assert result["version"] == "2.0"
    assert result["programming_language"] == "LAD"
    assert result["memory_layout"] == "Standard"


def test_get_properties_raises_returns_all_none():
    """Si ``get_properties()`` lanza, todos los campos son None (no propagar)."""
    block = MagicMock()
    block.get_properties.side_effect = RuntimeError("TIA V21 transient")

    result = _extract_extended_properties(block)

    assert set(result.keys()) == {
        "title", "comment", "author", "version",
        "programming_language", "memory_layout",
    }
    assert all(v is None for v in result.values())


def test_get_properties_returns_none_returns_all_none():
    """Si ``get_properties()`` devuelve ``None``, todos los campos son None."""
    result = _extract_extended_properties(_make_block(None))

    assert all(v is None for v in result.values())


def test_block_has_no_get_properties_returns_all_none():
    """Si el bloque no expone ``get_properties`` (no es ``ProgramBlock``)."""
    block = MagicMock(spec=[])  # sin ``get_properties``

    result = _extract_extended_properties(block)

    assert all(v is None for v in result.values())


def test_empty_string_value_normalized_to_none():
    """Un valor ``""`` se normaliza a ``None`` (IPC JSON uniforme).

    Usa ``SimpleNamespace`` (no ``MagicMock``) para evitar la
    auto-creacion de atributos de MagicMock cuando se accede a keys
    distintas (e.g. asignamos ``Author = None`` pero MagicMock
    auto-genera ``author`` en minusculas).
    """
    props = SimpleNamespace(
        Title="OK",
        Comment="",
        Author=None,
        Version="   ",  # solo espacios -> None
        ProgrammingLanguage="FBD",
        MemoryLayout="Optimized",
    )

    result = _extract_extended_properties(_make_block(props))

    assert result["title"] == "OK"
    assert result["comment"] is None
    assert result["author"] is None
    assert result["version"] is None
    assert result["programming_language"] == "FBD"
    assert result["memory_layout"] == "Optimized"


def test_alternative_camel_case_key_is_picked_up():
    """Si ``props`` expone la variante camelCase (``programmingLanguage``),
    el helper la acepta gracias a ``alt_candidates``.
    """
    props = {
        "programmingLanguage": "ST",
        "memoryLayout": "Standard",
    }

    result = _extract_extended_properties(_make_block(props))

    assert result["programming_language"] == "ST"
    assert result["memory_layout"] == "Standard"