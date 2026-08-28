"""Tests del fix de IDs duplicados en TagTableModifier.

Reproduce el bug que el operario vio en PLC_PST con TIA V21:
"Duplicate Simatic ML ID '1' found at line number 85 and line position 6.
This ID was previously used at line number 9 and line position 8."

Causa: ``_max_id_in_doc`` usaba ``int(id_str, 0)`` que NO parsea
hexadecimal sin prefijo (``A``, ``B``, ``FF``...). Resultado: cuando
el BASE exportado por TIA tenia IDs ``A``, ``B``, ``C``, el calculo del
max ID se quedaba corto y los nuevos constants colisionaban.

Estos tests usan un XML real exportado por TIA (en ``_source/``) y
verifican que tras ``add_user_constants_by_table`` no queden IDs
duplicados en el documento resultante.
"""
from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OPERATOR_XML = _REPO_ROOT / "_source" / ".build_cache" / "base" / "tags" / "2000_Dispositivos" / "2000_Disp_M.xml"


def _load_modifier() -> ModuleType:
    """Carga ``core.infrastructure.xml.modifiers`` evitando el circular import.

    ``modifiers.py`` importa ``from areas.alimentacion.domain.models.dispositivos
    import Dispositivo`` en su cabecera, lo que dispara toda la cadena de
    imports del paquete areas y vuelve a ``modifiers`` antes de que termine
    de cargarse. Para evitarlo, cargamos el modulo como un script suelto
    via ``importlib.util.spec_from_file_location``.
    """
    mod_path = _REPO_ROOT / "core" / "infrastructure" / "xml" / "modifiers.py"
    spec = importlib.util.spec_from_file_location("_modifiers_isolated", mod_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def TagTableModifier():
    return _load_modifier().TagTableModifier


_PLC_USER_CONSTANT = "{*}SW.Tags.PlcUserConstant"
_NAME_TAG = "{*}Name"


def _all_ids(root: ET.Element) -> list[str]:
    """Devuelve la lista plana de todos los atributos ID del documento."""
    return [e.get("ID") for e in root.iter() if "ID" in e.attrib]


def _constants(root: ET.Element) -> list[ET.Element]:
    return root.findall(f".//{_PLC_USER_CONSTANT}")


def test_max_id_in_doc_handles_hex_without_prefix(TagTableModifier):
    """El bug original: int('A', 0) falla. Ahora int('A', 16) funciona."""
    # XML minimo con IDs hexadecimales SIN prefijo 0x (formato Siemens).
    xml = (
        '<Document>'
        '<SW.Tags.PlcTagTable ID="0">'
        '<ObjectList>'
        '<SW.Tags.PlcUserConstant ID="1"><AttributeList><Name>A</Name></AttributeList></SW.Tags.PlcUserConstant>'
        '<SW.Tags.PlcUserConstant ID="A"><AttributeList><Name>B</Name></AttributeList></SW.Tags.PlcUserConstant>'
        '<SW.Tags.PlcUserConstant ID="FF"><AttributeList><Name>C</Name></AttributeList></SW.Tags.PlcUserConstant>'
        '</ObjectList>'
        '</SW.Tags.PlcTagTable>'
        '</Document>'
    )
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
        f.write(xml)
        f.flush()
        mod = TagTableModifier(f.name)

    try:
        # 0xFF = 255
        assert mod._max_id_in_doc() == 0xFF, (
            f"_max_id_in_doc debe parsear hex sin prefijo; "
            f"obtuvo {mod._max_id_in_doc()} (0x{mod._max_id_in_doc():X}), "
            f"esperaba 255 (0xFF)"
        )
    finally:
        Path(f.name).unlink(missing_ok=True)


def test_add_user_constants_no_duplicate_ids(tmp_path, TagTableModifier):
    """Caso real del operario: 4 constantes con IDs A,B,C, se anaden 4 mas.

    ANTES del fix: max_id=9 (ignoraba A,B,C) -> nuevos colisionaban.
    DESPUES del fix: max_id=12 -> nuevos arrancan en 0xD, 0x10, 0x13, 0x16.
    """

    # XML minimo equivalente al 2000_Disp_M.xml del operario
    # (4 constantes con subtrees 1,2,3 / 4,5,6 / 7,8,9 / A,B,C).
    xml = '''<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Tags.PlcTagTable ID="0">
    <ObjectList>
      <SW.Tags.PlcUserConstant ID="1" CompositionName="UserConstants">
        <AttributeList><DataTypeName>Int</DataTypeName><Name>A</Name><Value>1</Value></AttributeList>
        <ObjectList>
          <MultilingualText ID="2" CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem ID="3" CompositionName="Items">
                <AttributeList><Culture>es-ES</Culture><Text>txt</Text></AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcUserConstant>
      <SW.Tags.PlcUserConstant ID="4" CompositionName="UserConstants">
        <AttributeList><DataTypeName>Int</DataTypeName><Name>B</Name><Value>2</Value></AttributeList>
        <ObjectList>
          <MultilingualText ID="5" CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem ID="6" CompositionName="Items">
                <AttributeList><Culture>es-ES</Culture><Text>txt</Text></AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcUserConstant>
      <SW.Tags.PlcUserConstant ID="7" CompositionName="UserConstants">
        <AttributeList><DataTypeName>Int</DataTypeName><Name>C</Name><Value>3</Value></AttributeList>
        <ObjectList>
          <MultilingualText ID="8" CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem ID="9" CompositionName="Items">
                <AttributeList><Culture>es-ES</Culture><Text>txt</Text></AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcUserConstant>
      <SW.Tags.PlcUserConstant ID="A" CompositionName="UserConstants">
        <AttributeList><DataTypeName>Int</DataTypeName><Name>D</Name><Value>4</Value></AttributeList>
        <ObjectList>
          <MultilingualText ID="B" CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem ID="C" CompositionName="Items">
                <AttributeList><Culture>es-ES</Culture><Text>txt</Text></AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcUserConstant>
    </ObjectList>
  </SW.Tags.PlcTagTable>
</Document>
'''
    src = tmp_path / "test.xml"
    src.write_text(xml, encoding="utf-8")
    mod = TagTableModifier(src)

    # Sanity: el max real es 0xC
    assert mod._max_id_in_doc() == 0xC

    # Anadimos 4 nuevas constantes. Mismas 3 IDs en cada subtree (1,2,3).
    to_add = [
        {"plc_tag": f"NEW_{i}", "uid": str(10 + i)}
        for i in range(4)
    ]
    n = mod.add_user_constants_by_table("test", to_add)
    assert n == 4

    out = tmp_path / "out.xml"
    mod.save(out)

    # Verificacion critica: 0 IDs duplicados en todo el documento.
    root = ET.parse(out).getroot()
    ids = _all_ids(root)
    assert len(ids) == len(set(ids)), (
        f"Hay IDs duplicados tras add_user_constants_by_table! "
        f"Total={len(ids)}, unique={len(set(ids))}. "
        f"Duplicados: {[i for i in set(ids) if ids.count(i) > 1]}"
    )

    # Las 4 nuevas constantes tienen IDs > 0xC
    consts = _constants(root)
    assert len(consts) == 8
    new_consts = [c for c in consts if c.get("ID") not in {"1", "4", "7", "A"}]
    assert len(new_consts) == 4
    for c in new_consts:
        cid = int(c.get("ID"), 16)
        assert cid > 0xC, f"Nuevo constant {c.get('ID')} colisiona con IDs existentes"


@pytest.mark.skipif(
    not _OPERATOR_XML.exists(),
    reason="Requiere _source/.build_cache/base/tags/2000_Disp_M.xml (XML real del operario)",
)
def test_add_user_constants_against_real_operator_xml(tmp_path, TagTableModifier):
    """Test E2E con el XML REAL de 2000_Disp_M del operario.

    Esto reproduce EXACTAMENTE el escenario que causo el error
    'Duplicate Simatic ML ID' en TIA V21.
    """

    # Copiamos el XML real a tmp
    dst = tmp_path / "2000_Disp_M.xml"
    dst.write_bytes(_OPERATOR_XML.read_bytes())

    mod = TagTableModifier(dst)

    # El BASE tiene 4 constantes con max ID = 0xC (12).
    # El test anterior con el XML minimo ya cubre la logica; este test
    # añade los 6 adds exactos del preview (4 ya existen -> 2 omitidos).
    to_add = [
        {"plc_tag": f"M_0{i:02d}", "uid": str(5 + i), "comment": "test"}
        for i in range(1, 7)
    ]
    n = mod.add_user_constants_by_table("2000_Disp_M", to_add)
    # M_003 y M_004 ya existen -> se omiten
    assert n == 4

    out = tmp_path / "out.xml"
    mod.save(out)

    root = ET.parse(out).getroot()
    ids = _all_ids(root)
    assert len(ids) == len(set(ids)), (
        f"DUPLICADO contra XML real del operario! "
        f"Total={len(ids)}, unique={len(set(ids))}. "
        f"Duplicados: {[i for i in set(ids) if ids.count(i) > 1]}"
    )


def test_renumber_ids_increments_correctly(TagTableModifier):
    """_renumber_ids asigna IDs correlativos en hex mayusculas."""
    # Elemento con IDs existentes 1, 2, 3. Usamos un wrapper Document porque
    # ET.fromstring devuelve el root, que en este caso es <Document> (sin ID).
    xml = (
        '<Document>'
        '<X ID="1"><Y ID="2"><Z ID="3"/></Y></X>'
        '</Document>'
    )
    doc = ET.fromstring(xml)
    elem = doc.find("X")  # el nodo real con ID

    TagTableModifier._renumber_ids(elem, start=0xA)
    # Tras renumerar con start=0xA: 0xA, 0xB, 0xC
    assert elem.get("ID") == "A"
    assert elem.find("Y").get("ID") == "B"
    assert elem.find("Y").find("Z").get("ID") == "C"


def test_regenerate_root_table_id_assigns_unique_high_id(TagTableModifier, tmp_path):
    """regenerate_root_table_id cambia el ID="0" de la PlcTagTable a uno alto.

    Caso del operario: TIA V21 exporta con ID="0" y al re-importar intenta
    CREAR (no UPDATE) la tabla, fallando con "Cannot create the object...
    already exists". El fix asigna un ID unico alto (max+0x10000) para que
    TIA vea que no existe y haga UPDATE.
    """
    xml = '''<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Tags.PlcTagTable ID="0">
    <AttributeList><Name>2000_Disp_M</Name></AttributeList>
    <ObjectList>
      <SW.Tags.PlcUserConstant ID="1">
        <AttributeList><DataTypeName>Int</DataTypeName><Name>A</Name><Value>1</Value></AttributeList>
      </SW.Tags.PlcUserConstant>
      <SW.Tags.PlcUserConstant ID="4">
        <AttributeList><DataTypeName>Int</DataTypeName><Name>B</Name><Value>2</Value></AttributeList>
      </SW.Tags.PlcUserConstant>
      <SW.Tags.PlcUserConstant ID="A">
        <AttributeList><DataTypeName>Int</DataTypeName><Name>C</Name><Value>3</Value></AttributeList>
      </SW.Tags.PlcUserConstant>
    </ObjectList>
  </SW.Tags.PlcTagTable>
</Document>
'''
    src = tmp_path / "test.xml"
    src.write_text(xml, encoding="utf-8")
    mod = TagTableModifier(src)

    # Antes: tabla con ID="0", max en doc = 0xA
    table = mod._root.find(".//{*}SW.Tags.PlcTagTable")
    assert table.get("ID") == "0"
    assert mod._max_id_in_doc() == 0xA

    # Accion
    new_id = mod.regenerate_root_table_id()
    assert new_id is not None
    # Debe ser max(0xA) + 0x10000 = 0x1000A
    assert new_id == "1000A", f"Esperaba '1000A', obtuvo '{new_id}'"
    # La tabla ahora tiene el nuevo ID
    assert table.get("ID") == "1000A"
    # El metodo marco el modifier como modificado
    assert mod.was_modified()


def test_regenerate_root_table_id_no_collision_with_existing(tmp_path, TagTableModifier):
    """El nuevo ID debe ser MAYOR que cualquier ID existente en el doc."""
    xml = '''<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Tags.PlcTagTable ID="0">
    <ObjectList>
      <SW.Tags.PlcUserConstant ID="1"><AttributeList><Name>A</Name></AttributeList></SW.Tags.PlcUserConstant>
      <SW.Tags.PlcUserConstant ID="FF"><AttributeList><Name>B</Name></AttributeList></SW.Tags.PlcUserConstant>
      <SW.Tags.PlcUserConstant ID="1234"><AttributeList><Name>C</Name></AttributeList></SW.Tags.PlcUserConstant>
    </ObjectList>
  </SW.Tags.PlcTagTable>
</Document>
'''
    src = tmp_path / "test.xml"
    src.write_text(xml, encoding="utf-8")
    mod = TagTableModifier(src)
    new_id = mod.regenerate_root_table_id()

    # max en doc = 0x1234 = 4660
    # new = 4660 + 65536 = 70196 = 0x11224
    expected = f"{0x1234 + 0x10000:X}"
    assert new_id == expected, f"Esperaba '{expected}', obtuvo '{new_id}'"

    # Verificar que el nuevo ID no choca con ninguno existente
    all_ids = [e.get("ID") for e in mod._root.iter() if "ID" in e.attrib]
    assert all_ids.count(new_id) == 1, (
        f"ID regenerado '{new_id}' aparece más de una vez en el documento"
    )


def test_regenerate_root_table_id_returns_none_if_no_table(TagTableModifier, tmp_path):
    """Si no hay PlcTagTable, devuelve None (no rompe)."""
    xml = (
        '<Document>'
        '<Other ID="1"/>'
        '</Document>'
    )
    src = tmp_path / "test.xml"
    src.write_text(xml, encoding="utf-8")
    mod = TagTableModifier(src)
    assert mod.regenerate_root_table_id() is None


@pytest.mark.skipif(
    not _OPERATOR_XML.exists(),
    reason="Requiere _source/.build_cache/base/tags/2000_Disp_M.xml (XML real del operario)",
)
def test_regenerate_root_table_id_against_real_operator_xml(TagTableModifier, tmp_path):
    """E2E con XML real: regenera el ID de la PlcTagTable del operario."""
    dst = tmp_path / "2000_Disp_M.xml"
    dst.write_bytes(_OPERATOR_XML.read_bytes())
    mod = TagTableModifier(dst)

    table = mod._root.find(".//{*}SW.Tags.PlcTagTable")
    assert table is not None
    assert table.get("ID") == "0", "Esperaba ID='0' del export de TIA"

    new_id = mod.regenerate_root_table_id()
    assert new_id is not None
    # Verificar formato Siemens: hex mayuscula
    int(new_id, 16)
    # Y que es > cualquier ID existente (max real = 0xC = 12)
    assert int(new_id, 16) > 12
    assert table.get("ID") == new_id
