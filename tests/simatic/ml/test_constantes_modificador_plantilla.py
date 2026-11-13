"""La plantilla de las constantes se guarda al cargar el XML.

Si se borran todas las constantes de una tabla, ya no queda ninguna con la
que clonar las nuevas: el alta se pierde en silencio. La plantilla se guarda
al cargar el XML, asi que sigue estando.
"""
from __future__ import annotations

from pathlib import Path

from zc_suite.simatic.ml import ModificadorConstantesUsuario

#: El XML de una tabla de tags con una sola constante.
XML_UNA_CONSTANTE = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<Document>\n"
    '  <SW.Tags.PlcTagTable ID="0">\n'
    "    <ObjectList>\n"
    '      <SW.Tags.PlcUserConstant ID="1">\n'
    "        <AttributeList>"
        "<Name>ENT_001</Name><DataTypeName>Int</DataTypeName><Value>1</Value>"
        "</AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    "    </ObjectList>\n"
    "  </SW.Tags.PlcTagTable>\n"
    "</Document>\n"
)


def _escribir_xml(ruta: Path) -> Path:
    """Escribe el XML de prueba y devuelve su ruta."""
    ruta.write_text(XML_UNA_CONSTANTE, encoding="utf-8")
    return ruta


def test_se_puede_anadir_tras_borrar_todas_las_constantes(tmp_path: Path) -> None:
    """Borrar la unica constante y anadir otra deja la constante nueva."""
    ruta = _escribir_xml(tmp_path / "6_Entidades.xml")
    modificador = ModificadorConstantesUsuario(ruta)

    eliminados = modificador.eliminar_constantes_por_nombre({"ENT_001"})
    anadidos = modificador.anadir_constantes_de_tabla(
        "6_Entidades", [{"plc_tag": "ENT_002", "valor": "2", "comment": ""}]
    )

    assert eliminados == 1
    assert anadidos == 1
    modificador.guardar(ruta)
    xml = ruta.read_text(encoding="utf-8")
    assert "<Name>ENT_002</Name>" in xml
    assert "<Name>ENT_001</Name>" not in xml


def test_el_xml_sin_constantes_no_rompe(tmp_path: Path) -> None:
    """Una tabla sin constantes no tiene plantilla: el alta no hace nada."""
    ruta = tmp_path / "6_Entidades.xml"
    ruta.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Document><SW.Tags.PlcTagTable ID=\"0\"><ObjectList /></SW.Tags.PlcTagTable></Document>\n",
        encoding="utf-8",
    )
    modificador = ModificadorConstantesUsuario(ruta)

    anadidos = modificador.anadir_constantes_de_tabla(
        "6_Entidades", [{"plc_tag": "ENT_002", "valor": "2", "comment": ""}]
    )

    assert anadidos == 0
