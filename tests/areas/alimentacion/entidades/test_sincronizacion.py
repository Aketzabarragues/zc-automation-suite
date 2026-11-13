"""El calculo de la sincronizacion de entidades.

Que cambios hay que meter en TIA y como se editan los ficheros en disco. Es
logica pura: aqui no hay ni portal de TIA ni transacciones.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.entidades.diferencias import DiffEntidades, DiffNMax
from zc_suite.areas.alimentacion.entidades.sincronizacion import (
    ent_calcular_operaciones_comentarios,
    ent_calcular_operaciones_constantes,
    ent_calcular_operaciones_n_max,
    ent_copiar_y_editar,
    ent_mapa_de_comentarios,
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
"""

#: La carpeta de TIA donde viven la tabla de tags y el DB de las entidades.
CARPETA_TIA = "6_Entidades"


def _diff_constantes() -> DiffEntidades:
    """Un diff de constantes: un alta, una baja y un renombre."""
    return DiffEntidades(
        tabla="6_Entidades",
        base={"ENT_001": 1, "ENT_002": 2},
        deseado={"ENT_002_NUEVO": 2, "ENT_003": 3},
        agregados=["ENT_003"],
        eliminados=["ENT_001"],
        renombrados={},
        operaciones=[
            {"kind": "delete", "plc_tag": "ENT_001", "value_tia": 1},
            {
                "kind": "rename",
                "plc_tag_tia": "ENT_002",
                "value_tia": 2,
                "plc_tag_new": "ENT_002_NUEVO",
            },
            {
                "kind": "add",
                "plc_tag": "ENT_003",
                "value_excel": 3,
                "comment_excel": "TRES",
            },
            {
                "kind": "update_comment",
                "plc_tag": "ENT_002_NUEVO",
                "value_tia": 2,
                "comment_tia": None,
                "comment_excel": "DOS",
            },
            {"kind": "sin_cambios", "plc_tag": "ENT_001", "value_tia": 1},
        ],
    )


def _diff_n_max() -> DiffNMax:
    """El diff de un N_MAX que hay que actualizar."""
    return DiffNMax(
        tabla="0_Config_Generales",
        actual={"N_MAX_ENTIDAD": 3},
        deseado={"N_MAX_ENTIDAD": 5},
        todos=[
            {
                "name": "N_MAX_ENTIDAD",
                "actual": 3,
                "nuevo": 5,
                "status": "actualizar",
            }
        ],
        resumen={"actualizar": 1, "sin_cambios": 0, "total": 1},
    )


# ── las operaciones ─────────────────────────────────────────────────────────


def test_las_operaciones_de_n_max_solo_cubren_las_existentes() -> None:
    """Una constante que no esta en TIA no se puede cambiar: no se propone."""
    diff = DiffNMax(
        tabla="0_Config_Generales",
        actual={},
        deseado={"N_MAX_ENTIDAD": 5},
        todos=[
            {
                "name": "N_MAX_ENTIDAD",
                "actual": None,
                "nuevo": 5,
                "status": "actualizar",
            }
        ],
        resumen={"actualizar": 1, "sin_cambios": 0, "total": 1},
    )

    assert ent_calcular_operaciones_n_max("0_Config_Generales", diff) == []


def test_las_operaciones_de_n_max() -> None:
    """La operacion de N_MAX lleva la tabla, la constante y el valor."""
    operaciones = ent_calcular_operaciones_n_max("0_Config_Generales", _diff_n_max())

    assert operaciones == [
        {"tabla": "0_Config_Generales", "constante": "N_MAX_ENTIDAD", "valor": 5}
    ]


def test_las_operaciones_de_constantes() -> None:
    """Las operaciones del diff se traducen a las del modificador offline."""
    operaciones = ent_calcular_operaciones_constantes(_diff_constantes())

    assert operaciones == [
        {"kind": "remove", "plc_tag": "ENT_001"},
        {"kind": "remove", "plc_tag": "ENT_002"},
        {"kind": "add", "plc_tag": "ENT_002_NUEVO", "valor": 2, "comment": ""},
        {"kind": "add", "plc_tag": "ENT_003", "valor": 3, "comment": "TRES"},
        {"kind": "rename_comment", "plc_tag": "ENT_002_NUEVO", "new_comment": "DOS"},
    ]


def test_las_operaciones_de_comentarios_salen_del_excel() -> None:
    """Una operacion por entidad con comentario: manda el Excel."""
    entidades = [
        {"numero": 1, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_001", "plc_comentario": "UNO"},
        {"numero": 2, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_002", "plc_comentario": ""},
    ]

    operaciones = ent_calcular_operaciones_comentarios(entidades)

    assert operaciones == [
        {"kind": "update_comment", "slot": 1, "new_comment": "UNO"}
    ]


def test_el_mapa_de_comentarios() -> None:
    """El mapa ``{slot: comentario}`` que se pasa a la escritura del SD."""
    operaciones = ent_calcular_operaciones_comentarios(
        [
            {"numero": 1, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_001", "plc_comentario": "UNO"},
            {"numero": 2, "plc_name": "ZC_PLC_STD", "plc_tag": "ENT_002", "plc_comentario": "DOS"},
        ]
    )

    assert ent_mapa_de_comentarios(operaciones) == {1: "UNO", 2: "DOS"}


# ── la edicion offline ──────────────────────────────────────────────────────


def _preparar_export(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Prepara las carpetas del export y devuelve las cuatro rutas."""
    variables_export = tmp_path / "variables" / "export"
    variables_modified = tmp_path / "variables" / "modified"
    bloques_export = tmp_path / "bloques" / "export"
    bloques_modified = tmp_path / "bloques" / "modified"

    carpeta_variables = variables_export / CARPETA_TIA
    carpeta_variables.mkdir(parents=True)
    (carpeta_variables / "6_Entidades.xml").write_text(XML_ENTIDADES, encoding="utf-8")
    (carpeta_variables / "0_Config_Generales.xml").write_text(XML_N_MAX, encoding="utf-8")

    carpeta_bloques = bloques_export / CARPETA_TIA
    carpeta_bloques.mkdir(parents=True)
    (carpeta_bloques / "DB6_ENT.s7dcl").write_text(DCL_ENTIDADES, encoding="utf-8-sig")
    (carpeta_bloques / "DB6_ENT.s7res").write_text(RES_ENTIDADES, encoding="utf-8-sig")

    return variables_export, variables_modified, bloques_export, bloques_modified


def test_la_copia_excluye_la_tabla_de_n_max(tmp_path: Path) -> None:
    """La tabla de N_MAX no llega al import: su valor ya se aplico en linea."""
    variables_export, variables_modified, bloques_export, bloques_modified = _preparar_export(
        tmp_path
    )

    ent_copiar_y_editar(
        variables_export,
        variables_modified,
        bloques_export,
        bloques_modified,
        "0_Config_Generales",
        "6_Entidades",
        CARPETA_TIA,
        "DB6_ENT",
        "ENT",
        [],
        [],
    )

    assert (variables_modified / CARPETA_TIA / "6_Entidades.xml").is_file()
    assert not (variables_modified / CARPETA_TIA / "0_Config_Generales.xml").exists()


def test_la_edicion_escribe_las_constantes(tmp_path: Path) -> None:
    """Las altas, las bajas y los comentarios quedan en el XML de ``modified/``."""
    variables_export, variables_modified, bloques_export, bloques_modified = _preparar_export(
        tmp_path
    )
    operaciones = ent_calcular_operaciones_constantes(_diff_constantes())

    resultado = ent_copiar_y_editar(
        variables_export,
        variables_modified,
        bloques_export,
        bloques_modified,
        "0_Config_Generales",
        "6_Entidades",
        CARPETA_TIA,
        "DB6_ENT",
        "ENT",
        operaciones,
        [],
    )

    xml = (variables_modified / CARPETA_TIA / "6_Entidades.xml").read_text(encoding="utf-8")
    assert "<Name>ENT_001</Name>" not in xml
    assert "<Name>ENT_002</Name>" not in xml
    assert "<Name>ENT_002_NUEVO</Name>" in xml
    assert "<Name>ENT_003</Name>" in xml
    assert resultado["eliminados"] == 2
    assert resultado["anadidos"] == 2


def test_la_edicion_escribe_los_comentarios_del_db(tmp_path: Path) -> None:
    """Los comentarios del array se escriben en el par SimaticSD."""
    variables_export, variables_modified, bloques_export, bloques_modified = _preparar_export(
        tmp_path
    )
    operaciones = ent_calcular_operaciones_comentarios(
        [
            {
                "numero": 1,
                "plc_name": "ZC_PLC_STD",
                "plc_tag": "ENT_001",
                "plc_comentario": "NUEVO UNO",
            }
        ]
    )

    resultado = ent_copiar_y_editar(
        variables_export,
        variables_modified,
        bloques_export,
        bloques_modified,
        "0_Config_Generales",
        "6_Entidades",
        CARPETA_TIA,
        "DB6_ENT",
        "ENT",
        [],
        operaciones,
    )

    res = (bloques_modified / CARPETA_TIA / "DB6_ENT.s7res").read_text(encoding="utf-8-sig")
    assert "NUEVO UNO" in res
    assert resultado["comentarios"] == 1


def test_sin_cambios_no_se_toca_nada(tmp_path: Path) -> None:
    """Sin operaciones, la copia se hace pero no se edita nada."""
    variables_export, variables_modified, bloques_export, bloques_modified = _preparar_export(
        tmp_path
    )

    resultado = ent_copiar_y_editar(
        variables_export,
        variables_modified,
        bloques_export,
        bloques_modified,
        "0_Config_Generales",
        "6_Entidades",
        CARPETA_TIA,
        "DB6_ENT",
        "ENT",
        [],
        [],
    )

    xml = (variables_modified / CARPETA_TIA / "6_Entidades.xml").read_text(encoding="utf-8")
    assert xml == XML_ENTIDADES
    assert resultado["anadidos"] == 0
    assert resultado["eliminados"] == 0
    assert resultado["avisos"] == []


def test_sin_export_avisa(tmp_path: Path) -> None:
    """Si no hay export, el aviso lo dice y el sync sigue."""
    resultado = ent_copiar_y_editar(
        tmp_path / "variables" / "export",
        tmp_path / "variables" / "modified",
        tmp_path / "bloques" / "export",
        tmp_path / "bloques" / "modified",
        "0_Config_Generales",
        "6_Entidades",
        CARPETA_TIA,
        "DB6_ENT",
        "ENT",
        [],
        [],
    )

    assert len(resultado["avisos"]) == 2


def test_el_xml_de_las_constantes_que_no_esta_avisa(tmp_path: Path) -> None:
    """Si el XML de la tabla no esta, las constantes se omiten con aviso."""
    variables_export, variables_modified, bloques_export, bloques_modified = _preparar_export(
        tmp_path
    )
    (variables_export / CARPETA_TIA / "6_Entidades.xml").unlink()

    resultado: dict[str, Any] = ent_copiar_y_editar(
        variables_export,
        variables_modified,
        bloques_export,
        bloques_modified,
        "0_Config_Generales",
        "6_Entidades",
        CARPETA_TIA,
        "DB6_ENT",
        "ENT",
        [{"kind": "add", "plc_tag": "ENT_003", "valor": 3, "comment": ""}],
        [],
    )

    assert len(resultado["avisos"]) == 1
    assert resultado["anadidos"] == 0
