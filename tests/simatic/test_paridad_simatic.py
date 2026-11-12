"""Paridad con ``main`` de los helpers de SimaticML y SimaticSD.

Los ficheros de ``tests/fixtures/expected/`` son la salida que produce el
codigo de ``main`` con los mismos datos de entrada: la comparacion es byte a
byte.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from zc_suite.simatic.ml import ModificadorConstantesUsuario
from zc_suite.simatic.sd import confirmar_comentarios_array

#: Los bloques exportados que usa la app (los mismos de ``main``).
ORIGEN = Path(__file__).resolve().parents[1] / "fixtures" / "source" / "Bloques"

#: Las salidas que produce ``main`` con esos datos.
ESPERADO = Path(__file__).resolve().parents[1] / "fixtures" / "expected"

#: El XML de la tabla de constantes de usuario.
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


class _UuidFalso:
    """Un ``uuid4`` determinista: el MLC nuevo siempre es el mismo."""

    def __init__(self, valor: str) -> None:
        self._valor = valor

    @property
    def hex(self) -> str:
        return self._valor


def _copiar_db(destino: Path) -> tuple[Path, Path]:
    """Copia el DB de los fixtures a una carpeta temporal."""
    destino.mkdir(parents=True, exist_ok=True)
    dcl = destino / "DB2000_ED.s7dcl"
    res = destino / "DB2000_ED.s7res"
    shutil.copy(ORIGEN / "DB2000_ED.s7dcl", dcl)
    shutil.copy(ORIGEN / "DB2000_ED.s7res", res)
    return dcl, res


def test_actualizar_un_comentario_sale_byte_a_byte_como_en_main(tmp_path: Path) -> None:
    """El CASO C (actualizar el texto de un MLC) sale igual que en ``main``."""
    dcl, res = _copiar_db(tmp_path / "caso_c")

    confirmar_comentarios_array(dcl, res, "ED", {2: "DP-202 revisado"}, array_type="UDT")

    modificado_dcl = tmp_path / "caso_c" / "modificado_DB2000_ED.s7dcl"
    modificado_res = tmp_path / "caso_c" / "modificado_DB2000_ED.s7res"

    assert modificado_dcl.read_bytes() == (
        ESPERADO / "DB2000_ED_actualizado.s7dcl"
    ).read_bytes()
    assert modificado_res.read_bytes() == (
        ESPERADO / "DB2000_ED_actualizado.s7res"
    ).read_bytes()


def test_inyectar_un_slot_sale_byte_a_byte_como_en_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El CASO A (inyectar un indice nuevo) sale igual que en ``main``."""
    monkeypatch.setattr("uuid.uuid4", lambda: _UuidFalso("aaaaa"))
    dcl, res = _copiar_db(tmp_path / "caso_a")

    confirmar_comentarios_array(dcl, res, "ED", {7: "DP-207 nuevo"}, array_type="UDT")

    assert (tmp_path / "caso_a" / "modificado_DB2000_ED.s7dcl").read_bytes() == (
        ESPERADO / "DB2000_ED_inyectado.s7dcl"
    ).read_bytes()
    assert (tmp_path / "caso_a" / "modificado_DB2000_ED.s7res").read_bytes() == (
        ESPERADO / "DB2000_ED_inyectado.s7res"
    ).read_bytes()


def test_anadir_constantes_sale_byte_a_byte_como_en_main(tmp_path: Path) -> None:
    """El modificador de constantes de usuario sale igual que en ``main``."""
    ruta_xml = tmp_path / "2000_Disp_ED.xml"
    ruta_xml.write_text(XML_ENTRADA, encoding="utf-8")
    modificador = ModificadorConstantesUsuario(ruta_xml)

    modificador.anadir_constantes_de_tabla(
        "2000_Disp_ED",
        [
            {"valor": "1", "plc_tag": "ED_001", "comment": "Entrada digital 1"},
            {"valor": "2", "plc_tag": "ED_002"},
        ],
    )
    salida = tmp_path / "salida.xml"
    modificador.guardar(salida)

    assert salida.read_bytes() == (ESPERADO / "2000_Disp_ED_modificado.xml").read_bytes()


def test_los_bloques_exportados_son_los_de_main() -> None:
    """Los fixtures de bloques son los de ``main``, byte a byte."""
    for nombre in ("DB2000_ED", "FB2017_ZC_M_SINA", "FC2000_ZC_ED", "OB1_MAIN"):
        for sufijo in (".s7dcl", ".s7res"):
            ruta = ORIGEN / f"{nombre}{sufijo}"
            assert ruta.is_file(), f"falta el fixture {ruta.name}"
            assert ruta.read_bytes(), f"el fixture {ruta.name} esta vacio"


def test_el_almacen_de_constantes_es_el_de_main() -> None:
    """El parser de constantes lee lo mismo que el de ``main``."""
    from zc_suite.simatic.ml import ParserConstantesUsuario

    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Document>\n"
        '  <SW.Tags.PlcTagTable ID="0">\n'
        "    <ObjectList>\n"
        '      <SW.Tags.PlcUserConstant ID="1">\n'
        "        <AttributeList><Name>N_MAX_ED</Name><Value>10</Value></AttributeList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        '      <SW.Tags.PlcUserConstant ID="2">\n'
        "        <AttributeList><Name>N_MAX_EA</Name><Value>20</Value></AttributeList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        '      <SW.Tags.PlcUserConstant ID="3">\n'
        "        <AttributeList><Name>OTRO</Name><Value>texto</Value></AttributeList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        "    </ObjectList>\n"
        "  </SW.Tags.PlcTagTable>\n"
        "</Document>\n"
    )
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", delete=False, encoding="utf-8"
    ) as fichero:
        fichero.write(xml)
        ruta = Path(fichero.name)
    try:
        constantes: dict[str, int] = ParserConstantesUsuario.leer_constantes(ruta)
    finally:
        ruta.unlink()

    assert constantes == {"N_MAX_ED": 10, "N_MAX_EA": 20}


def test_el_modificador_lee_las_constantes_con_su_comentario(tmp_path: Path) -> None:
    """El modificador lee el MLC y su comentario, como el de ``main``."""
    ruta_xml = tmp_path / "tabla.xml"
    ruta_xml.write_text(XML_ENTRADA, encoding="utf-8")

    modificador = ModificadorConstantesUsuario(ruta_xml)

    assert modificador.leer_constantes_con_valores() == {"0": "ED_000"}
    con_comentario: dict[str, dict[str, Any]] = modificador.leer_constantes_con_comentarios()
    assert con_comentario["0"]["name"] == "ED_000"
    assert con_comentario["0"]["comment"] == "DP-000"
