"""Paridad con ``main`` de la edicion offline del sync de entidades.

El fichero de ``tests/fixtures/expected/entidades/`` es la salida que produce el
codigo de ``main`` (su ``PlcUserConstantModifier``) con los mismos datos de
entrada: la comparacion es byte a byte.

TIA exporta con saltos CRLF y ``main`` escribe en Windows con CRLF, asi que
los fixtures de ``expected/`` van con CRLF y ``.gitattributes`` los deja
intactos (``tests/fixtures/** -text``). El XML de entrada se escribe con
CRLF explicitos: ElementTree devuelve los saltos tal cual los lee, y sin
fijarlos la salida cambiaria entre sistemas.
"""
from __future__ import annotations

from pathlib import Path

from zc_suite.areas.alimentacion.entidades.sincronizacion import ent_copiar_y_editar

#: Las salidas que produce ``main`` con esos datos.
ESPERADO = Path(__file__).resolve().parents[3] / "fixtures" / "expected" / "entidades"

#: Los saltos de linea de los ficheros de TIA.
NEWLINE = "\r\n"

#: El XML de la tabla de entidades, antes de la edicion.
XML_ENTRADA = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<Document>\n"
    '  <SW.Tags.PlcTagTable ID="0">\n'
    "    <ObjectList>\n"
    '      <SW.Tags.PlcUserConstant ID="1">\n'
    "        <AttributeList>\n"
    "          <DataTypeName>Int</DataTypeName>\n"
    "          <Name>ENT_001</Name>\n"
    "          <Value>1</Value>\n"
    "        </AttributeList>\n"
    "        <ObjectList>\n"
    '          <MultilingualText ID="2" CompositionName="Comment">\n'
    "            <ObjectList>\n"
    '              <MultilingualTextItem ID="3">\n'
    "                <AttributeList>\n"
    "                  <Culture>es-ES</Culture>\n"
    "                  <Text>Comentario antiguo</Text>\n"
    "                </AttributeList>\n"
    "              </MultilingualTextItem>\n"
    "            </ObjectList>\n"
    "          </MultilingualText>\n"
    "        </ObjectList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    '      <SW.Tags.PlcUserConstant ID="4">\n'
    "        <AttributeList>\n"
    "          <DataTypeName>Int</DataTypeName>\n"
    "          <Name>ENT_099</Name>\n"
    "          <Value>99</Value>\n"
    "        </AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    "    </ObjectList>\n"
    "  </SW.Tags.PlcTagTable>\n"
    "</Document>\n"
)

#: El XML de la tabla de N_MAX, que no se importa.
XML_N_MAX = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<Document>\n"
    '  <SW.Tags.PlcTagTable ID="0">\n'
    "    <ObjectList>\n"
    '      <SW.Tags.PlcUserConstant ID="1">\n'
    "        <AttributeList><Name>N_MAX_ENTIDAD</Name><Value>3</Value></AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    "    </ObjectList>\n"
    "  </SW.Tags.PlcTagTable>\n"
    "</Document>\n"
)

#: Las operaciones de constantes que aplica el sync de entidades.
OPERACIONES = [
    {"kind": "add", "plc_tag": "ENT_002_NUEVO", "valor": 2, "comment": "Comentario dos"},
    {"kind": "remove", "plc_tag": "ENT_099"},
    {"kind": "rename_comment", "plc_tag": "ENT_001", "new_comment": "Comentario uno"},
]


def _exportacion(tmp_path: Path) -> Path:
    """Prepara la exportacion: la tabla de entidades y la de N_MAX."""
    export = tmp_path / "export"
    tabla = export / "6_Entidades"
    tabla.mkdir(parents=True)
    (tabla / "6_Entidades.xml").write_text(XML_ENTRADA, encoding="utf-8", newline=NEWLINE)
    (export / "0_Config_Generales.xml").write_text(XML_N_MAX, encoding="utf-8", newline=NEWLINE)
    return export


def test_el_xml_de_modified_sale_byte_a_byte_como_en_main(tmp_path: Path) -> None:
    """La tabla de entidades editada sale igual que en ``main``."""
    export = _exportacion(tmp_path)
    modified = tmp_path / "modified"

    ent_copiar_y_editar(
        export,
        modified,
        tmp_path / "bloques_export",
        tmp_path / "bloques_modified",
        "0_Config_Generales",
        "6_Entidades",
        "6_Entidades",
        "DB6_ENT",
        "ENT",
        OPERACIONES,
        [],
    )

    assert (modified / "6_Entidades" / "6_Entidades.xml").read_bytes() == (
        ESPERADO / "6_Entidades.xml"
    ).read_bytes()


def test_la_tabla_de_n_max_no_llega_a_modified(tmp_path: Path) -> None:
    """La tabla de N_MAX no se copia: su valor se aplica en linea."""
    export = _exportacion(tmp_path)
    modified = tmp_path / "modified"

    ent_copiar_y_editar(
        export,
        modified,
        tmp_path / "bloques_export",
        tmp_path / "bloques_modified",
        "0_Config_Generales",
        "6_Entidades",
        "6_Entidades",
        "DB6_ENT",
        "ENT",
        OPERACIONES,
        [],
    )

    assert not (modified / "0_Config_Generales.xml").exists()


def test_el_rename_conserva_la_constante(tmp_path: Path) -> None:
    """Un rename se materializa en un alta: la constante no se pierde.

    ``main`` anade antes de borrar, asi que el alta de un nombre que ya
    existe se descarta y la constante desaparece del PLC. Aqui la baja va
    primero, asi que la constante queda con el nombre nuevo.
    """
    export = _exportacion(tmp_path)
    modified = tmp_path / "modified"

    ent_copiar_y_editar(
        export,
        modified,
        tmp_path / "bloques_export",
        tmp_path / "bloques_modified",
        "0_Config_Generales",
        "6_Entidades",
        "6_Entidades",
        "DB6_ENT",
        "ENT",
        [
            {"kind": "remove", "plc_tag": "ENT_001"},
            {"kind": "add", "plc_tag": "ENT_001_NUEVO", "valor": 1, "comment": ""},
        ],
        [],
    )

    xml = (modified / "6_Entidades" / "6_Entidades.xml").read_text(encoding="utf-8")
    assert "ENT_001_NUEVO" in xml
    assert "<Name>ENT_001</Name>" not in xml
