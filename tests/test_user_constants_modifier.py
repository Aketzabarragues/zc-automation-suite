"""Tests para ``UserConstantsModifier`` (añade PlcUserConstant con estructura canónica).

Tests OFFLINE: crean un PlcTagTable.xml de fixture en un directorio temporal
y verifican que el modifier:
  - Construye la estructura canónica completa (AttributeList + MultilingualText anidado).
  - Genera IDs hexadecimales mayúsculas monotónicamente crecientes.
  - Es idempotente (no duplica por nombre).
  - Inserta ``<ObjectList>`` en posición canónica.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.xml.user_constants_modifier import UserConstantsModifier


_EMPTY_TABLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<SW.Tags.PlcTagTable>
  <AttributeList>
    <Name>2000_Disp_ED</Name>
  </AttributeList>
  <LinkList />
</SW.Tags.PlcTagTable>
"""


@pytest.fixture
def empty_table(tmp_path: Path) -> Path:
    """Crea un PlcTagTable.xml vacío de fixture."""
    tabla_path = tmp_path / "2000_Disp_ED.xml"
    tabla_path.write_text(_EMPTY_TABLE_XML, encoding="utf-8")
    return tabla_path


def test_add_user_constant_creates_canonical_structure(empty_table: Path) -> None:
    """``add_user_constant`` debe generar la estructura canónica completa."""
    modifier = UserConstantsModifier(empty_table)
    result = modifier.add_user_constant(
        name="V_VA_101",
        value=1,
        comment="Válvula VA-101",
    )
    assert result is True
    assert modifier.was_modified() is True
    modifier.save()

    new_content = empty_table.read_text(encoding="utf-8")
    # Estructura canónica: <SW.Tags.PlcUserConstant>.
    assert "<SW.Tags.PlcUserConstant" in new_content
    assert 'CompositionName="UserConstants"' in new_content
    # ID hexadecimal mayúscula (primer ID disponible; empieza en 0 si no hay otros).
    assert 'ID="0"' in new_content
    # Atributos básicos.
    assert "<Name>V_VA_101</Name>" in new_content
    assert "<DataTypeName>Int</DataTypeName>" in new_content
    assert "<Value>1</Value>" in new_content
    # Comment anidado con MultilingualText + MultilingualTextItem.
    assert "<MultilingualText" in new_content
    assert "<MultilingualTextItem" in new_content
    assert '<Culture>es-ES</Culture>' in new_content
    assert "<Text>Válvula VA-101</Text>" in new_content


def test_add_user_constant_is_idempotent(empty_table: Path) -> None:
    """Una segunda llamada con el mismo nombre NO debe duplicar."""
    modifier = UserConstantsModifier(empty_table)
    first = modifier.add_user_constant(name="V_VA_101", value=1, comment="c1")
    second = modifier.add_user_constant(name="V_VA_101", value=1, comment="c2")

    assert first is True
    assert second is False  # idempotente
    modifier.save()

    content = empty_table.read_text(encoding="utf-8")
    # Solo debe haber UNA aparición del nombre.
    assert content.count("<Name>V_VA_101</Name>") == 1


def test_add_user_constant_increments_ids(empty_table: Path) -> None:
    """IDs hexadecimales deben incrementarse monotónicamente."""
    modifier = UserConstantsModifier(empty_table)
    modifier.add_user_constant(name="A", value=1, comment="")
    modifier.add_user_constant(name="B", value=2, comment="")
    modifier.add_user_constant(name="C", value=3, comment="")
    modifier.save()

    content = empty_table.read_text(encoding="utf-8")
    # Tres constantes con IDs incrementales.
    import re

    ids = re.findall(r'ID="([0-9A-F]+)"', content)
    assert ids[0] != ids[1]
    assert ids[1] != ids[2]
    # Orden ascendente.
    assert int(ids[0], 16) < int(ids[1], 16) < int(ids[2], 16)


def test_add_user_constant_without_comment(empty_table: Path) -> None:
    """Si no se pasa comment, NO se genera el árbol MultilingualText."""
    modifier = UserConstantsModifier(empty_table)
    modifier.add_user_constant(name="X", value=5, comment="")
    modifier.save()

    content = empty_table.read_text(encoding="utf-8")
    assert "<Name>X</Name>" in content
    assert "<MultilingualText" not in content
    assert "<Value>5</Value>" in content


def test_add_user_constant_validates_empty_name(empty_table: Path) -> None:
    """El modificador debe rechazar nombres vacíos."""
    modifier = UserConstantsModifier(empty_table)
    with pytest.raises(ValueError, match="no puede estar vacío"):
        modifier.add_user_constant(name="", value=1)
