"""Paridad con ``main`` de la edicion offline del sync.

Los ficheros de ``tests/fixtures/expected/sync/`` son la salida que produce el
codigo de ``main`` con los mismos datos de entrada: la comparacion es byte a
byte.

El fixture de la tabla de dispositivos se genero con el
``PlcUserConstantModifier`` de ``main`` sobre el mismo XML de entrada y los
mismos dispositivos anadidos que usa este test. El de los bloques es el mismo
que ya comprueba ``tests/simatic/test_paridad_simatic.py``.

TIA exporta con saltos CRLF y ``main`` escribe en Windows con CRLF, asi que
los fixtures de ``expected/`` van con CRLF y ``.gitattributes`` los deja
intactos (``tests/fixtures/** -text``). El XML de entrada se escribe con
CRLF explicitos: ElementTree devuelve los saltos tal cual los lee, y sin
fijarlos la salida cambiaria entre sistemas.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from zc_suite.areas.alimentacion.dispositivos.sincronizacion import (
    disp_copiar_y_editar,
)
from zc_suite.simatic.sd import confirmar_comentarios_array

#: Los bloques exportados que usa la app (los mismos de ``main``).
ORIGEN = Path(__file__).resolve().parents[3] / "fixtures" / "source" / "Bloques"

#: Las salidas que produce ``main`` con esos datos.
ESPERADO = Path(__file__).resolve().parents[3] / "fixtures" / "expected"

#: El XML de la tabla de constantes de usuario, antes de la edicion.
XML_ENTRADA = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<Document>\n"
    '  <SW.Tags.PlcTagTable ID="0">\n'
    "    <ObjectList>\n"
    '      <SW.Tags.PlcUserConstant ID="1">\n'
    "        <AttributeList>\n"
    "          <DataTypeName>Int</DataTypeName>\n"
    "          <Name>ED_000</Name>\n"
    "          <Value>0</Value>\n"
    "        </AttributeList>\n"
    "        <ObjectList>\n"
    '          <MultilingualText ID="2" CompositionName="Comment">\n'
    "            <ObjectList>\n"
    '              <MultilingualTextItem ID="3">\n'
    "                <AttributeList>\n"
    "                  <Culture>es-ES</Culture>\n"
    "                  <Text>DP-000</Text>\n"
    "                </AttributeList>\n"
    "              </MultilingualTextItem>\n"
    "            </ObjectList>\n"
    "          </MultilingualText>\n"
    "        </ObjectList>\n"
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
    "        <AttributeList><Name>N_MAX_DISP_ED</Name><Value>5</Value></AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    "    </ObjectList>\n"
    "  </SW.Tags.PlcTagTable>\n"
    "</Document>\n"
)

#: Los saltos de linea de los ficheros de TIA.
NEWLINE = "\r\n"


def test_el_xml_de_modified_sale_byte_a_byte_como_en_main(tmp_path: Path) -> None:
    """La tabla de dispositivos editada sale igual que en ``main``."""
    export = tmp_path / "export"
    export.mkdir()
    (export / "2000_Disp_ED.xml").write_text(XML_ENTRADA, encoding="utf-8", newline=NEWLINE)
    (export / "0_Config_Dispositivos.xml").write_text(
        XML_N_MAX, encoding="utf-8", newline=NEWLINE
    )
    modified = tmp_path / "modified"

    disp_copiar_y_editar(
        export,
        modified,
        [
            {
                "tabla": "2000_Disp_ED",
                "agregados": [
                    {"valor": "1", "plc_tag": "ED_001", "comment": "Entrada digital 1"},
                    {"valor": "2", "plc_tag": "ED_002"},
                ],
                "eliminados": [],
            }
        ],
    )

    assert (modified / "2000_Disp_ED.xml").read_bytes() == (
        ESPERADO / "sync" / "2000_Disp_ED.xml"
    ).read_bytes()


def test_la_tabla_de_n_max_no_llega_a_modified(tmp_path: Path) -> None:
    """La tabla de N_MAX no se copia: sus valores se aplican en linea."""
    export = tmp_path / "export"
    export.mkdir()
    (export / "2000_Disp_ED.xml").write_text(XML_ENTRADA, encoding="utf-8", newline=NEWLINE)
    (export / "0_Config_Dispositivos.xml").write_text(
        XML_N_MAX, encoding="utf-8", newline=NEWLINE
    )
    modified = tmp_path / "modified"

    disp_copiar_y_editar(
        export,
        modified,
        [
            {
                "tabla": "2000_Disp_ED",
                "agregados": [{"valor": "1", "plc_tag": "ED_001"}],
                "eliminados": [],
            }
        ],
    )

    assert not (modified / "0_Config_Dispositivos.xml").exists()


class _UuidFalso:
    """Un ``uuid4`` determinista: el MLC nuevo siempre es el mismo."""

    def __init__(self, valor: str) -> None:
        self._valor = valor

    @property
    def hex(self) -> str:
        return self._valor


def test_el_bloque_con_comentarios_sale_byte_a_byte_como_en_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El DB con los comentarios del slot sale igual que en ``main``."""
    monkeypatch.setattr("uuid.uuid4", lambda: _UuidFalso("aaaaa"))
    modified = tmp_path / "modified"
    modified.mkdir()
    dcl = modified / "DB2000_ED.s7dcl"
    res = modified / "DB2000_ED.s7res"
    shutil.copy(ORIGEN / "DB2000_ED.s7dcl", dcl)
    shutil.copy(ORIGEN / "DB2000_ED.s7res", res)

    confirmar_comentarios_array(
        dcl,
        res,
        "ED",
        {7: "DP-207 nuevo"},
        array_type="Simple",
        write_to_original=True,
    )

    assert dcl.read_bytes() == (ESPERADO / "DB2000_ED_inyectado.s7dcl").read_bytes()
    assert res.read_bytes() == (ESPERADO / "DB2000_ED_inyectado.s7res").read_bytes()
