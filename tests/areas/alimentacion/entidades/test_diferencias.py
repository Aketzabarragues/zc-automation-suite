"""El diff de las entidades: las constantes de usuario y los comentarios.

Que cambia entre lo que hay en TIA y lo que dice el Excel. Es logica pura:
aqui no hay ni portal de TIA ni transacciones.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.entidades.diferencias import (
    ent_calcular_diff_comentarios,
    ent_calcular_diff_constantes,
    ent_calcular_diff_n_max,
    ent_detectar_inconsistencias,
    ent_resumen,
)

#: El XML de la tabla de entidades, tal y como lo exporta TIA en plano.
XML_ENTIDADES = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<Document>\n"
    '  <SW.Tags.PlcTagTable ID="0">\n'
    "    <ObjectList>\n"
    '      <SW.Tags.PlcUserConstant ID="1">\n'
    "        <AttributeList><Name>ENT_001</Name><Value>1</Value></AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    '      <SW.Tags.PlcUserConstant ID="2">\n'
    "        <AttributeList><Name>ENT_002</Name><Value>2</Value></AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    '      <SW.Tags.PlcUserConstant ID="3">\n'
    "        <AttributeList><Name>ENT_003</Name><Value>3</Value></AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    '      <SW.Tags.PlcUserConstant ID="4">\n'
    "        <AttributeList><Name>ENT_099</Name><Value>99</Value></AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    "    </ObjectList>\n"
    "  </SW.Tags.PlcTagTable>\n"
    "</Document>\n"
)

#: El XML de la tabla de N_MAX.
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

#: El par SimaticSD del DB de entidades.
DCL_ENTIDADES = """{
    S7_Author := "HCR";
    S7_BlockComment := "MLC_32c";
    S7_BlockNumber := "6";
    S7_BlockTitle := "MLC_wT";
    S7_Family := "ZeusControl";
    S7_Optimized := "TRUE";
    S7_StandardRetain := "TRUE";
    S7_Version := "1.0"
}
DATA_BLOCK DB6_ENT
    VAR
        "ENT" : Array[0.._.N_MAX_ENTIDAD] of _.UDT_ZC_ENT;
    END_VAR

        { S7_MLC := "MLC_a1" }
        ENT[0] := ();
        { S7_MLC := "MLC_b2" }
        ENT[1] := ();
        { S7_MLC := "MLC_c3" }
        ENT[2] := ();
END_DATA_BLOCK
"""

RES_ENTIDADES = """MultiLingualTexts:
  - id: MLC_wT
    es-ES: DB6_ENT
  - id: MLC_32c
    es-ES: Bloque de datos de entidades
  - id: MLC_a1
    es-ES: .
  - id: MLC_b2
    es-ES: ENTIDAD UNO
  - id: MLC_c3
    es-ES: ENTIDAD DOS
"""


def _escribir_xml(ruta: Path, contenido: str) -> Path:
    """Escribe un XML de prueba y devuelve su ruta."""
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def _entidades() -> list[dict[str, Any]]:
    """Las entidades del Excel: un alta, una baja, un renombre y un comentario.

    ``ENT_003`` se queda igual (mismo nombre, mismo valor y sin comentario),
    asi que sale como ``sin_cambios``.
    """
    return [
        {"numero": 1, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_001", "plc_comentario": "UNO"},
        {
            "numero": 2,
            "plc_name": "ZC_PLC_STD",
            "plc_tag": "ENT_002_NUEVO",
            "plc_comentario": "DOS",
        },
        {"numero": 3, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_003", "plc_comentario": ""},
        {"numero": 4, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_004", "plc_comentario": ""},
    ]


def _entidades_comentarios() -> list[dict[str, Any]]:
    """Las entidades del Excel para el diff de comentarios del array."""
    return [
        {"numero": 1, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_001", "plc_comentario": "UNO"},
        {
            "numero": 2,
            "plc_name": "ZC_PLC_STD",
            "plc_tag": "ENT_002",
            "plc_comentario": "ENTIDAD DOS",
        },
        {"numero": 4, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_004", "plc_comentario": ""},
    ]


# ── las constantes ───────────────────────────────────────────────────────────


def test_el_diff_de_constantes_detecta_altas_y_bajas(tmp_path: Path) -> None:
    """Las diferencias de las constantes de usuario."""
    xml = _escribir_xml(tmp_path / "6_Entidades.xml", XML_ENTIDADES)

    diff = ent_calcular_diff_constantes("6_Entidades", _entidades(), xml)

    assert diff.agregados == ["ENT_004"]
    assert diff.eliminados == ["ENT_099"]
    assert diff.xml_ausente is False


def test_el_diff_de_constantes_sin_xml_no_falla(tmp_path: Path) -> None:
    """Sin XML de TIA, todas las entidades salen como altas."""
    diff = ent_calcular_diff_constantes("6_Entidades", _entidades(), tmp_path / "nada.xml")

    assert diff.xml_ausente is True
    assert diff.base == {}
    assert diff.agregados == ["ENT_001", "ENT_002_NUEVO", "ENT_003", "ENT_004"]


def test_el_diff_de_constantes_ordena_las_operaciones(tmp_path: Path) -> None:
    """Las operaciones van en el orden en que las aplica el sync."""
    xml = _escribir_xml(tmp_path / "6_Entidades.xml", XML_ENTIDADES)

    diff = ent_calcular_diff_constantes("6_Entidades", _entidades(), xml)

    kinds = [operacion["kind"] for operacion in diff.operaciones]
    assert kinds == ["delete", "rename", "add", "update_comment", "update_comment", "sin_cambios"]
    assert diff.operaciones[0] == {"kind": "delete", "plc_tag": "ENT_099", "value_tia": 99}
    assert diff.operaciones[1] == {
        "kind": "rename",
        "plc_tag_tia": "ENT_002",
        "value_tia": 2,
        "plc_tag_new": "ENT_002_NUEVO",
    }


def test_el_rename_por_valor_cambia_el_nombre_y_conserva_el_valor(tmp_path: Path) -> None:
    """Un ``plc_tag`` de TIA con el valor de otro del Excel es un rename."""
    xml = _escribir_xml(tmp_path / "6_Entidades.xml", XML_ENTIDADES)

    diff = ent_calcular_diff_constantes("6_Entidades", _entidades(), xml)

    renombres = [
        operacion for operacion in diff.operaciones if operacion["kind"] == "rename"
    ]
    assert renombres == [
        {
            "kind": "rename",
            "plc_tag_tia": "ENT_002",
            "value_tia": 2,
            "plc_tag_new": "ENT_002_NUEVO",
        }
    ]


def test_el_rename_trae_el_comentario_del_excel(tmp_path: Path) -> None:
    """El rename se materializa como remove + add y ademas cambia el comentario."""
    xml = _escribir_xml(tmp_path / "6_Entidades.xml", XML_ENTIDADES)

    diff = ent_calcular_diff_constantes("6_Entidades", _entidades(), xml)

    comentarios = [
        operacion
        for operacion in diff.operaciones
        if operacion["kind"] == "update_comment"
    ]
    assert comentarios == [
        {
            "kind": "update_comment",
            "plc_tag": "ENT_001",
            "value_tia": 1,
            "comment_tia": None,
            "comment_excel": "UNO",
        },
        {
            "kind": "update_comment",
            "plc_tag": "ENT_002_NUEVO",
            "value_tia": 2,
            "comment_tia": None,
            "comment_excel": "DOS",
        },
    ]


def test_el_mismo_nombre_con_otro_valor_se_borra_y_se_anade(tmp_path: Path) -> None:
    """El mismo plc_tag con otro valor es un borrado y un alta."""
    xml = _escribir_xml(tmp_path / "6_Entidades.xml", XML_ENTIDADES)
    entidades = [
        {"numero": 7, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_001", "plc_comentario": ""},
    ]

    diff = ent_calcular_diff_constantes("6_Entidades", entidades, xml)

    operaciones = [
        operacion
        for operacion in diff.operaciones
        if operacion["kind"] in ("delete", "add")
        and operacion["plc_tag"] == "ENT_001"
    ]
    assert operaciones == [
        {"kind": "delete", "plc_tag": "ENT_001", "value_tia": 1},
        {"kind": "add", "plc_tag": "ENT_001", "value_excel": 7, "comment_excel": None},
    ]


def test_los_comentarios_de_tia_se_leen_del_xml(tmp_path: Path) -> None:
    """El comentario de cada constante se lee del XML."""
    xml = _escribir_xml(tmp_path / "6_Entidades.xml", XML_ENTIDADES)

    diff = ent_calcular_diff_constantes("6_Entidades", _entidades(), xml)

    assert diff.comentarios_base == {
        "ENT_001": None,
        "ENT_002": None,
        "ENT_003": None,
        "ENT_099": None,
    }


# ── los comentarios ─────────────────────────────────────────────────────────


def test_el_diff_de_comentarios_lee_los_slots_de_tia() -> None:
    """Los slots del array y sus comentarios actuales."""
    diff = ent_calcular_diff_comentarios(
        "DB6_ENT",
        "ENT",
        _entidades_comentarios(),
        DCL_ENTIDADES,
        RES_ENTIDADES,
    )

    assert diff.slots_tia == {0, 1, 2}
    assert diff.actuales[1] == "ENTIDAD UNO"
    assert diff.xml_ausente is False


def test_el_diff_de_comentarios_distingue_cambios_y_sin_cambios() -> None:
    """El slot 1 cambia, el 2 se queda y el 4 es una alta."""
    diff = ent_calcular_diff_comentarios(
        "DB6_ENT",
        "ENT",
        _entidades_comentarios(),
        DCL_ENTIDADES,
        RES_ENTIDADES,
    )

    assert diff.actualizados == [1]
    assert diff.sin_cambios == [2]
    assert diff.agregados == [4]


def test_el_diff_de_comentarios_no_elimina_los_slots_de_tia() -> None:
    """Los slots que hay en TIA y no en el Excel se preservan."""
    entidades = [
        {"numero": 1, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_001", "plc_comentario": "UNO"}
    ]

    diff = ent_calcular_diff_comentarios(
        "DB6_ENT",
        "ENT",
        entidades,
        DCL_ENTIDADES,
        RES_ENTIDADES,
    )

    assert diff.eliminados == []
    assert diff.actualizados == [1]


def test_el_diff_de_comentarios_sin_ficheros_avisa() -> None:
    """Sin el par SimaticSD, el diff sale vacio pero valido."""
    diff = ent_calcular_diff_comentarios("DB6_ENT", "ENT", _entidades(), "", "")

    assert diff.xml_ausente is True
    assert diff.slots_tia == set()
    assert diff.agregados == [1, 2, 3, 4]


# ── el N_MAX ────────────────────────────────────────────────────────────────


def test_el_diff_del_n_max_de_entidades(tmp_path: Path) -> None:
    """El N_MAX de las entidades se compara como los de los dispositivos."""
    xml = _escribir_xml(tmp_path / "0_Config_Generales.xml", XML_N_MAX)

    diff = ent_calcular_diff_n_max("0_Config_Generales", {"N_MAX_ENTIDAD": 5}, xml)

    assert diff.actual == {"N_MAX_ENTIDAD": 3}
    assert diff.resumen == {"actualizar": 1, "sin_cambios": 0, "total": 1}


def test_el_diff_del_n_max_sin_xml(tmp_path: Path) -> None:
    """Sin el XML, el N_MAX sale como xml ausente."""
    diff = ent_calcular_diff_n_max(
        "0_Config_Generales", {"N_MAX_ENTIDAD": 5}, tmp_path / "nada.xml"
    )

    assert diff.xml_ausente is True
    assert diff.todos == []


# ── los avisos y el resumen ─────────────────────────────────────────────────


def test_se_avisa_de_un_plc_tag_no_canonico(tmp_path: Path) -> None:
    """Una constante de TIA que no sigue la regla ``ENT_<X>`` es un aviso."""
    xml = _escribir_xml(
        tmp_path / "6_Entidades.xml",
        XML_ENTIDADES.replace("ENT_099", "Constant_1"),
    )
    entidades = [
        *_entidades(),
        {"numero": 99, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_099", "plc_comentario": ""},
    ]

    diff = ent_calcular_diff_constantes("6_Entidades", entidades, xml)
    avisos = ent_detectar_inconsistencias(diff)

    assert len(avisos) == 1
    assert "Constant_1" in avisos[0]


def test_no_se_avisa_de_una_constante_suelta(tmp_path: Path) -> None:
    """Una constante que no se solapa con el Excel no es un aviso."""
    xml = _escribir_xml(tmp_path / "6_Entidades.xml", XML_ENTIDADES)

    diff = ent_calcular_diff_constantes("6_Entidades", _entidades(), xml)
    avisos = ent_detectar_inconsistencias(diff)

    assert avisos == []


def test_el_resumen_suma_los_cambios(tmp_path: Path) -> None:
    """El resumen cuenta las constantes y los comentarios."""
    xml = _escribir_xml(tmp_path / "6_Entidades.xml", XML_ENTIDADES)
    diff_constantes = ent_calcular_diff_constantes("6_Entidades", _entidades(), xml)
    diff_comentarios = ent_calcular_diff_comentarios(
        "DB6_ENT", "ENT", _entidades_comentarios(), DCL_ENTIDADES, RES_ENTIDADES
    )

    resumen = ent_resumen(diff_constantes, diff_comentarios)

    assert resumen["constants_agregados"] == 1
    assert resumen["constants_eliminados"] == 1
    assert resumen["constants_sin_cambios"] == 2
    assert resumen["comments_updated"] == 1
    assert resumen["comments_added"] == 1
    assert resumen["total"] == 4
