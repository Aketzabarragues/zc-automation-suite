"""El diff de un proceso: los comentarios de los slots y los N_MAX.

Que cambia entre lo que hay en TIA y lo que dice el Excel. Es logica pura:
aqui no hay ni portal de TIA ni transacciones.
"""
from __future__ import annotations

from pathlib import Path

from zc_suite.areas.alimentacion.procesos.diferencias import (
    SATELITES_POR_ARRAY,
    DiffNMax,
    proc_calcular_arrays,
    proc_calcular_diff_n_max,
    proc_resumen,
)
from zc_suite.areas.alimentacion.procesos.mapa import MapaProceso

#: El XML de la tabla del proceso, con los N_MAX tal y como los exporta TIA.
XML_N_MAX = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<Document>\n"
    '  <SW.Tags.PlcTagTable ID="0">\n'
    "    <ObjectList>\n"
    '      <SW.Tags.PlcUserConstant ID="1">\n'
    '        <AttributeList><Name>100_N_MAX_PREAL</Name><Value>3</Value></AttributeList>\n'
    '      </SW.Tags.PlcUserConstant>\n'
    '      <SW.Tags.PlcUserConstant ID="2">\n'
    '        <AttributeList><Name>100_N_MAX_PINT</Name><Value>2</Value></AttributeList>\n'
    '      </SW.Tags.PlcUserConstant>\n'
    '      <SW.Tags.PlcUserConstant ID="3">\n'
    '        <AttributeList><Name>100_N_MAX_ALM</Name><Value>16</Value></AttributeList>\n'
    '      </SW.Tags.PlcUserConstant>\n'
    '      <SW.Tags.PlcUserConstant ID="4">\n'
    '        <AttributeList><Name>100_N_MAX_ALM_HMI</Name><Value>2</Value></AttributeList>\n'
    '      </SW.Tags.PlcUserConstant>\n'
    '      <SW.Tags.PlcUserConstant ID="5">\n'
    '        <AttributeList><Name>OTRA_CONSTANTE</Name><Value>99</Value></AttributeList>\n'
    '      </SW.Tags.PlcUserConstant>\n'
    "    </ObjectList>\n"
    '  </SW.Tags.PlcTagTable>\n'
    "</Document>\n"
)


# ── los pares SimaticSD de prueba ────────────────────────────────────────────


def _dcl_param() -> str:
    """El ``.s7dcl`` del DB_PARAM: PReal[0..3], PInt[0..2] (PInt[2] sin MLC)."""
    return (
        "END_DATA_BLOCK_MARKER\n"
        "DATA_BLOCK DB53100_CPR_PARAM\n"
        "    VAR\n"
        '        "PReal" : Array[0..3] of _.UDT_ZC_PREAL;\n'
        '        "PInt" : Array[0..2] of _.UDT_ZC_PINT;\n'
        "    END_VAR\n"
        '        { S7_MLC := "MLC_pr0" }\n'
        "        PReal[0] := ();\n"
        '        { S7_MLC := "MLC_pr1" }\n'
        "        PReal[1] := ();\n"
        '        { S7_MLC := "MLC_pr2" }\n'
        "        PReal[2] := ();\n"
        '        { S7_MLC := "MLC_pr3" }\n'
        "        PReal[3] := ();\n"
        '        { S7_MLC := "MLC_pi0" }\n'
        "        PInt[0] := ();\n"
        '        { S7_MLC := "MLC_pi1" }\n'
        "        PInt[1] := ();\n"
        "END_DATA_BLOCK\n"
    )


def _res_param() -> str:
    """El ``.s7res`` del DB_PARAM: los textos ``es-ES`` de los MLC."""
    return (
        "MultiLingualTexts:\n"
        "  - id: MLC_pr0\n"
        "    es-ES: NO USAR\n"
        "  - id: MLC_pr1\n"
        "    es-ES: Un real\n"
        "  - id: MLC_pr2\n"
        "    es-ES: Otro real\n"
        "  - id: MLC_pr3\n"
        "    es-ES: .\n"
        "  - id: MLC_pi0\n"
        "    es-ES: NO USAR\n"
        "  - id: MLC_pi1\n"
        "    es-ES: Un entero\n"
    )


def _dcl_alm() -> str:
    """El ``.s7dcl`` del DB_ALM: ALM[0..2] (Simple)."""
    return (
        "DATA_BLOCK DB55100_CPR_ALM\n"
        "    VAR\n"
        '        "ALM" : Array[0..2] of Int;\n'
        "    END_VAR\n"
        '        { S7_MLC := "MLC_alm0" }\n'
        "        ALM[0] := 0;\n"
        '        { S7_MLC := "MLC_alm1" }\n'
        "        ALM[1] := 1;\n"
        '        { S7_MLC := "MLC_alm2" }\n'
        "        ALM[2] := 2;\n"
        "END_DATA_BLOCK\n"
    )


def _res_alm() -> str:
    """El ``.s7res`` del DB_ALM."""
    return (
        "MultiLingualTexts:\n"
        "  - id: MLC_alm0\n"
        "    es-ES: NO USAR\n"
        "  - id: MLC_alm1\n"
        "    es-ES: Una alarma\n"
        "  - id: MLC_alm2\n"
        "    es-ES: Otra alarma\n"
    )


def _mapa() -> MapaProceso:
    """El mapa del proceso: PReal 1..3, PInt 1..2, ALM 1..2."""
    return MapaProceso(
        preal={0: "NO USAR", 1: "Un real", 2: "Otro real", 3: "Nuevo real"},
        pint={0: "NO USAR", 1: "Un entero", 2: "Otro entero"},
        alm={0: "NO USAR", 1: "Una alarma", 2: "Otra alarma"},
        db_param_name="DB53100_CPR_PARAM",
        db_alm_name="DB55100_CPR_ALM",
        table_name="100_CPR",
        table_present=True,
    )


# ── el diff de los comentarios ───────────────────────────────────────────────


def test_los_arrays_tienen_la_shape_de_main() -> None:
    """Cada array sale con ``db_name``, ``array_name``, ``satellite_arrays``,
    ``current_count``, ``desired_count`` y ``slot_map``."""
    arrays = proc_calcular_arrays(_mapa(), _dcl_param(), _res_param(), _dcl_alm(), _res_alm())

    assert set(arrays) == {"PReal", "PInt", "ALM"}
    preal = arrays["PReal"]
    assert preal["db_name"] == "DB53100_CPR_PARAM"
    assert preal["array_name"] == "PReal"
    assert preal["satellite_arrays"] == ["PReal_Vis", "Aux.PReal_ValorAnterior"]
    assert preal["desired_count"] == 4  # slots 0..3 del Excel
    assert arrays["PInt"]["db_name"] == "DB53100_CPR_PARAM"
    assert arrays["ALM"]["db_name"] == "DB55100_CPR_ALM"
    assert arrays["ALM"]["satellite_arrays"] == []


def test_el_slot_cero_no_sale_en_el_diff() -> None:
    """El slot ``0`` (placeholder ``"NO USAR"``) no aparece en el ``slot_map``."""
    arrays = proc_calcular_arrays(_mapa(), _dcl_param(), _res_param(), _dcl_alm(), _res_alm())

    assert "0" not in arrays["PReal"]["slot_map"]
    assert "0" not in arrays["PInt"]["slot_map"]
    assert "0" not in arrays["ALM"]["slot_map"]


def test_un_slot_sin_cambios_sale_sin_cambios() -> None:
    """Un slot con el mismo comentario en TIA y en el Excel es ``sin_cambios``."""
    arrays = proc_calcular_arrays(_mapa(), _dcl_param(), _res_param(), _dcl_alm(), _res_alm())

    assert arrays["PReal"]["slot_map"]["1"] == {
        "current": "Un real",
        "desired": "Un real",
        "action": "sin_cambios",
    }
    assert arrays["ALM"]["slot_map"]["1"] == {
        "current": "Una alarma",
        "desired": "Una alarma",
        "action": "sin_cambios",
    }


def test_un_slot_con_otro_comentario_sale_renombrar() -> None:
    """Un slot con comentario distinto en TIA y en el Excel es ``renombrar``."""
    arrays = proc_calcular_arrays(_mapa(), _dcl_param(), _res_param(), _dcl_alm(), _res_alm())

    # PReal[3]: TIA tiene ".", el Excel quiere "Nuevo real".
    assert arrays["PReal"]["slot_map"]["3"] == {
        "current": ".",
        "desired": "Nuevo real",
        "action": "renombrar",
    }
    # PInt[2]: TIA no lo tiene (current=None) -> "agregar" (como ``main``: el
    # apply lo crea, con comentario o sin).
    assert arrays["PInt"]["slot_map"]["2"] == {
        "current": None,
        "desired": "Otro entero",
        "action": "agregar",
    }
    # PInt[1]: TIA tiene "Un entero" y el Excel lo igual -> sin_cambios.
    assert arrays["PInt"]["slot_map"]["1"] == {
        "current": "Un entero",
        "desired": "Un entero",
        "action": "sin_cambios",
    }


def test_un_slot_nuevo_con_punto_sale_agregar() -> None:
    """Un slot del Excel que no esta en TIA y cuyo comentario deseado es
    ``"."`` sale como ``agregar``."""
    mapa = MapaProceso(
        preal={0: "NO USAR", 1: "Un real", 5: "."},
        db_param_name="DB53100_CPR_PARAM",
        db_alm_name="DB55100_CPR_ALM",
        table_name="100_CPR",
    )
    arrays = proc_calcular_arrays(mapa, _dcl_param(), _res_param(), _dcl_alm(), _res_alm())

    assert arrays["PReal"]["slot_map"]["5"] == {
        "current": None,
        "desired": ".",
        "action": "agregar",
    }


def test_un_slot_de_tia_que_no_esta_en_el_excel_sale_eliminar() -> None:
    """Un slot de TIA con comentario historico que no esta en el Excel es
    ``eliminar``."""
    # PInt[1] no esta en el Excel del mapa, pero TIA lo tiene con "Un entero".
    mapa = MapaProceso(
        preal={0: "NO USAR"},
        pint={0: "NO USAR"},
        alm={0: "NO USAR"},
        db_param_name="DB53100_CPR_PARAM",
        db_alm_name="DB55100_CPR_ALM",
        table_name="100_CPR",
    )
    arrays = proc_calcular_arrays(mapa, _dcl_param(), _res_param(), _dcl_alm(), _res_alm())

    # PReal[1..3] estan en TIA pero no en el Excel -> eliminar.
    assert arrays["PReal"]["slot_map"]["1"]["action"] == "eliminar"
    assert arrays["PReal"]["slot_map"]["1"]["current"] == "Un real"
    assert arrays["PReal"]["slot_map"]["1"]["desired"] is None


def test_el_punto_sigue_saliendo_como_eliminar_como_main() -> None:
    """Un slot de TIA cuyo comentario ya es ``"."`` sigue saliendo como
    ``eliminar`` (no como ``sin_cambios``): solo el comentario vacio
    (``""``) se preserva (``main``)."""
    dcl = (
        "DATA_BLOCK DB53100_CPR_PARAM\n"
        '        { S7_MLC := "MLC_p1" }\n'
        "        PReal[1] := ();\n"
        "END_DATA_BLOCK\n"
    )
    res = "MultiLingualTexts:\n  - id: MLC_p1\n    es-ES: .\n"
    mapa = MapaProceso(
        preal={0: "NO USAR"},
        db_param_name="DB53100_CPR_PARAM",
        db_alm_name="DB55100_CPR_ALM",
        table_name="100_CPR",
    )
    arrays = proc_calcular_arrays(mapa, dcl, res, "", "")

    assert arrays["PReal"]["slot_map"]["1"]["action"] == "eliminar"


def test_un_slot_vacio_en_tia_sale_sin_cambios() -> None:
    """Un slot de TIA con comentario ``""`` (vacio) no se toca:
    ``sin_cambios``."""
    dcl = (
        "DATA_BLOCK DB53100_CPR_PARAM\n"
        '        { S7_MLC := "MLC_p1" }\n'
        "        PReal[1] := ();\n"
        "END_DATA_BLOCK\n"
    )
    res = "MultiLingualTexts:\n  - id: MLC_p1\n    es-ES: ''\n"
    mapa = MapaProceso(
        preal={0: "NO USAR"},
        db_param_name="DB53100_CPR_PARAM",
        db_alm_name="DB55100_CPR_ALM",
        table_name="100_CPR",
    )
    arrays = proc_calcular_arrays(mapa, dcl, res, "", "")

    assert arrays["PReal"]["slot_map"]["1"]["action"] == "sin_cambios"


def test_db_no_exportado_salido_degradado() -> None:
    """Sin el par ``.s7dcl``/``.s7res`` del DB (vacio), el estado actual es
    ``None`` y la accion se infiere del deseado: ``"."`` -> ``agregar``, otro
    -> ``renombrar``."""
    arrays = proc_calcular_arrays(_mapa(), "", "", "", "")

    assert arrays["PReal"]["current_count"] == 0
    # PReal[1] desired="Un real" -> renombrar; un slot deseado "." -> agregar.
    assert arrays["PReal"]["slot_map"]["1"] == {
        "current": None,
        "desired": "Un real",
        "action": "renombrar",
    }
    assert arrays["ALM"]["current_count"] == 0
    assert arrays["ALM"]["slot_map"]["1"] == {
        "current": None,
        "desired": "Una alarma",
        "action": "renombrar",
    }


def test_el_resumen_cuenta_por_accion() -> None:
    """El resumen suma los slots y cuenta por tipo de accion."""
    arrays = proc_calcular_arrays(_mapa(), _dcl_param(), _res_param(), _dcl_alm(), _res_alm())

    resumen = proc_resumen(arrays)
    assert resumen["total"] == sum(
        len(arr["slot_map"]) for arr in arrays.values()
    )
    total_por_accion = {
        "agregados": 0,
        "renombrados": 0,
        "eliminados": 0,
        "sin_cambios": 0,
    }
    for arr in arrays.values():
        for entry in arr["slot_map"].values():
            key = {
                "agregar": "agregados",
                "renombrar": "renombrados",
                "eliminar": "eliminados",
                "sin_cambios": "sin_cambios",
            }.get(entry["action"])
            if key:
                total_por_accion[key] += 1
    assert resumen["agregados"] == total_por_accion["agregados"]
    assert resumen["renombrados"] == total_por_accion["renombrados"]
    assert resumen["eliminados"] == total_por_accion["eliminados"]
    assert resumen["sin_cambios"] == total_por_accion["sin_cambios"]
    assert resumen["total"] == sum(total_por_accion.values())


# ── el diff del N_MAX ────────────────────────────────────────────────────────


def test_el_diff_n_max_compara_por_nombre_tia(tmp_path: Path) -> None:
    """El N_MAX se compara por nombre canonico TIA: el ``actual`` sale del
    XML filtrado por los nombres del proceso y el ``deseado``, de la columna
    del proceso del Excel."""
    ruta = tmp_path / "100_CPR.xml"
    ruta.write_text(XML_N_MAX, encoding="utf-8")

    diff = proc_calcular_diff_n_max(
        "100_CPR",
        {
            "preal": "100_N_MAX_PREAL",
            "pint": "100_N_MAX_PINT",
            "alm": "100_N_MAX_ALM",
            "alm_hmi": "100_N_MAX_ALM_HMI",
        },
        {"preal": 3, "pint": 2, "alm": 20, "alm_hmi": 2},
        ruta,
    )

    assert isinstance(diff, DiffNMax)
    assert diff.xml_ausente is False
    # OTra_CONSTANTE no entra en el filtro por nombre TIA.
    assert diff.actual == {
        "100_N_MAX_PREAL": 3,
        "100_N_MAX_PINT": 2,
        "100_N_MAX_ALM": 16,
        "100_N_MAX_ALM_HMI": 2,
    }
    assert diff.deseado["100_N_MAX_ALM"] == 20
    # alm: 16 (TIA) != 20 (Excel) -> actualizar.
    estados = {fila["kind"]: fila["status"] for fila in diff.todos}
    assert estados == {
        "preal": "sin_cambios",
        "pint": "sin_cambios",
        "alm": "actualizar",
        "alm_hmi": "sin_cambios",
    }
    assert diff.resumen == {"actualizar": 1, "sin_cambios": 3, "total": 4}
    fila_alm = next(f for f in diff.todos if f["kind"] == "alm")
    assert fila_alm == {
        "kind": "alm",
        "name": "100_N_MAX_ALM",
        "actual": 16,
        "nuevo": 20,
        "status": "actualizar",
    }


def test_el_diff_n_max_con_el_xml_ausente(tmp_path: Path) -> None:
    """Sin el XML en la exportacion, el N_MAX sale en modo degradado:
    ``actual`` vacio, ``todos`` vacio, resumen todo ``sin_cambios``."""
    ruta = tmp_path / "no_existe.xml"

    diff = proc_calcular_diff_n_max(
        "100_CPR",
        {"preal": "100_N_MAX_PREAL", "pint": "100_N_MAX_PINT"},
        {"preal": 3, "pint": 2},
        ruta,
    )

    assert diff.xml_ausente is True
    assert diff.actual == {}
    assert diff.deseado == {"100_N_MAX_PREAL": 3, "100_N_MAX_PINT": 2}
    assert diff.todos == []
    assert diff.resumen == {"actualizar": 0, "sin_cambios": 2, "total": 2}


def test_el_diff_n_max_sin_sufijos_sale_vacio(tmp_path: Path) -> None:
    """Sin sufijos de N_MAX en el config, no hay nada que comparar."""
    ruta = tmp_path / "100_CPR.xml"
    ruta.write_text(XML_N_MAX, encoding="utf-8")

    diff = proc_calcular_diff_n_max("100_CPR", {}, {}, ruta)

    assert diff.actual == {}
    assert diff.deseado == {}
    assert diff.todos == []
    assert diff.resumen == {"actualizar": 0, "sin_cambios": 0, "total": 0}


# ── los satelites ─────────────────────────────────────────────────────────────


def test_los_satelites_por_array_son_los_de_main() -> None:
    """Los satelites de cada array principal son los de ``main``."""
    assert SATELITES_POR_ARRAY["PReal"] == ("PReal_Vis", "Aux.PReal_ValorAnterior")
    assert SATELITES_POR_ARRAY["PInt"] == ("PInt_Vis", "Aux.PInt_ValorAnterior")
    assert SATELITES_POR_ARRAY["ALM"] == ()
