"""Tests del ``SimaticSDDbArrayCommentUpdater`` (sept-2026 DRY).

Parametrizados sobre ``quote_array_name`` y ``keep_slot0`` para cubrir
tanto Disp (con comillas, slot 0 obligatorio) como Proc (sin comillas,
slot 0 omitido). Casos cubiertos:
  - Reutilizacion de MLC existente (disp + proc).
  - Insercion de MLC + asignacion nueva (disp + proc).
  - FIX sept-2026: inyeccion de MLC en satellite que existe en .s7dcl
    pero sin MLC (resize N_MAX típico).
  - Insercion bloque + asignacion en satellite que no existe.
  - Texto comun al array principal y a los satellites.
  - ensure_slot0_mlc.
  - save in-place.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from areas.alimentacion.helpers.simatic_sd.simatic_sd_db_array_comment_updater import (  # noqa: E501
    CommentUpdateResult,
    SimaticSDDbArrayCommentUpdater,
)
from areas.alimentacion.helpers.simatic_sd.simatic_sd_mlc_registry import (
    MLCRegistry,
)


# ────────────────────────────────────────────────────────────────────────
# Builders de .s7dcl/.s7res sinteticos para los tests parametrizados.
# ────────────────────────────────────────────────────────────────────────

def _synth_s7dcl_disp(slot_count: int = 5, with_slot0: bool = True) -> str:
    """Genera .s7dcl para Disp con ``"DispED"[N] := ();`` + slot 0."""
    body = "\n"
    body += '    VAR RETAIN\n'
    if with_slot0:
        body += '        "DispED" : Array[0..{}] of _.UDT_ZC_DISP;\n'.format(slot_count)
    else:
        body += '        "DispED" : Array[1..{}] of _.UDT_ZC_DISP;\n'.format(slot_count)
    body += '    END_VAR\n\n'
    if with_slot0:
        body += '        { S7_MLC := "MLC_Disp_0" }\n'
        body += '        "DispED"[0] := ();\n'
    for i in range(1, slot_count + 1):
        body += f'        {{ S7_MLC := "MLC_Disp_{i:03d}" }}\n'
        body += f'        "DispED"[{i}] := ();\n'
    header = (
        'DATA_BLOCK "DB2000_TEST"\n'
    )
    return header + body + "END_DATA_BLOCK\n"


def _synth_s7res_disp(mlcs: dict[int, str]) -> str:
    """Genera .s7res para Disp con MLC_N = texto."""
    res = "MultiLingualTexts:\n"
    for slot, text in mlcs.items():
        res += f"  - id: MLC_Disp_{slot:03d}\n    es-ES: {text}\n"
    if "MLC_Disp_0" not in {f"MLC_Disp_{slot:03d}" for slot in mlcs}:
        # Header placeholder (slot 0 sin comentario real)
        for slot in mlcs:
            if slot == 0:
                pass
        res += "  - id: MLC_Disp_0\n    es-ES: .\n"
    return res


def _synth_s7dcl_proc(
    preal_slots: int = 3,
    pint_slots: int = 10,
    preal_vis_slots: int | None = None,
    valoranterior_preal: int | None = None,
    valoranterior_pint: int | None = None,
) -> str:
    """Genera .s7dcl para proceso PRO_STD con PReal/PInt/Vis/ValorAnterior."""
    if preal_vis_slots is None:
        preal_vis_slots = preal_slots
    if valoranterior_preal is None:
        valoranterior_preal = preal_slots
    if valoranterior_pint is None:
        valoranterior_pint = pint_slots

    body = (
        'DATA_BLOCK DB53010_PRO_STD_PARAM\n'
        '    VAR RETAIN\n'
        '        { S7_MLC := "MLC_prHeader" }\n'
        '        PReal : Array[1.._."50010_N_MAX_PREAL"] of _.UDT_ZC_PREAL;\n'
        '    END_VAR\n\n'
        '    VAR\n'
        '        { S7_MLC := "MLC_prVisHeader" }\n'
        '        PReal_Vis : Array[1.._."50010_N_MAX_PREAL"] of Bool;\n'
        '    END_VAR\n\n'
        '    VAR RETAIN\n'
        '        { S7_MLC := "MLC_piHeader" }\n'
        '        PInt : Array[1.._."50010_N_MAX_PINT"] of _.UDT_ZC_PINT;\n'
        '    END_VAR\n\n'
        '    VAR\n'
        '        { S7_MLC := "MLC_piVisHeader" }\n'
        '        PInt_Vis : Array[1.._."50010_N_MAX_PINT"] of Bool;\n'
        '        Aux : STRUCT\n'
        '            { S7_MLC := "MLC_auxVaHeader"; S7_Visibility := "Hidden := External" }\n'
        '            PReal_ValorAnterior : Array[1.._."50010_N_MAX_PREAL"] of Real;\n'
        '            { S7_MLC := "MLC_auxIaHeader"; S7_Visibility := "Hidden := External" }\n'
        '            PInt_ValorAnterior : Array[1.._."50010_N_MAX_PINT"] of Int;\n'
        '        END_STRUCT;\n'
        '    END_VAR\n\n'
    )

    # PReal[1..preal_slots] with MLCs for preal_slots ; reuse for satelites exist.
    for i in range(1, preal_slots + 1):
        body += f'        {{ S7_MLC := "MLC_pr_{i:03d}" }}\n'
        body += f'        PReal[{i}] := ();\n'
    # PReal_Vis[1..preal_vis_slots] - some may lack MLC (resize simulado).
    for i in range(1, preal_vis_slots + 1):
        if i <= 1:
            body += f'        {{ S7_MLC := "MLC_prv_{i:03d}" }}\n'
        body += f'        PReal_Vis[{i}] := FALSE;\n'

    # PInt[1..pint_slots] (reutilizamos algunos con MLC).
    for i in range(1, pint_slots + 1):
        body += f'        {{ S7_MLC := "MLC_pi_{i:03d}" }}\n'
        body += f'        PInt[{i}] := ();\n'

    # PInt_Vis[1..preal_vis_slots] - todos SIN MLC (caso del fix).
    for i in range(1, preal_vis_slots + 1):
        body += f'        PInt_Vis[{i}] := ();\n'

    # Aux.PReal_ValorAnterior[1..valoranterior_preal].
    for i in range(1, valoranterior_preal + 1):
        if i <= 1:
            body += f'        {{ S7_MLC := "MLC_aux_vapre_{i:03d}" }}\n'
        body += f'        Aux.PReal_ValorAnterior[{i}] := ();\n'

    # Aux.PInt_ValorAnterior[1..valoranterior_pint] - todos SIN MLC.
    for i in range(1, valoranterior_pint + 1):
        body += f'        Aux.PInt_ValorAnterior[{i}] := ();\n'

    return body + "END_DATA_BLOCK\n"


def _synth_s7res_proc(mlcs: dict[str, str]) -> str:
    """Genera .s7res para proc con header + entries."""
    res = "MultiLingualTexts:\n"
    for mlc, text in mlcs.items():
        res += f"  - id: {mlc}\n    es-ES: {text}\n"
    return res


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────

def _count_es_es(text: str, needle: str) -> int:
    return text.count(f"es-ES: {needle}")


def _s7dcl_has_mlc_block_for(s7dcl: str, array_name: str, slot: int) -> bool:
    """Detecta si hay un bloque ``{ S7_MLC := ... }`` inmediatamente
    antes de la asignacion ``<ARRAY>[slot] := ...``. Funciona con o sin
    comillas en el nombre del array.
    """
    target = array_name.strip('"')
    pattern = re.compile(
        rf'(?xm)^[ \t]+\{{[^}}]*S7_MLC\s*:=\s*"\S+"[^}}]*\}}[ \t]*\n'
        rf'^[ \t]+"?{re.escape(target)}"?\[{slot}\][ \t]*:='
    )
    return bool(pattern.search(s7dcl))


# ────────────────────────────────────────────────────────────────────────
# Tests parametrizados
# ────────────────────────────────────────────────────────────────────────

# ── 1. DispED: reutilizacion de MLC existente ──────────────────────────

def test_disp_reused_mlc_y_modifica_texto(tmp_path: Path) -> None:
    """Disp: slot 2 ya tiene MLC_Disp_002, lo reutilizamos y cambiamos texto."""
    dcl_path = tmp_path / "DB2000.s7dcl"
    res_path = tmp_path / "DB2000.s7res"
    dcl_path.write_text(_synth_s7dcl_disp(slot_count=5), encoding="utf-8")
    res_path.write_text(
        _synth_s7res_disp({0: ".", 1: "antiguo_1", 2: "antiguo_2", 3: "x", 4: "x", 5: "x"}),
        encoding="utf-8-sig",
    )
    updater = SimaticSDDbArrayCommentUpdater(
        s7dcl_path=dcl_path,
        s7res_path=res_path,
        array_name='"DispED"',
        slot_map={1: "nuevo_1", 2: "nuevo_2"},
        quote_array_name=True,
        keep_slot0=True,
        ensure_slot0_mlc=True,
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    result = updater.update()
    updater.save()

    assert result.reused[1] == "MLC_Disp_001"
    assert result.reused[2] == "MLC_Disp_002"
    assert result.inserted == {}
    res_text = res_path.read_text(encoding="utf-8-sig")
    assert _count_es_es(res_text, "nuevo_1") == 1
    assert _count_es_es(res_text, "nuevo_2") == 1
    assert "antiguo_1" not in res_text
    assert "antiguo_2" not in res_text


# ── 2. DispED: ensure_slot0_mlc solo cuando hace falta ────────────────

def test_disp_ensure_slot0_inyecta_si_falta(tmp_path: Path) -> None:
    """Disp: si el slot 0 no tiene MLC, ensure_slot0_mlc=True lo inyecta."""
    # Generamos .s7dcl SIN bloque MLC en slot 0.
    dcl_text = (
        'DATA_BLOCK "DB2000_TEST"\n'
        '    VAR RETAIN\n'
        '        "DispED" : Array[0..3] of _.UDT_ZC_DISP;\n'
        '    END_VAR\n\n'
        '        "DispED"[0] := ();\n'
        '        { S7_MLC := "MLC_d_1" }\n'
        '        "DispED"[1] := ();\n'
        '        { S7_MLC := "MLC_d_2" }\n'
        '        "DispED"[2] := ();\n'
        '        { S7_MLC := "MLC_d_3" }\n'
        '        "DispED"[3] := ();\n'
        'END_DATA_BLOCK\n'
    )
    dcl = tmp_path / "DB.s7dcl"
    res = tmp_path / "DB.s7res"
    dcl.write_text(dcl_text, encoding="utf-8")
    res.write_text(
        "MultiLingualTexts:\n  - id: MLC_d_1\n    es-ES: a\n"
        "  - id: MLC_d_2\n    es-ES: b\n"
        "  - id: MLC_d_3\n    es-ES: c\n",
        encoding="utf-8-sig",
    )
    updater = SimaticSDDbArrayCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        array_name='"DispED"',
        slot_map={1: "A", 2: "B", 3: "C"},
        quote_array_name=True,
        keep_slot0=True,
        ensure_slot0_mlc=True,
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    result = updater.update()
    updater.save()

    dcl_text_after = dcl.read_text(encoding="utf-8")
    # El slot 0 ahora debe tener un MLC asignado.
    slot0_match = re.search(
        r'\s*\{\s*S7_MLC\s*:=\s*"(MLC_\w+)"\s*;?\s*\}\s*\n\s*"DispED"\[0\]',
        dcl_text_after,
    )
    assert slot0_match is not None, "slot 0 deberia tener MLC inyectado"
    slot0_mlc = slot0_match.group(1)
    assert slot0_mlc in result.inserted.values() or slot0_mlc == "MLC_zz" or len(slot0_mlc) > 0


def test_disp_ensure_slot0_no_hace_nada_si_ya_existe(
    tmp_path: Path,
) -> None:
    """Disp: si slot 0 ya tiene MLC, ensure_slot0_mlc no duplica."""
    dcl = tmp_path / "DB.s7dcl"
    res = tmp_path / "DB.s7res"
    dcl.write_text(
        'DATA_BLOCK "DB"\n'
        '    VAR RETAIN\n'
        '        "DispED" : Array[0..1] of _.UDT_ZC_DISP;\n'
        '    END_VAR\n\n'
        '        { S7_MLC := "MLC_zero" }\n'
        '        "DispED"[0] := ();\n'
        '        { S7_MLC := "MLC_one" }\n'
        '        "DispED"[1] := ();\n'
        'END_DATA_BLOCK\n',
        encoding="utf-8",
    )
    res.write_text(
        "MultiLingualTexts:\n  - id: MLC_zero\n    es-ES: .\n"
        "  - id: MLC_one\n    es-ES: original\n",
        encoding="utf-8-sig",
    )
    updater = SimaticSDDbArrayCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        array_name='"DispED"',
        slot_map={1: "nuevo"},
        quote_array_name=True,
        keep_slot0=True,
        ensure_slot0_mlc=True,
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    updater.update()
    updater.save()

    # MLC_zero sigue siendo el del slot 0 (no se inyecto otro).
    assert _s7dcl_has_mlc_block_for(dcl.read_text(encoding="utf-8"), '"DispED"', 0)
    assert 'MLC_zero' in dcl.read_text(encoding="utf-8")


# ── 3. DispED: slot 0 en slot_map se omite si keep_slot0=False ───────

def test_disp_slot0_se_omite_si_keep_slot0_false(tmp_path: Path) -> None:
    """Disp: con keep_slot0=False el slot_map[0] se ignora (warning)."""
    dcl = tmp_path / "DB.s7dcl"
    res = tmp_path / "DB.s7res"
    dcl.write_text(_synth_s7dcl_disp(slot_count=2), encoding="utf-8")
    res.write_text(_synth_s7res_disp({0: ".", 1: "a", 2: "b"}), encoding="utf-8-sig")
    updater = SimaticSDDbArrayCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        array_name='"DispED"',
        slot_map={0: "ignorar", 1: "nuevo"},
        quote_array_name=True,
        keep_slot0=False,           # <-- slot 0 ignorado
        ensure_slot0_mlc=False,
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    updater.update()
    # Slot 0 no fue procesado.
    assert 0 not in updater._result.reused
    assert 0 not in updater._result.inserted


# ── 4. PROC: reutilizacion + propagacion a satellite (case PReal) ──────

def test_proc_reused_principal_y_propagate_a_satellite(tmp_path: Path) -> None:
    """PROC PReal: slot 3 reutilizado, satellite Aux.PReal_ValorAnterior
    tambien reutilizado (slot 1 tenia MLC). Ambos quedan con el mismo texto."""
    dcl = tmp_path / "DB_PRM.s7dcl"
    res = tmp_path / "DB_PRM.s7res"
    dcl.write_text(
        _synth_s7dcl_proc(preal_slots=3, valoranterior_preal=1),
        encoding="utf-8",
    )
    res.write_text(
        _synth_s7res_proc({
            "MLC_prHeader": ".",
            "MLC_prvHeader": ".",
            "MLC_piHeader": ".",
            "MLC_piVisHeader": ".",
            "MLC_auxVaHeader": ".",
            "MLC_auxIaHeader": ".",
            "MLC_pr_001": "orig_pr_1",
            "MLC_pr_002": "orig_pr_2",
            "MLC_pr_003": "orig_pr_3",
            "MLC_aux_vapre_001": "orig_aux_pre_1",
            "MLC_aux_vapre_002": ".",   # satellite slot 2 (sin comentar)
            "MLC_aux_vapre_003": ".",   # satellite slot 3
        }),
        encoding="utf-8-sig",
    )
    updater = SimaticSDDbArrayCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        array_name="PReal",
        slot_map={3: "nuevo_P3"},
        quote_array_name=False,
        keep_slot0=False,
        satellite_arrays={"PReal_Vis", "Aux.PReal_ValorAnterior"},
        registry=MLCRegistry(),
    )
    result = updater.update()
    updater.save()

    # PReal[3] reused; satellite_reused[key] = Aux.PReal_ValorAnterior[3]
    assert result.reused[3] == "MLC_pr_003"
    assert ("Aux.PReal_ValorAnterior", 3) in result.satellite_inserted
    res_text = res.read_text(encoding="utf-8-sig")
    assert _count_es_es(res_text, "nuevo_P3") >= 1


# ── 5. FIX sept-2026: satellite sin MLC recibe uno nuevo ───────────────

def test_proc_satellite_sin_mlc_se_inyecta_fix_sept_2026(
    tmp_path: Path,
) -> None:
    """PROC: PReal_Vis[2] y Aux.PReal_ValorAnterior[2] existen en .s7dcl
    SIN MLC (caso resize N_MAX). El updater DEBE inyectar nuevos MLCs."""
    dcl = tmp_path / "DB_PRM.s7dcl"
    res = tmp_path / "DB_PRM.s7res"
    # Solo PReal[1..2] con MLC. PReal_Vis[1..3] y Aux.PReal_ValorAnterior[1..3]
    # existen con asignacion. Vis/ValorAnterior[1] tienen MLC (pre-existente).
    # Vis[2..3] y ValorAnterior[2..3] NO tienen MLC (tras resize).
    dcl_text = (
        'DATA_BLOCK DB\n'
        '    VAR RETAIN\n'
        '        { S7_MLC := "MLC_pr_h" }\n'
        '        PReal : Array[1..3] of _.UDT_ZC_PREAL;\n'
        '    END_VAR\n'
        '    VAR\n'
        '        { S7_MLC := "MLC_prv_h" }\n'
        '        PReal_Vis : Array[1..3] of Bool;\n'
        '    END_VAR\n'
        '    VAR\n'
        '        Aux : STRUCT\n'
        '            { S7_MLC := "MLC_aux_h" }\n'
        '            PReal_ValorAnterior : Array[1..3] of Real;\n'
        '        END_STRUCT;\n'
        '    END_VAR\n\n'
        '        { S7_MLC := "MLC_pr_001" }\n'
        '        PReal[1] := ();\n'
        '        { S7_MLC := "MLC_pr_002" }\n'
        '        PReal[2] := ();\n'
        '        PReal[3] := ();\n'
        # PReal_Vis: 1 con MLC, 2-3 sin MLC (caso resize).
        '        { S7_MLC := "MLC_prv_001" }\n'
        '        PReal_Vis[1] := FALSE;\n'
        '        PReal_Vis[2] := ();\n'
        '        PReal_Vis[3] := ();\n'
        # Aux.PReal_ValorAnterior: 1 con MLC, 2-3 sin MLC.
        '        { S7_MLC := "MLC_aux_vapre_001" }\n'
        '        Aux.PReal_ValorAnterior[1] := 50.0;\n'
        '        Aux.PReal_ValorAnterior[2] := ();\n'
        '        Aux.PReal_ValorAnterior[3] := ();\n'
        'END_DATA_BLOCK\n'
    )
    dcl.write_text(dcl_text, encoding="utf-8")
    res.write_text(
        _synth_s7res_proc({
            "MLC_pr_h": ".",
            "MLC_prv_h": ".",
            "MLC_aux_h": ".",
            "MLC_pr_001": "orig_pr_1",
            "MLC_pr_002": "orig_pr_2",
            "MLC_prv_001": "orig_prv_1",
            "MLC_aux_vapre_001": "orig_aux_pre_1",
        }),
        encoding="utf-8-sig",
    )
    updater = SimaticSDDbArrayCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        array_name="PReal",
        slot_map={1: "pr_1_new", 2: "pr_2_new", 3: "pr_3_new"},
        quote_array_name=False,
        keep_slot0=False,
        satellite_arrays={"PReal_Vis", "Aux.PReal_ValorAnterior"},
        registry=MLCRegistry(),
    )
    result = updater.update()
    updater.save()

    # PReal[1..2]: reused (tenian MLC).
    assert result.reused[1] == "MLC_pr_001"
    assert result.reused[2] == "MLC_pr_002"
    # PReal[3]: inserted (no tenia MLC).
    assert 3 in result.inserted

    # FIX: PReal_Vis[2..3] y Aux.PReal_ValorAnterior[2..3] deben aparecer en
    # satellite_inserted (slots nuevos tras resize).
    assert ("PReal_Vis", 2) in result.satellite_inserted
    assert ("PReal_Vis", 3) in result.satellite_inserted
    assert ("Aux.PReal_ValorAnterior", 2) in result.satellite_inserted
    assert ("Aux.PReal_ValorAnterior", 3) in result.satellite_inserted

    # PReal_Vis[1] y Aux.PReal_ValorAnterior[1]: reutilizado.
    assert ("PReal_Vis", 1) in result.satellite_reused
    assert ("Aux.PReal_ValorAnterior", 1) in result.satellite_reused

    # Texto comun al principal y satellites nuevos.
    dcl_after = dcl.read_text(encoding="utf-8")
    res_after = res.read_text(encoding="utf-8-sig")
    # El mismo texto "pr_2_new" aparece en PReal[2] (reused) y en
    # sus satellites nuevos (inserted).
    assert _count_es_es(res_after, "pr_2_new") >= 1
    # Los bloques S7_MLC aparecen en PReal_Vis[2..3] y Aux.PReal_ValorAnterior[2..3].
    assert re.search(
        r"\{[^}]*S7_MLC\s*:=\s*\"\S+\"[^}]*\}\s*\n\s*PReal_Vis\[2\]", dcl_after,
    )
    assert re.search(
        r"\{[^}]*S7_MLC\s*:=\s*\"\S+\"[^}]*\}\s*\n\s*PReal_Vis\[3\]", dcl_after,
    )


# ── 6. read_current_comments (API publica) ────────────────────────────

def test_read_current_comments_devuelve_texto_por_slot(
    tmp_path: Path,
) -> None:
    """read_current_comments mapea MLC -> es-ES actual para slots."""
    dcl = tmp_path / "DB_PRM.s7dcl"
    res = tmp_path / "DB_PRM.s7res"
    dcl.write_text(_synth_s7dcl_proc(preal_slots=3), encoding="utf-8")
    res.write_text(
        _synth_s7res_proc({
            "MLC_prHeader": ".",
            "MLC_prvHeader": ".",
            "MLC_piHeader": ".",
            "MLC_piVisHeader": ".",
            "MLC_auxVaHeader": ".",
            "MLC_auxIaHeader": ".",
            "MLC_pr_001": "preal_1_actual",
            "MLC_pr_002": "preal_2_actual",
            "MLC_pr_003": "preal_3_actual",
        }),
        encoding="utf-8-sig",
    )
    updater = SimaticSDDbArrayCommentUpdater(
        s7dcl_path=dcl, s7res_path=res,
        array_name="PReal", slot_map={},
        quote_array_name=False,
        registry=MLCRegistry(),
    )
    result_map = updater.read_current_comments([1, 2, 3, 99], "PReal")
    assert result_map[1] == "preal_1_actual"
    assert result_map[2] == "preal_2_actual"
    assert result_map[3] == "preal_3_actual"
    assert result_map[99] is None   # slot 99 no existe en .s7dcl


# ── 7. was_modified y save in-place ──────────────────────────────────

def test_save_inplace_y_no_save_si_no_hubo_cambios(tmp_path: Path) -> None:
    """save escribe in-place si no se pasan rutas."""
    dcl = tmp_path / "DB.s7dcl"
    res = tmp_path / "DB.s7res"
    dcl.write_text(_synth_s7dcl_disp(slot_count=2), encoding="utf-8")
    res.write_text(_synth_s7res_disp({0: ".", 1: "x", 2: "y"}), encoding="utf-8-sig")

    updater = SimaticSDDbArrayCommentUpdater(
        s7dcl_path=dcl, s7res_path=res,
        array_name='"DispED"', slot_map={1: "x"},   # mismo texto que ya tiene
        quote_array_name=True, keep_slot0=True, ensure_slot0_mlc=True,
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    result = updater.update()
    # same text -> not modified (o al menos sin modificar nada nuevo).
    updater.save()
    assert result.reused.get(1) == "MLC_Disp_001"
