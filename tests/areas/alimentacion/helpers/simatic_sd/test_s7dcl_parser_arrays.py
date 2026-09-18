"""Tests del parser ``simatic_sd_s7dcl_parser`` con arrays de UDT.

Sept-2026: tras refactor DRY, descubri que el parser comparaba el
grupo ``array`` del regex (sin comillas) con el ``array_name`` del
caller (con o sin comillas). Fallaba para disp con comillas. Ahora el
parser normaliza internamente.

Estos tests blindan el fix.
"""
from __future__ import annotations

from areas.alimentacion.helpers.simatic_sd.simatic_sd_s7dcl_parser import (
    find_array_slots,
    find_assignment,
    find_assignment_mlc,
)


# ── Sintaxis disp (con comillas, slot 0 valido) ─────────────────────────

_DISP_S7DCL = """DATA_BLOCK "DB2000_DispED"
    VAR RETAIN
        "DispED" : Array[0..3] of _.UDT_ZC_DISP;
    END_VAR

        { S7_MLC := "MLC_disp0" }
        "DispED"[0] := ();
        "DispED"[1].Nombre := 'Bomba';
        { S7_MLC := "MLC_disp1" }
        "DispED"[1] := ();
        "DispED"[2].Activo := FALSE;
        { S7_MLC := "MLC_disp2" }
        "DispED"[2] := ();
        "DispED"[3] := ();
END_DATA_BLOCK
"""


def test_find_assignment_disp_con_comillas() -> None:
    m = find_assignment(_DISP_S7DCL, '"DispED"', 1)
    assert m is not None
    assert m.group().strip() == '"DispED"[1] := ();'


def test_find_assignment_disp_sin_comillas_tambien_matchea() -> None:
    """El parser es bidi: si el .s7dcl tiene comillas, el caller puede
    pasar el array_name SIN comillas y matchea igual."""
    m = find_assignment(_DISP_S7DCL, 'DispED', 1)
    assert m is not None


def test_find_assignment_mlc_disp_con_comillas() -> None:
    assert find_assignment_mlc(_DISP_S7DCL, '"DispED"', 1) == "MLC_disp1"
    assert find_assignment_mlc(_DISP_S7DCL, '"DispED"', 0) == "MLC_disp0"
    assert find_assignment_mlc(_DISP_S7DCL, '"DispED"', 2) == "MLC_disp2"


def test_find_assignment_mlc_disp_sin_mlc_devuelve_none() -> None:
    """Slot 3 sin MLC adyacente: retorna None (FIX sept-2026 lo inyectara)."""
    assert find_assignment_mlc(_DISP_S7DCL, '"DispED"', 3) is None


def test_find_array_slots_disp_incluye_slot_0() -> None:
    """Disp incluye slot 0 por convencion; proc no."""
    slots = find_array_slots(_DISP_S7DCL, '"DispED"')
    assert slots == {0, 1, 2, 3}


# ── Sintaxis proc (sin comillas, sin slot 0) ───────────────────────────

_PROC_S7DCL = """DATA_BLOCK DB53010_PRO_STD_PARAM
    VAR RETAIN
        { S7_MLC := "MLC_prHeader" }
        PReal : Array[1..3] of _.UDT_ZC_PREAL;
    END_VAR

        PReal[1].Valor := 50.0;
        { S7_MLC := "MLC_pr_001" }
        PReal[1] := ();
        PReal[2].Valor := 60.0;
        { S7_MLC := "MLC_pr_002" }
        PReal[2] := ();
        PReal[3] := ();
END_DATA_BLOCK
"""


def test_find_assignment_proc_sin_comillas() -> None:
    m = find_assignment(_PROC_S7DCL, "PReal", 1)
    assert m is not None
    assert m.group().strip() == "PReal[1] := ();"


def test_find_assignment_proc_con_comillas_matchea_por_normalizacion() -> None:
    """El parser normaliza comillas en ambos lados (sept-2026 fix).
    Si el .s7dcl NO tiene comillas pero el caller pasa ``'"PReal"'``,
    el parser quita las comillas y matchea igual. Es bidirectional.

    Esto evita que el caller tenga que saber si el .s7dcl original
    llevaba comillas (depende del export de TIA V18 vs V21).
    """
    m = find_assignment(_PROC_S7DCL, '"PReal"', 1)
    assert m is not None


def test_find_assignment_mlc_proc() -> None:
    assert find_assignment_mlc(_PROC_S7DCL, "PReal", 1) == "MLC_pr_001"
    assert find_assignment_mlc(_PROC_S7DCL, "PReal", 2) == "MLC_pr_002"
    assert find_assignment_mlc(_PROC_S7DCL, "PReal", 3) is None


def test_find_array_slots_proc_excluye_slot_0() -> None:
    slots = find_array_slots(_PROC_S7DCL, "PReal")
    assert slots == {1, 2, 3}
    assert 0 not in slots


# ── Cuidado: campos de UDT NO capturan como asignaciones del array ────

def test_no_matchea_campos_udt_como_asignacion_principal() -> None:
    """``PReal[1].Valor := 50.0;`` NO matchea ``PReal[1] := ();``. Solo la
    asignacion PRINCIPAL del slot (final) entra en find_assignment."""
    s7dcl_with_udt = (
        'DATA_BLOCK DB\n'
        '    VAR RETAIN\n'
        '        { S7_MLC := "MLC_x" }\n'
        '        PReal : Array[1..1] of _.UDT_ZC_PREAL;\n'
        '    END_VAR\n\n'
        '        PReal[1].Valor := 50.0;\n'
        '        PReal[1].Maximo := 100.0;\n'
        '        PReal[1].Minimo := 10.0;\n'
        '        { S7_MLC := "MLC_pr_001" }\n'
        '        PReal[1] := ();\n'
        'END_DATA_BLOCK\n'
    )
    m = find_assignment(s7dcl_with_udt, "PReal", 1)
    assert m is not None
    # El match cubre SOLO la linea ``PReal[1] := ();``, no los campos.
    assert "Valor" not in m.group()
    assert "Maximo" not in m.group()
    assert m.group().strip().endswith("PReal[1] := ();")
    assert find_assignment_mlc(s7dcl_with_udt, "PReal", 1) == "MLC_pr_001"


def test_no_matchea_campos_udt_disp() -> None:
    """Idem pero para disp, con comillas."""
    s7dcl_with_udt = (
        'DATA_BLOCK "DB"\n'
        '    VAR RETAIN\n'
        '        "DispED" : Array[0..1] of _.UDT_ZC_DISP;\n'
        '    END_VAR\n\n'
        '        { S7_MLC := "MLC_zero" }\n'
        '        "DispED"[0] := ();\n'
        '        "DispED"[1].Nombre := \'X\';\n'
        '        { S7_MLC := "MLC_one" }\n'
        '        "DispED"[1] := ();\n'
        'END_DATA_BLOCK\n'
    )
    m = find_assignment(s7dcl_with_udt, '"DispED"', 1)
    assert m is not None
    assert "Nombre" not in m.group()
    assert find_assignment_mlc(s7dcl_with_udt, '"DispED"', 1) == "MLC_one"


# ── Formato inline / Seccion A (sept-2026 fix) ─────────────────────
#
# TIA V21 exporta los DBs con DOS secciones mezcladas:
#   - Seccion B (standalone): MLC ANTES de la asignacion `:= ();`.
#   - Seccion A (inline):     MLC DESPUES de la asignacion `:= VALOR;`.
# El algoritmo anterior buscaba el ULTIMO MLC en un rango grande,
# lo que daba falsos positivos (slots en Seccion A recibian MLCs
# compartidos de UDT u otros arrays). Esto es el bug del smoke en
# vivo proceso 50010 (sept-2026).
#
# Tests blindan el fix: el algoritmo debe detectar el formato y
# buscar en la direccion correcta, dentro de un rango pequeno.

_INLINE_S7DCL = """DATA_BLOCK DB
    VAR
        PReal_Vis : Array[1..3] of Bool;
    END_VAR

        PReal_Vis[1] := FALSE;
        {
            S7_MLC := "MLC_pv1";
        }
        PReal_Vis[2] := false;
        {
            S7_MLC := "MLC_pv2";
        }
        PReal_Vis[3] := true;
END_DATA_BLOCK
"""


def test_inline_mlc_despues_de_asignacion() -> None:
    """Formato A: ``PReal_Vis[1] := FALSE;`` + MLC justo despues.

    El MLC esta DESPUES (no antes) de la asignacion. El algoritmo
    debe encontrarlo.
    """
    assert find_assignment_mlc(_INLINE_S7DCL, "PReal_Vis", 1) == "MLC_pv1"
    assert find_assignment_mlc(_INLINE_S7DCL, "PReal_Vis", 2) == "MLC_pv2"
    # PReal_Vis[3] := true; NO tiene MLC adyacente despues.
    assert find_assignment_mlc(_INLINE_S7DCL, "PReal_Vis", 3) is None


def test_inline_slot_sin_mlc_devuelve_none_no_compartido() -> None:
    """Sin MLC propio, devuelve None (no un MLC compartido de otro slot).

    Caso critico sept-2026: el archivo REAL del operario (proceso
    50010) tiene ``PReal_Vis[1] := FALSE;`` y ``Aux.PReal_ValorAnterior[1]
    := 50.0;`` como slots SIN MLC propio. El bug era que devolvia un
    MLC compartido (p.ej. MLC_4dY del UDT PInt), contaminando ambos.
    El fix devuelve None.
    """
    # PReal_Vis[1] := FALSE; sin MLC adyacente propio (solo hay
    # una declaracion de array, ningun MLC antes ni despues inmediato).
    s7dcl = (
        'DATA_BLOCK DB\n'
        '    VAR\n'
        '        PReal_Vis : Array[1..2] of Bool;\n'
        '    END_VAR\n'
        '        PReal_Vis[1] := FALSE;\n'
        'END_DATA_BLOCK\n'
    )
    assert find_assignment_mlc(s7dcl, "PReal_Vis", 1) is None


def test_inline_no_asigna_mlc_de_otro_array() -> None:
    """El MLC encontrado DESPUES debe ser del MISMO array, no de otro.

    Caso patologico del archivo sintetico: si el siguiente MLC esta
    a >200 chars o pertenece a una asignacion de OTRO array, devolver
    None.
    """
    s7dcl = (
        'DATA_BLOCK DB\n'
        '    VAR\n'
        '        PReal_Vis : Array[1..1] of Bool;\n'
        '        PInt : Array[1..1] of Int;\n'
        '    END_VAR\n'
        '        PReal_Vis[1] := FALSE;\n'
        # Salto: otra asignacion de PInt antes del MLC.
        '        PInt[1] := 30;\n'
        '        { S7_MLC := "MLC_pi_001"; }\n'
        '        PInt[1] := ();\n'
        'END_DATA_BLOCK\n'
    )
    # El MLC_pi_001 es de PInt[1], no de PReal_Vis[1]. Devolver None.
    assert find_assignment_mlc(s7dcl, "PReal_Vis", 1) is None
    # PInt[1] := 30; (formato A) tiene MLC justo despues.
    assert find_assignment_mlc(s7dcl, "PInt", 1) == "MLC_pi_001"


def test_off_by_one_en_seccion_a() -> None:
    """El MLC entre dos slots consecutivos pertenece al ANTERIOR.

    Caso del operario (proceso 50010): ``PInt_Vis[1] := false;`` +
    ``{ MLC_GXnT }`` + ``PInt_Vis[2] := false;``. El MLC pertenece
    al slot 1, NO al slot 2. El bug era que el algoritmo lo asignaba
    al slot 2 (off-by-one).
    """
    s7dcl = (
        'DATA_BLOCK DB\n'
        '    VAR\n'
        '        PInt_Vis : Array[1..3] of Bool;\n'
        '    END_VAR\n'
        '        PInt_Vis[1] := false;\n'
        '        { S7_MLC := "MLC_1"; }\n'
        '        PInt_Vis[2] := false;\n'
        '        { S7_MLC := "MLC_2"; }\n'
        '        PInt_Vis[3] := true;\n'
        'END_DATA_BLOCK\n'
    )
    assert find_assignment_mlc(s7dcl, "PInt_Vis", 1) == "MLC_1"
    assert find_assignment_mlc(s7dcl, "PInt_Vis", 2) == "MLC_2"
    assert find_assignment_mlc(s7dcl, "PInt_Vis", 3) is None


def test_seccion_b_standalone_sigue_funcionando() -> None:
    """Formato B (MLC ANTES de `:= ();`): comportamiento intacto."""
    s7dcl = (
        'DATA_BLOCK DB\n'
        '    VAR\n'
        '        PReal : Array[1..3] of Real;\n'
        '    END_VAR\n'
        '        { S7_MLC := "MLC_pr_001"; }\n'
        '        PReal[1] := ();\n'
        '        { S7_MLC := "MLC_pr_002"; }\n'
        '        PReal[2] := ();\n'
        '        PReal[3] := ();\n'
        'END_DATA_BLOCK\n'
    )
    assert find_assignment_mlc(s7dcl, "PReal", 1) == "MLC_pr_001"
    assert find_assignment_mlc(s7dcl, "PReal", 2) == "MLC_pr_002"
    assert find_assignment_mlc(s7dcl, "PReal", 3) is None
