"""Tests de ``commit_proc_simplified`` (sept-2026 refactor DRY)."""
from __future__ import annotations

from pathlib import Path

import yaml

from areas.alimentacion.helpers.proc.proc_commit_simplified import (
    PROC_ARRAYS_ALM,
    PROC_ARRAYS_PARAM,
    ProcCommitSummary,
    commit_proc_simplified,
)


_BASE_DCL = """DATA_BLOCK "DB_TEST"
    VAR RETAIN
        { S7_MLC := "MLC_prHeader" }
        PReal : Array[1..3] of _.UDT_ZC_PREAL;
    END_VAR
    VAR
        PReal_Vis : Array[1..3] of Bool;
        Aux : STRUCT
            PReal_ValorAnterior : Array[1..3] of Real;
        END_STRUCT;
    END_VAR
    VAR RETAIN
        PInt : Array[1..3] of _.UDT_ZC_PINT;
    END_VAR
    VAR
        PInt_Vis : Array[1..3] of Bool;
        Aux.PInt_ValorAnterior : Array[1..3] of Int;
    END_VAR
    VAR RETAIN
        { S7_MLC := "MLC_almHeader" }
        ALM : Array[1..3] of Bool;
    END_VAR
END_DATA_BLOCK
"""

_BASE_RES = """MultiLingualTexts:
  - id: MLC_prHeader
    es-ES: Header PReal
  - id: MLC_almHeader
    es-ES: Header ALM
"""


def _write_pair(tmp_path: Path, dcl: str, res: str) -> tuple[Path, Path]:
    dcl_p = tmp_path / "DB_PARAM.s7dcl"
    res_p = tmp_path / "DB_PARAM.s7res"
    dcl_p.write_text(dcl, encoding="utf-8-sig")
    res_p.write_text(res, encoding="utf-8-sig")
    return dcl_p, res_p


# ── PROC_ARRAYS_PARAM shape ────────────────────────────────────────

def test_proc_arrays_param_contiene_los_6_arrays() -> None:
    """Los 6 arrays del PARAM: PReal + PInt + sus 4 satellites."""
    arrays = [name for name, _ in PROC_ARRAYS_PARAM]
    assert arrays == [
        "PReal",
        "PReal_Vis",
        "Aux.PReal_ValorAnterior",
        "PInt",
        "PInt_Vis",
        "Aux.PInt_ValorAnterior",
    ]


def test_proc_arrays_param_tipos_correctos() -> None:
    """PReal y PInt son UDT; sus satellites son Simple."""
    types = dict(PROC_ARRAYS_PARAM)
    assert types["PReal"] == "UDT"
    assert types["PInt"] == "UDT"
    assert types["PReal_Vis"] == "Simple"
    assert types["Aux.PReal_ValorAnterior"] == "Simple"
    assert types["PInt_Vis"] == "Simple"
    assert types["Aux.PInt_ValorAnterior"] == "Simple"


def test_proc_arrays_alm_solo_tiene_alm() -> None:
    """ALM es un unico array (no tiene satellites)."""
    assert PROC_ARRAYS_ALM == [("ALM", "Simple")]


# ── commit_proc_simplified ─────────────────────────────────────────

def test_commit_proc_simplified_acumula_sobre_mismo_archivo(
    tmp_path: Path,
) -> None:
    """Las 6 llamadas escriben sobre el mismo .s7dcl/.s7res
    (``write_to_original=True``); el archivo final contiene
    TODOS los cambios acumulados."""
    dcl_p, res_p = _write_pair(tmp_path, _BASE_DCL, _BASE_RES)

    slot_maps = {
        "PReal":   {1: "PR 1"},
        "PInt":    {1: "PI 1"},
        "PReal_Vis": {1: "PV 1"},
    }
    result = commit_proc_simplified(dcl_p, res_p, slot_maps)

    # Los 3 arrays con slot_map aparecen en per_array.
    assert set(result.per_array.keys()) == {"PReal", "PInt", "PReal_Vis"}
    # Los 3 sin slot_map NO aparecen (skip en el bucle).
    assert "PInt_Vis" not in result.per_array

    # El archivo .s7dcl ORIGINAL contiene los 3 cambios.
    dcl_final = dcl_p.read_text(encoding="utf-8-sig")
    # PReal[1] := (); fue inyectado (CASO A).
    assert "PReal[1] := ();" in dcl_final
    # PReal_Vis[1] := (); fue inyectado (CASO A; no existia
    # asignacion previa en este sintético).
    assert "PReal_Vis[1] := ();" in dcl_final
    # PInt[1] := (); fue inyectado (CASO A).
    assert "PInt[1] := ();" in dcl_final

    # El .s7res ORIGINAL contiene los 3 textos.
    res_final = yaml.safe_load(res_p.read_text(encoding="utf-8-sig"))
    textos = {t["es-ES"] for t in res_final["MultiLingualTexts"]}
    assert "PR 1" in textos
    assert "PI 1" in textos
    assert "PV 1" in textos


def test_commit_proc_simplified_array_vacio_es_noop(tmp_path: Path) -> None:
    """Array sin slot_map: se skipea, no aparece en per_array."""
    dcl_p, res_p = _write_pair(tmp_path, _BASE_DCL, _BASE_RES)
    slot_maps = {"PReal": {1: "PR 1"}}
    result = commit_proc_simplified(dcl_p, res_p, slot_maps)

    assert "PReal" in result.per_array
    for name, _ in PROC_ARRAYS_PARAM:
        if name != "PReal":
            assert name not in result.per_array


def test_commit_proc_simplified_no_crea_archivo_modificado(
    tmp_path: Path,
) -> None:
    """``write_to_original=True`` (via wrapper): NO crea
    ``modificado_<file>``. Solo modifica los originales."""
    dcl_p, res_p = _write_pair(tmp_path, _BASE_DCL, _BASE_RES)
    commit_proc_simplified(
        dcl_p, res_p, {"PReal": {1: "PR 1"}},
    )
    assert not (tmp_path / "modificado_DB_PARAM.s7dcl").exists()
    assert not (tmp_path / "modificado_DB_PARAM.s7res").exists()


def test_commit_proc_simplified_total_injected_agregado(tmp_path: Path) -> None:
    """``total_injected`` suma los slots inyectados de todos los arrays."""
    dcl_p, res_p = _write_pair(tmp_path, _BASE_DCL, _BASE_RES)
    slot_maps = {
        "PReal":   {1: "PR 1", 2: "PR 2"},   # CASO A x2
        "PInt":    {1: "PI 1"},              # CASO A x1
    }
    result = commit_proc_simplified(dcl_p, res_p, slot_maps)
    assert result.total_injected == 3


def test_commit_proc_simplified_usa_array_types_custom(tmp_path: Path) -> None:
    """Si pasamos ``array_types`` custom, se itera SOLO esa lista."""
    dcl_p, res_p = _write_pair(tmp_path, _BASE_DCL, _BASE_RES)
    # Solo procesar PReal (ignorar PInt y satellites).
    result = commit_proc_simplified(
        dcl_p, res_p,
        {"PReal": {1: "PR 1"}},
        array_types=[("PReal", "UDT")],
    )
    assert set(result.per_array.keys()) == {"PReal"}


def test_commit_proc_simplified_para_alm(tmp_path: Path) -> None:
    """El wrapper tambien sirve para ALM (1 array, sin satellites)."""
    dcl_p, res_p = _write_pair(tmp_path, _BASE_DCL, _BASE_RES)
    result = commit_proc_simplified(
        dcl_p, res_p,
        {"ALM": {1: "Alarma 1"}},
        array_types=PROC_ARRAYS_ALM,
    )
    assert "ALM" in result.per_array
    assert result.per_array["ALM"].injected[1].startswith("MLC_")
