"""Tests de regresion para ``_inyectar_comentario_multilingue``.

Verifica que el helper inyecta o actualiza el comment DENTRO del
``ObjectList`` del ``PlcUserConstant``, NO como hijo directo.

TIA V21 rechaza XML donde el Comment esta fuera del ``ObjectList`` con
``OpennessAccessException``. Antes del fix, el helper creaba un Comment
hermano de ``AttributeList`` y ``ObjectList`` (estructura invalida).

TIA exporta sin namespace declaration; las tags son planas.
"""
from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def _make_const(name: str, value: int, existing_comment: str | None = None) -> ET.Element:
    """Crea un ``PlcUserConstant`` con la estructura valida de TIA V21."""
    const = ET.Element("SW.Tags.PlcUserConstant")
    const.set("ID", "1")
    const.set("CompositionName", "UserConstants")
    al = ET.SubElement(const, "AttributeList")
    ET.SubElement(al, "DataTypeName").text = "Int"
    ET.SubElement(al, "Name").text = name
    ET.SubElement(al, "Value").text = str(value)
    ol = ET.SubElement(const, "ObjectList")
    if existing_comment is not None:
        mlt = ET.SubElement(ol, "MultilingualText", {"CompositionName": "Comment"})
        inner_ol = ET.SubElement(mlt, "ObjectList")
        mlti = ET.SubElement(inner_ol, "MultilingualTextItem", {"CompositionName": "Items"})
        mlti_al = ET.SubElement(mlti, "AttributeList")
        ET.SubElement(mlti_al, "Culture").text = "es-ES"
        ET.SubElement(mlti_al, "Text").text = existing_comment
    return const


def test_inject_comment_crea_dentro_de_object_list() -> None:
    """Inyecta el comment DENTRO del ``ObjectList`` existente, no como hermano."""
    from zc_suite.simatic.ml import ModificadorConstantesUsuario

    const = _make_const("ENT_001", 1, existing_comment="")
    modifier = ModificadorConstantesUsuario.__new__(ModificadorConstantesUsuario)
    modifier._inyectar_comentario_multilingue(const, "Linea 1")

    comment_node = const.find("ObjectList/MultilingualText")
    assert comment_node is not None, (
        "Comment debe estar DENTRO de ObjectList, no como hermano"
    )
    assert comment_node.get("CompositionName") == "Comment"
    text_node = comment_node.find("ObjectList/MultilingualTextItem/AttributeList/Text")
    assert text_node is not None
    assert text_node.text == "Linea 1"

    direct_comment = const.find("Comment")
    assert direct_comment is None, (
        "NO debe existir Comment directo (hermano de AttributeList). "
        "TIA V21 rechaza este XML con OpennessAccessException."
    )


def test_inject_comment_actualiza_existente_sin_duplicar() -> None:
    """Si ya hay comment en el ``ObjectList``, lo actualiza (no duplica)."""
    from zc_suite.simatic.ml import ModificadorConstantesUsuario

    const = _make_const("ENT_001", 1, existing_comment="d")
    modifier = ModificadorConstantesUsuario.__new__(ModificadorConstantesUsuario)
    modifier._inyectar_comentario_multilingue(const, "Linea 1")

    multi_texts = const.findall("ObjectList/MultilingualText[@CompositionName='Comment']")
    assert len(multi_texts) == 1, f"Esperaba 1 MultilingualText, encontre {len(multi_texts)}."
    text_node = multi_texts[0].find("ObjectList/MultilingualTextItem/AttributeList/Text")
    assert text_node.text == "Linea 1"


def test_inject_comment_string_vacio_deja_text_vacio() -> None:
    """``text`` vacio deja ``Text`` vacio (no elimina la entrada)."""
    from zc_suite.simatic.ml import ModificadorConstantesUsuario

    const = _make_const("ENT_001", 1, existing_comment="d")
    modifier = ModificadorConstantesUsuario.__new__(ModificadorConstantesUsuario)
    modifier._inyectar_comentario_multilingue(const, "")

    text_node = const.find(
        "ObjectList/MultilingualText/ObjectList/MultilingualTextItem/AttributeList/Text"
    )
    assert text_node is not None
    assert text_node.text is None


def test_inject_comment_crea_object_list_si_no_existe() -> None:
    """Si el constant no tiene ``ObjectList``, lo crea (defensa para tests)."""
    from zc_suite.simatic.ml import ModificadorConstantesUsuario

    const = ET.Element("SW.Tags.PlcUserConstant")
    const.set("ID", "1")
    al = ET.SubElement(const, "AttributeList")
    ET.SubElement(al, "Name").text = "ENT_X"
    ET.SubElement(al, "Value").text = "1"

    modifier = ModificadorConstantesUsuario.__new__(ModificadorConstantesUsuario)
    modifier._inyectar_comentario_multilingue(const, "Test comment")

    object_list = const.find("ObjectList")
    assert object_list is not None
    text_node = object_list.find(
        "MultilingualText/ObjectList/MultilingualTextItem/AttributeList/Text"
    )
    assert text_node is not None
    assert text_node.text == "Test comment"


def test_modifier_update_user_constant_comment_genera_xml_valido() -> None:
    """E2E: ``actualizar_comentario`` genera XML estructuralmente valido."""
    from zc_suite.simatic.ml import ModificadorConstantesUsuario

    xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Document>\n"
        '  <SW.Tags.PlcTagTable ID="0">\n'
        "    <ObjectList>\n"
        '      <SW.Tags.PlcUserConstant ID="1">\n'
        "        <AttributeList><Name>ENT_001</Name><Value>1</Value></AttributeList>\n"
        "        <ObjectList>\n"
        '          <MultilingualText ID="2" CompositionName="Comment">\n'
        "            <ObjectList>\n"
        '              <MultilingualTextItem ID="3">\n'
        "                <AttributeList><Culture>es-ES</Culture><Text>d</Text></AttributeList>\n"
        "              </MultilingualTextItem>\n"
        "            </ObjectList>\n"
        "          </MultilingualText>\n"
        "        </ObjectList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        "    </ObjectList>\n"
        "  </SW.Tags.PlcTagTable>\n"
        "</Document>\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", delete=False, encoding="utf-8"
    ) as fichero:
        fichero.write(xml_content)
        ruta_xml = Path(fichero.name)

    try:
        modifier = ModificadorConstantesUsuario(ruta_xml)
        ok = modifier.actualizar_comentario("ENT_001", "Linea 1")
        assert ok is True

        const = modifier._root.find(".//SW.Tags.PlcUserConstant")
        direct_comment = const.find("Comment")
        assert direct_comment is None

        text_node = const.find(
            "ObjectList/MultilingualText/ObjectList/"
            "MultilingualTextItem/AttributeList/Text"
        )
        assert text_node is not None
        assert text_node.text == "Linea 1"
    finally:
        ruta_xml.unlink()
