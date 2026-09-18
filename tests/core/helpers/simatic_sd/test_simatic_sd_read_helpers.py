"""Tests de ``find_array_slots`` y ``read_current_comments``
(sept-2026 refactor DRY, Commit 21a).

Helpers de SOLO-LECTURA para el preview (``proc_generar_preview``).
Cubren la API minima que el preview necesita: saber que slots
existen en el .s7dcl + leer el texto ``es-ES`` actual de cada slot.
"""
from __future__ import annotations

import pytest

from core.helpers.simatic_sd import (
    find_array_slots,
    read_current_comments,
)


# ── find_array_slots ───────────────────────────────────────────────

_BASE_DCL = """DATA_BLOCK "DB_TEST"
    VAR RETAIN
        { S7_MLC := "MLC_prHeader" }
        PReal : Array[1..3] of _.UDT_ZC_PREAL;
    END_VAR
    VAR
        PReal_Vis : Array[1..3] of Bool;
    END_VAR
END_DATA_BLOCK
"""


def test_find_array_slots_udt_encuentra_slots_raiz() -> None:
    """Para UDT, encuentra los slots con ``:= ();`` (raiz vacia)."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        '        { S7_MLC := "MLC_pr_001"; }\n        PReal[1] := ();\n'
        '        { S7_MLC := "MLC_pr_002"; }\n        PReal[2] := ();\n'
        '        PReal[3] := ();\nEND_DATA_BLOCK',
    )
    assert find_array_slots(dcl, "PReal", "UDT") == {1, 2, 3}


def test_find_array_slots_udt_ignora_sub_campos() -> None:
    """Los sub-campos ``.Valor``, ``.Maximo`` no cuentan como PReal[X]."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        "        PReal[1].Valor := 50.0;\n"
        "        PReal[1].Maximo := 100.0;\n"
        "        PReal[1].Minimo := 10.0;\n"
        "        PReal[2].Valor := 60.0;\n"
        "END_DATA_BLOCK",
    )
    # Sin ``:= ();`` no hay slots UDT.
    assert find_array_slots(dcl, "PReal", "UDT") == set()


def test_find_array_slots_simple_encuentra_cualquier_valor() -> None:
    """Para Simple, ``:= FALSE;``, ``:= 30;``, ``:= 50.0;`` cuentan."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        "        PReal_Vis[1] := FALSE;\n"
        "        PReal_Vis[2] := true;\n"
        "        PReal_Vis[3] := ();\n"
        "END_DATA_BLOCK",
    )
    assert find_array_slots(dcl, "PReal_Vis", "Simple") == {1, 2, 3}


def test_find_array_slots_no_matchea_otros_arrays() -> None:
    """Solo cuenta slots del array pedido."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        '        { S7_MLC := "MLC_a"; }\n        PReal[1] := ();\n'
        "        PReal_Vis[1] := FALSE;\nEND_DATA_BLOCK",
    )
    assert find_array_slots(dcl, "PReal", "UDT") == {1}
    assert find_array_slots(dcl, "PReal_Vis", "Simple") == {1}


def test_find_array_slots_sin_asignaciones_devuelve_set_vacio() -> None:
    """Sin asignaciones del array pedido, devuelve set vacio."""
    assert find_array_slots(_BASE_DCL, "PReal", "UDT") == set()
    assert find_array_slots("", "PReal", "UDT") == set()


def test_find_array_slots_con_array_complejo_aux() -> None:
    """Aux.PReal_ValorAnterior[X] (con punto en el nombre) matchea."""
    dcl = (
        'DATA_BLOCK DB\n'
        '    VAR\n'
        '        Aux : STRUCT\n'
        '            PReal_ValorAnterior : Array[1..3] of Real;\n'
        '        END_STRUCT;\n'
        '    END_VAR\n'
        '        Aux.PReal_ValorAnterior[1] := 50.0;\n'
        '        Aux.PReal_ValorAnterior[2] := 60.0;\n'
        'END_DATA_BLOCK\n'
    )
    assert find_array_slots(dcl, "Aux.PReal_ValorAnterior", "Simple") == {1, 2}


# ── read_current_comments ──────────────────────────────────────────

_BASE_RES = """MultiLingualTexts:
  - id: MLC_pr_001
    es-ES: parametro 1
  - id: MLC_pr_002
    es-ES: parametro 2
  - id: MLC_pv_001
    es-ES: visualizacion 1
"""


def test_read_current_comments_udt_con_mlcs() -> None:
    """Slots UDT con MLC adyacente: devuelve el texto del .s7res."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        '        { S7_MLC := "MLC_pr_001"; }\n        PReal[1] := ();\n'
        '        { S7_MLC := "MLC_pr_002"; }\n        PReal[2] := ();\n'
        '        PReal[3] := ();\nEND_DATA_BLOCK',
    )
    result = read_current_comments(_BASE_RES, "PReal", [1, 2, 3], dcl)
    assert result == {1: "parametro 1", 2: "parametro 2", 3: None}


def test_read_current_comments_sin_mlc_devuelve_none() -> None:
    """Slot sin MLC adyacente: devuelve None."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK", "        PReal[1] := ();\nEND_DATA_BLOCK",
    )
    result = read_current_comments(_BASE_RES, "PReal", [1], dcl)
    assert result == {1: None}


def test_read_current_comments_sin_dcl_text() -> None:
    """Sin dcl_text: devuelve None para todos los slots (no busca MLC)."""
    result = read_current_comments(_BASE_RES, "PReal", [1, 2, 3])
    assert result == {1: None, 2: None, 3: None}


def test_read_current_comments_slot_no_en_res() -> None:
    """MLC existe en .s7dcl pero NO en .s7res: devuelve None."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        '        { S7_MLC := "MLC_inexistente"; }\n        PReal[1] := ();\nEND_DATA_BLOCK',
    )
    result = read_current_comments(_BASE_RES, "PReal", [1], dcl)
    assert result == {1: None}


def test_read_current_comments_slot_vacio_en_lista() -> None:
    """Lista de slots vacia: devuelve dict vacio."""
    result = read_current_comments(_BASE_RES, "PReal", [], _BASE_DCL)
    assert result == {}


def test_read_current_comments_simple() -> None:
    """Para Simple, lee los textos de los slots con MLC."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        '        { S7_MLC := "MLC_pv_001"; }\n        PReal_Vis[1] := FALSE;\n'
        "        PReal_Vis[2] := false;\nEND_DATA_BLOCK",
    )
    result = read_current_comments(
        _BASE_RES, "PReal_Vis", [1, 2, 3], dcl, array_type="Simple",
    )
    assert result == {1: "visualizacion 1", 2: None, 3: None}
