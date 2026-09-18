"""Tests de ``commit_array_comments`` .

Cubre los 4 casos del helper con archivos .s7dcl sinteticos que
representan los formatos A (inline) y B (standalone) de TIA V21.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.helpers.simatic_sd import (
    ArrayCommitResult,
    commit_array_comments,
    next_mlc_id,
)


# ── Fixtures ────────────────────────────────────────────────────────

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
END_DATA_BLOCK
"""

_BASE_RES = """MultiLingualTexts:
  - id: MLC_prHeader
    es-ES: Header
"""


def _write_pair(tmp_path: Path, dcl: str, res: str) -> tuple[Path, Path]:
    """Escribe un par .s7dcl/.s7res en tmp_path y devuelve las rutas."""
    dcl_p = tmp_path / "DB.s7dcl"
    res_p = tmp_path / "DB.s7res"
    dcl_p.write_text(dcl, encoding="utf-8-sig")
    res_p.write_text(res, encoding="utf-8-sig")
    return dcl_p, res_p


# ── CASO A: slot no existe, inyectar ────────────────────────────────

def test_caso_a_inyecta_slot_nuevo_udt(tmp_path: Path) -> None:
    """Caso A: el slot no existe en el .s7dcl, se inyecta ``{ MLC } := ();``.

    Formato B (standalone): se inserta el bloque + asignacion
    raiz vacia antes de END_DATA_BLOCK.
    """
    dcl_p, res_p = _write_pair(tmp_path, _BASE_DCL, _BASE_RES)
    result = commit_array_comments(
        dcl_p, res_p, "PReal", {1: "PR 1"}, array_type="UDT",
    )
    assert 1 in result.injected
    new_id = result.injected[1]
    assert new_id.startswith("MLC_")

    dcl_out = (tmp_path / "modificado_DB.s7dcl").read_text(encoding="utf-8-sig")
    assert f"S7_MLC := \"{new_id}\"" in dcl_out
    assert "PReal[1] := ();" in dcl_out
    assert dcl_out.endswith("END_DATA_BLOCK\n") or "END_DATA_BLOCK" in dcl_out

    res_out = yaml.safe_load(
        (tmp_path / "modificado_DB.s7res").read_text(encoding="utf-8-sig")
    )
    ids = {t["id"] for t in res_out["MultiLingualTexts"]}
    assert new_id in ids
    texto = next(t for t in res_out["MultiLingualTexts"] if t["id"] == new_id)
    assert texto["es-ES"] == "PR 1"


def test_caso_a_inyecta_multiples_slots(tmp_path: Path) -> None:
    """Multiples slots NUEVOS: cada uno recibe su propio MLC ID."""
    dcl_p, res_p = _write_pair(tmp_path, _BASE_DCL, _BASE_RES)
    result = commit_array_comments(
        dcl_p, res_p, "PReal", {1: "PR 1", 2: "PR 2", 3: "PR 3"}, array_type="UDT",
    )
    assert set(result.injected.keys()) == {1, 2, 3}
    assert len({result.injected[i] for i in (1, 2, 3)}) == 3  # todos distintos


def test_caso_a_inyecta_slot_simple_en_seccion_a(tmp_path: Path) -> None:
    """CASO A en Seccion A (formato inline): slot ``PReal_Vis[1]`` no existe.

    Aunque el archivo tiene ``PReal_Vis[1] := FALSE;`` (formato A), el
    slot NUEVO es 5 (no existe). El helper lo inyecta antes de
    END_DATA_BLOCK en formato B."""
    dcl_p, res_p = _write_pair(
        tmp_path,
        _BASE_DCL.replace("END_DATA_BLOCK", "        PReal_Vis[1] := FALSE;\nEND_DATA_BLOCK"),
        _BASE_RES,
    )
    result = commit_array_comments(
        dcl_p, res_p, "PReal_Vis", {5: "PV 5"}, array_type="Simple",
    )
    assert 5 in result.injected


# ── CASO B: existe con MLC, comentario vacio, eliminar ─────────────

def test_caso_b_elimina_mlc_de_slot_existente(tmp_path: Path) -> None:
    """CASO B: el slot existe con MLC, texto vacio = eliminar MLC del bloque."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        '        { S7_MLC := "MLC_old"; }\n        PReal[1] := ();\nEND_DATA_BLOCK',
    )
    res = _BASE_RES + '  - id: MLC_old\n    es-ES: old_text\n'
    dcl_p, res_p = _write_pair(tmp_path, dcl, res)

    result = commit_array_comments(
        dcl_p, res_p, "PReal", {1: ""}, array_type="UDT",
    )
    assert 1 in result.removed

    dcl_out = (tmp_path / "modificado_DB.s7dcl").read_text(encoding="utf-8-sig")
    assert "MLC_old" not in dcl_out
    # Si el bloque era solo { S7_MLC := "..." } y la asignacion es := (),
    # se borra la linea entera (ancla vacia).
    assert "PReal[1] := ();" not in dcl_out

    res_out = yaml.safe_load(
        (tmp_path / "modificado_DB.s7res").read_text(encoding="utf-8-sig")
    )
    ids = {t["id"] for t in res_out["MultiLingualTexts"]}
    assert "MLC_old" not in ids


def test_caso_b_preserva_otros_metadatos_del_bloque(tmp_path: Path) -> None:
    """CASO B: el bloque ``{ ... }`` tiene mas metadatos aparte del MLC.
    Al eliminar el MLC, los demas metadatos se conservan."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        '        { S7_MLC := "MLC_old"; S7_Setpoint := "True"; }\n'
        '        PReal[1] := ();\nEND_DATA_BLOCK',
    )
    res = _BASE_RES + '  - id: MLC_old\n    es-ES: old_text\n'
    dcl_p, res_p = _write_pair(tmp_path, dcl, res)

    result = commit_array_comments(
        dcl_p, res_p, "PReal", {1: ""}, array_type="UDT",
    )
    assert 1 in result.removed
    dcl_out = (tmp_path / "modificado_DB.s7dcl").read_text(encoding="utf-8-sig")
    assert "MLC_old" not in dcl_out
    assert "S7_Setpoint" in dcl_out  # conservado
    assert "PReal[1] := ();" in dcl_out  # la asignacion se mantiene


# ── CASO C: existe con MLC, actualizar texto ──────────────────────

def test_caso_c_actualiza_texto_en_res(tmp_path: Path) -> None:
    """CASO C: slot existe con MLC, texto nuevo != texto actual.

    Solo se actualiza el ``es-ES`` en .s7res (el .s7dcl no cambia).
    """
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        '        { S7_MLC := "MLC_pr_001"; }\n        PReal[1] := ();\nEND_DATA_BLOCK',
    )
    res = _BASE_RES + '  - id: MLC_pr_001\n    es-ES: old\n'
    dcl_p, res_p = _write_pair(tmp_path, dcl, res)

    result = commit_array_comments(
        dcl_p, res_p, "PReal", {1: "nuevo texto"}, array_type="UDT",
    )
    assert result.updated == {1: "MLC_pr_001"}

    res_out = yaml.safe_load(
        (tmp_path / "modificado_DB.s7res").read_text(encoding="utf-8-sig")
    )
    texto = next(t for t in res_out["MultiLingualTexts"] if t["id"] == "MLC_pr_001")
    assert texto["es-ES"] == "nuevo texto"

    dcl_out = (tmp_path / "modificado_DB.s7dcl").read_text(encoding="utf-8-sig")
    # El .s7dcl no cambia (el MLC sigue siendo el mismo).
    assert 'S7_MLC := "MLC_pr_001"' in dcl_out


def test_caso_c_noop_si_texto_identico(tmp_path: Path) -> None:
    """CASO C con texto identico al actual: no-op (no aparece en updated)."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        '        { S7_MLC := "MLC_pr_001"; }\n        PReal[1] := ();\nEND_DATA_BLOCK',
    )
    res = _BASE_RES + '  - id: MLC_pr_001\n    es-ES: mismo\n'
    dcl_p, res_p = _write_pair(tmp_path, dcl, res)

    result = commit_array_comments(
        dcl_p, res_p, "PReal", {1: "mismo"}, array_type="UDT",
    )
    assert result.updated == {}
    assert 1 in result.noop


# ── CASO D: existe SIN MLC, anadir MLC ────────────────────────────

def test_caso_d_anade_mlc_a_slot_existente_simple(tmp_path: Path) -> None:
    """CASO D: slot existe como ``PReal_Vis[1] := FALSE;`` SIN MLC adyacente.

    Caso del bug  smoke en vivo proceso 50010: el helper
    detecta que el slot existe (sin MLC) y le anade el bloque MLC.
    """
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        "        PReal_Vis[1] := FALSE;\nEND_DATA_BLOCK",
    )
    dcl_p, res_p = _write_pair(tmp_path, dcl, _BASE_RES)

    result = commit_array_comments(
        dcl_p, res_p, "PReal_Vis", {1: "PV 1"}, array_type="Simple",
    )
    assert 1 in result.injected
    new_id = result.injected[1]

    dcl_out = (tmp_path / "modificado_DB.s7dcl").read_text(encoding="utf-8-sig")
    assert f'S7_MLC := "{new_id}"' in dcl_out
    assert "PReal_Vis[1] := FALSE;" in dcl_out

    res_out = yaml.safe_load(
        (tmp_path / "modificado_DB.s7res").read_text(encoding="utf-8-sig")
    )
    texto = next(t for t in res_out["MultiLingualTexts"] if t["id"] == new_id)
    assert texto["es-ES"] == "PV 1"


def test_caso_d_anade_mlc_preservando_otros_metadatos(tmp_path: Path) -> None:
    """CASO D: el bloque ``{ ... }`` tiene otros metadatos (S7_Access, etc.).
    El MLC se anade al inicio del bloque, los demas metadatos se conservan."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        '        { S7_Access := "ReadOnly"; }\n'
        '        Aux.PReal_ValorAnterior[1] := 50.0;\nEND_DATA_BLOCK',
    )
    dcl_p, res_p = _write_pair(tmp_path, dcl, _BASE_RES)

    result = commit_array_comments(
        dcl_p, res_p, "Aux.PReal_ValorAnterior", {1: "VA 1"}, array_type="Simple",
    )
    assert 1 in result.injected
    new_id = result.injected[1]

    dcl_out = (tmp_path / "modificado_DB.s7dcl").read_text(encoding="utf-8-sig")
    assert f'S7_MLC := "{new_id}"' in dcl_out
    assert "S7_Access" in dcl_out
    assert "Aux.PReal_ValorAnterior[1] := 50.0;" in dcl_out


# ── Casos limite ───────────────────────────────────────────────────

def test_slot_que_no_existe_y_texto_vacio_es_noop(tmp_path: Path) -> None:
    """Slot no existe + texto vacio = no-op (no se inyecta nada)."""
    dcl_p, res_p = _write_pair(tmp_path, _BASE_DCL, _BASE_RES)
    result = commit_array_comments(
        dcl_p, res_p, "PReal", {99: ""}, array_type="UDT",
    )
    assert 99 in result.noop
    assert result.injected == {}
    # El archivo no se reescribe con cambios significativos.
    dcl_out = (tmp_path / "modificado_DB.s7dcl").read_text(encoding="utf-8-sig")
    assert "PReal[99]" not in dcl_out


def test_error_si_no_hay_end_data_block(tmp_path: Path) -> None:
    """Sin END_DATA_BLOCK no se puede inyectar (CASO A): falla explicita."""
    dcl_p, res_p = _write_pair(
        tmp_path, "DATA_BLOCK DB\n  VAR\n  END_VAR\n", _BASE_RES,
    )
    with pytest.raises(ValueError, match="END_DATA_BLOCK"):
        commit_array_comments(
            dcl_p, res_p, "PReal", {1: "x"}, array_type="UDT",
        )


def test_udt_no_matchea_sub_campos(tmp_path: Path) -> None:
    """Para UDT, ``PReal[1].Valor := 50.0;`` NO cuenta como PReal[1] existente.

    El helper busca SOLO la asignacion raiz ``:= ();``.
    """
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK",
        "        PReal[1].Valor := 50.0;\n"
        "        PReal[1].Maximo := 100.0;\n"
        "        PReal[1].Minimo := 10.0;\nEND_DATA_BLOCK",
    )
    dcl_p, res_p = _write_pair(tmp_path, dcl, _BASE_RES)

    # Para UDT, PReal[1] no existe (solo hay sub-campos). CASO A.
    result = commit_array_comments(
        dcl_p, res_p, "PReal", {1: "PR 1"}, array_type="UDT",
    )
    assert 1 in result.injected


def test_simple_matchea_asignacion_con_valor(tmp_path: Path) -> None:
    """Para Simple, ``PReal_Vis[1] := FALSE;`` matchea (CASO D, sin MLC)."""
    dcl = _BASE_DCL.replace(
        "END_DATA_BLOCK", "        PReal_Vis[1] := FALSE;\nEND_DATA_BLOCK",
    )
    dcl_p, res_p = _write_pair(tmp_path, dcl, _BASE_RES)

    result = commit_array_comments(
        dcl_p, res_p, "PReal_Vis", {1: "PV 1"}, array_type="Simple",
    )
    assert 1 in result.injected  # CASO D, no CASO A


def test_slot_map_vacio_no_modifica_archivos(tmp_path: Path) -> None:
    """slot_map vacio: no hay cambios, archivos se reescriben identicos."""
    dcl_p, res_p = _write_pair(tmp_path, _BASE_DCL, _BASE_RES)
    result = commit_array_comments(
        dcl_p, res_p, "PReal", {}, array_type="UDT",
    )
    assert result.injected == {}
    assert result.updated == {}
    assert result.removed == []
