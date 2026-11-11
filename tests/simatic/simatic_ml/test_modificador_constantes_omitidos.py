"""Tests de los tags omitidos al escribir las tablas de dispositivos.

El diff razona por ``valor`` (el ``<Value>`` del ``PlcUserConstant``) y el
modificador razona por ``nombre`` (el ``<Name>``). Un add cuyo nombre ya
existe en la tabla (con otro valor) no se puede escribir: el modificador lo
descarta y el preview, que lo contaba, promete mas tags de los que acaban
en TIA.

El descarte no puede ser silencioso: el operador tiene que ver cuantos tags
se han escrito de verdad y cuales se han quedado fuera.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

TABLA = "2000_Disp_ED"

XML_TABLA = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<Document>\n"
    '  <SW.Tags.PlcTagTable ID="0">\n'
    "    <ObjectList>\n"
    '      <SW.Tags.PlcUserConstant ID="1">\n'
    "        <AttributeList><Name>ED_000</Name><Value>0</Value></AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    "    </ObjectList>\n"
    "  </SW.Tags.PlcTagTable>\n"
    "</Document>\n"
)

LOGGER = "zc_suite.simatic.simatic_ml.modificador_constantes"


def _escribir_xml(path: Path, contenido: str) -> Path:
    path.write_text(contenido, encoding="utf-8")
    return path


def _modifier(path: Path) -> object:
    from zc_suite.simatic.simatic_ml import ModificadorConstantesUsuario

    return ModificadorConstantesUsuario(path)


def test_add_omite_el_nombre_que_ya_existe_y_lo_avisa(caplog: object) -> None:
    """Un add con nombre ya presente se omite y se dice cual es."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _escribir_xml(Path(tmp) / f"{TABLA}.xml", XML_TABLA)
        modifier = _modifier(path)
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            added = modifier.anadir_constantes_de_tabla(
                TABLA,
                [
                    {"valor": "1", "plc_tag": "ED_001"},
                    {"valor": "0", "plc_tag": "ED_000"},
                ],
            )

    assert added == 1, "Solo se escribe el nombre que no existe."
    assert "ED_000" in caplog.text, caplog.text
    assert "el nombre ya existe" in caplog.text


def test_add_omite_el_plc_tag_vacio_y_lo_avisa(caplog: object) -> None:
    """Un add sin ``plc_tag`` se omite y se avisa."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _escribir_xml(Path(tmp) / f"{TABLA}.xml", XML_TABLA)
        modifier = _modifier(path)
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            added = modifier.anadir_constantes_de_tabla(
                TABLA,
                [{"valor": "1", "plc_tag": "  "}],
            )

    assert added == 0
    assert "plc_tag vacio" in caplog.text


def test_add_no_avisa_si_no_hay_omitidos(caplog: object) -> None:
    """Sin omitidos no hay warning (el log normal no es ruido)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _escribir_xml(Path(tmp) / f"{TABLA}.xml", XML_TABLA)
        modifier = _modifier(path)
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            added = modifier.anadir_constantes_de_tabla(
                TABLA, [{"valor": "1", "plc_tag": "ED_001"}]
            )

    assert added == 1
    assert "omitidos" not in caplog.text
