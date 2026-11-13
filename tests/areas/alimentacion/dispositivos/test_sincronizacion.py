"""El calculo de la sincronizacion de dispositivos.

Que cambios hay que meter en TIA y como se editan los ficheros en disco. Es
logica pura: aqui no hay ni portal de TIA ni transacciones.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.dispositivos.diferencias import (
    DiffNMax,
    DiffTabla,
)
from zc_suite.areas.alimentacion.dispositivos.sincronizacion import (
    COMENTARIO_SLOT_CERO,
    disp_calcular_cambios_dispositivos,
    disp_calcular_operaciones_n_max,
    disp_calcular_renombres,
    disp_copiar_y_editar,
    disp_localizar_xml,
    disp_mapa_comentarios,
)

#: El XML de una tabla de tags, tal y como lo exporta TIA en plano.
XML_TABLA = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<Document>\n"
    '  <SW.Tags.PlcTagTable ID="0">\n'
    "    <ObjectList>\n"
    '      <SW.Tags.PlcUserConstant ID="1">\n'
    "        <AttributeList><Name>ED_001</Name><Value>1</Value></AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    '      <SW.Tags.PlcUserConstant ID="2">\n'
    "        <AttributeList><Name>ED_099</Name><Value>99</Value></AttributeList>\n"
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
    "        <AttributeList><Name>N_MAX_DISP_ED</Name><Value>5</Value></AttributeList>\n"
    "      </SW.Tags.PlcUserConstant>\n"
    "    </ObjectList>\n"
    "  </SW.Tags.PlcTagTable>\n"
    "</Document>\n"
)


def _diff_tabla() -> DiffTabla:
    """El diff de una tabla: un alta, una baja y un renombrado."""
    return DiffTabla(
        tabla="2000_Disp_ED",
        base={"1": "ED_001", "2": "ED_002", "99": "ED_099"},
        deseado={"1": "ED_001", "2": "ED_002_NUEVO", "4": "ED_004"},
        agregados=["4"],
        eliminados=["99"],
        renombrados={"2": ("ED_002", "ED_002_NUEVO")},
    )


def _diff_n_max() -> DiffNMax:
    """El diff de los N_MAX: uno cambia y otro no."""
    return DiffNMax(
        tabla="0_Config_Dispositivos",
        actual={"N_MAX_DISP_ED": 5, "N_MAX_DISP_EA": 20},
        deseado={"N_MAX_DISP_ED": 8, "N_MAX_DISP_EA": 20},
        todos=[
            {
                "name": "N_MAX_DISP_ED",
                "actual": 5,
                "nuevo": 8,
                "status": "actualizar",
            },
            {
                "name": "N_MAX_DISP_EA",
                "actual": 20,
                "nuevo": 20,
                "status": "sin_cambios",
            },
        ],
        resumen={"actualizar": 1, "sin_cambios": 1, "total": 2},
    )


def test_localiza_el_xml_plano_y_el_de_jerarquia(tmp_path: Path) -> None:
    """El XML se encuentra plano o dentro de la carpeta de TIA."""
    plano = tmp_path / "plano"
    plano.mkdir()
    (plano / "2000_Disp_ED.xml").write_text(XML_TABLA, encoding="utf-8")
    assert disp_localizar_xml(plano, "2000_Disp_ED") == plano / "2000_Disp_ED.xml"

    jerarquia = tmp_path / "2000_Dispositivos"
    jerarquia.mkdir()
    (jerarquia / "2000_Disp_ED.xml").write_text(XML_TABLA, encoding="utf-8")
    assert disp_localizar_xml(tmp_path, "2000_Disp_ED") == jerarquia / "2000_Disp_ED.xml"

    assert disp_localizar_xml(tmp_path, "2000_Disp_EA") is None


def test_las_operaciones_de_n_max_solo_son_las_que_cambian() -> None:
    """Solo se propone cambiar el N_MAX cuyo valor no coincide."""
    operaciones = disp_calcular_operaciones_n_max("0_Config_Dispositivos", _diff_n_max())

    assert operaciones == [
        {"tabla": "0_Config_Dispositivos", "constante": "N_MAX_DISP_ED", "valor": 8}
    ]


def test_un_n_max_que_no_existe_en_tia_no_se_propone() -> None:
    """Una constante que no esta en TIA no se puede cambiar: no se propone."""
    diff = DiffNMax(
        tabla="0_Config_Dispositivos",
        actual={"N_MAX_DISP_ED": 5},
        deseado={"N_MAX_DISP_ED": 8, "N_MAX_DISP_SA": 30},
        todos=[
            {
                "name": "N_MAX_DISP_ED",
                "actual": 5,
                "nuevo": 8,
                "status": "actualizar",
            },
            {
                "name": "N_MAX_DISP_SA",
                "actual": None,
                "nuevo": 30,
                "status": "actualizar",
            },
        ],
        resumen={"actualizar": 2, "sin_cambios": 0, "total": 2},
    )

    operaciones = disp_calcular_operaciones_n_max("0_Config_Dispositivos", diff)

    assert operaciones == [
        {"tabla": "0_Config_Dispositivos", "constante": "N_MAX_DISP_ED", "valor": 8}
    ]


def test_sin_xml_de_n_max_no_se_propone_nada() -> None:
    """Sin el XML de TIA no se puede saber el valor actual: no se toca nada."""
    diff = DiffNMax(
        tabla="0_Config_Dispositivos",
        actual={},
        deseado={"N_MAX_DISP_ED": 8},
        todos=[],
        resumen={"actualizar": 0, "sin_cambios": 1, "total": 1},
        xml_ausente=True,
    )

    assert disp_calcular_operaciones_n_max("0_Config_Dispositivos", diff) == []


def test_los_renombres_son_los_del_diff() -> None:
    """Un dispositivo con otro ``plc_tag`` es un renombrado."""
    renombres = disp_calcular_renombres({"2000_Disp_ED": _diff_tabla()})

    assert renombres == [
        {"tabla": "2000_Disp_ED", "actual": "ED_002", "nuevo": "ED_002_NUEVO"}
    ]


def test_los_cambios_de_dispositivos_separan_altas_y_bajas() -> None:
    """Las altas llevan su valor y su nombre; las bajas, su valor."""
    cambios = disp_calcular_cambios_dispositivos({"2000_Disp_ED": _diff_tabla()})

    assert cambios == [
        {
            "tabla": "2000_Disp_ED",
            "agregados": [{"valor": "4", "plc_tag": "ED_004"}],
            "eliminados": ["99"],
        }
    ]


def test_una_tabla_sin_cambios_no_aparece() -> None:
    """Las tablas que no cambian no van al sync."""
    diff = DiffTabla(
        tabla="2000_Disp_EA",
        base={"1": "EA_001"},
        deseado={"1": "EA_001"},
        agregados=[],
        eliminados=[],
        renombrados={},
    )

    assert disp_calcular_cambios_dispositivos({"2000_Disp_EA": diff}) == []


def test_el_mapa_de_comentarios_deja_el_slot_cero_y_salta_los_duplicados() -> None:
    """El slot 0 no se usa y cada numero aparece una sola vez."""
    mapa = disp_mapa_comentarios(
        [
            {"numero": 1, "comentario_db": "DP-001"},
            {"numero": 1, "comentario_db": "otro"},
            {"numero": 0, "comentario_db": "no vale"},
            {"numero": 2, "comentario_db": "DP-002"},
            {"numero": 3},
        ]
    )

    assert mapa == {0: COMENTARIO_SLOT_CERO, 1: "DP-001", 2: "DP-002", 3: ""}


def _export(tmp_path: Path, xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str]) -> Path:
    """Un export con la tabla de dispositivos, la de N_MAX y otra sin cambios."""
    export = tmp_path / "export"
    export.mkdir()
    (export / "2000_Disp_ED.xml").write_text(XML_TABLA, encoding="utf-8")
    (export / "2000_Disp_EA.xml").write_text(
        xml_tabla("2000_Disp_EA", (("EA_001", 1),)), encoding="utf-8"
    )
    (export / "0_Config_Dispositivos.xml").write_text(XML_N_MAX, encoding="utf-8")
    return export


def test_la_copia_a_modified_no_lleva_la_tabla_de_n_max(
    tmp_path: Path,
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> None:
    """La tabla de N_MAX no se importa: sus valores se aplican en linea."""
    export = _export(tmp_path, xml_tabla)
    destino = tmp_path / "modified"

    disp_copiar_y_editar(
        export,
        destino,
        [{"tabla": "2000_Disp_ED", "agregados": [], "eliminados": []}],
    )

    assert (destino / "2000_Disp_ED.xml").is_file()
    assert not (destino / "0_Config_Dispositivos.xml").exists()


def test_la_edicion_offline_anade_y_quita_constantes(
    tmp_path: Path,
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> None:
    """El XML de ``modified/`` lleva el alta y ya no lleva la baja."""
    export = _export(tmp_path, xml_tabla)
    destino = tmp_path / "modified"

    resultado = disp_copiar_y_editar(
        export,
        destino,
        [
            {
                "tabla": "2000_Disp_ED",
                "agregados": [{"valor": "4", "plc_tag": "ED_004"}],
                "eliminados": ["99"],
            }
        ],
    )

    assert resultado["pedidos"] == 1
    assert resultado["escritos"] == 1
    assert resultado["eliminados"] == 1
    assert resultado["parciales"] == []

    from zc_suite.simatic.ml import ModificadorConstantesUsuario

    modificador = ModificadorConstantesUsuario(destino / "2000_Disp_ED.xml")
    assert modificador.leer_constantes_con_valores() == {"1": "ED_001", "4": "ED_004"}


def test_un_xml_que_no_esta_no_impide_el_resto(
    tmp_path: Path,
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> None:
    """Una tabla sin XML se avisa, pero las demas se aplican."""
    export = _export(tmp_path, xml_tabla)
    destino = tmp_path / "modified"

    resultado = disp_copiar_y_editar(
        export,
        destino,
        [
            {
                "tabla": "2000_Disp_ED",
                "agregados": [{"valor": "4", "plc_tag": "ED_004"}],
                "eliminados": [],
            },
            {
                "tabla": "2000_Disp_SA",
                "agregados": [{"valor": "2", "plc_tag": "SA_002"}],
                "eliminados": [],
            },
        ],
    )

    assert resultado["escritos"] == 1
    assert resultado["parciales"] == ["2000_Disp_SA: 0/1 (XML no encontrado)"]


def test_sin_cambios_no_se_copia_nada(tmp_path: Path) -> None:
    """Sin cambios no hay nada que editar."""
    export = tmp_path / "export"
    export.mkdir()
    destino = tmp_path / "modified"

    resultado = disp_copiar_y_editar(export, destino, [])

    assert resultado == {"pedidos": 0, "escritos": 0, "eliminados": 0, "parciales": []}
    assert list(destino.rglob("*.xml")) == []


def test_el_origen_que_no_existe_no_es_un_error(tmp_path: Path) -> None:
    """Un export vacio no rompe el sync: se avisa y se sigue."""
    resultado = disp_copiar_y_editar(
        tmp_path / "no_existe",
        tmp_path / "modified",
        [{"tabla": "2000_Disp_ED", "agregados": [], "eliminados": []}],
    )

    assert resultado["pedidos"] == 0


def test_los_cambios_usan_el_valor_como_clave(tmp_path: Path) -> None:
    """El numero del dispositivo es el ``<Value>`` de la constante."""
    cambios: list[dict[str, Any]] = [
        {
            "tabla": "2000_Disp_ED",
            "agregados": [{"valor": "4", "plc_tag": "ED_004"}],
            "eliminados": ["99"],
        }
    ]

    assert cambios[0]["agregados"][0]["valor"] == "4"
    assert cambios[0]["eliminados"] == ["99"]
