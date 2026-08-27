"""Tests OFFLINE de ``DispCommentUpdater``.

Trabaja sobre archivos ``.s7dcl`` / ``.s7res`` temporales (no toca
el repo). Cubre los casos del plan:
- slot_map vacío (early return).
- slot 0 sin/con MLC existente.
- slot nuevo, slot existente sin MLC, slot existente con MLC.
- eliminación de MLCs huérfanos.
- idempotencia.
- escape de caracteres, sanitización, codificación.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from areas.alimentacion.infrastructure.sd.disp_comment_updater import DispCommentUpdater


# ── Fixtures: contenido de .s7dcl / .s7res ──────────────────────────────


# S7dcl minimal con un array "ED" inicializado, slot 0 con MLC existente
# ("MLC_old0") y un comentario de cabecera, slot 1 con asignación sin MLC.
S7DCL_WITH_SLOT0_MLC = """{
    S7_Author := "HCR";
    S7_BlockComment := "MLC_block_cmt";
    S7_BlockNumber := "2000";
    S7_BlockTitle := "MLC_block_title";
    S7_Family := "ZeusControl";
    S7_Optimized := "TRUE";
    S7_Version := "1.0"
}
DATA_BLOCK DB2000_ED
    VAR RETAIN
        {
            S7_MLC := "MLC_arr_cmt";
            S7_Setpoint := "False"
        }
        "ED" : Array[0.._.N_MAX_DISP_ED] of _.UDT_ZC_DISP_ED;
    END_VAR

    VAR
        { S7_Setpoint := "False" }
        Agrup : Array[0.._.N_MAX_DISP_AGRUP] of _.UDT_ZC_DISP_AGRUP;
        NumDispositivos : Int;
    END_VAR

        "ED"[0].Estado_AutoMan := FALSE;
        "ED"[0].Estado_Activado := FALSE;
        { S7_MLC := "MLC_old0" }
        "ED"[0] := ();
        "ED"[1].Estado_AutoMan := FALSE;
        "ED"[1] := ();

END_DATA_BLOCK
"""

# S7res mínimo con MLC de cabecera + el del slot 0.
S7RES_WITH_OLD = """MultiLingualTexts:
  - id: MLC_block_cmt
    es-ES: Bloque de datos ED
  - id: MLC_arr_cmt
    es-ES: .
  - id: MLC_old0
    es-ES: NO USAR
"""


# S7dcl con slot 0 SIN MLC (asignación sin bloque previo).
S7DCL_NO_SLOT0_MLC = """DATA_BLOCK DB2000_ED
    VAR
        "ED" : Array[0..10] of _.UDT_ZC_DISP_ED;
    END_VAR

        "ED"[0].Estado_AutoMan := FALSE;
        "ED"[0] := ();

END_DATA_BLOCK
"""

# S7res vacío (sin entradas MLC).
S7RES_EMPTY = """MultiLingualTexts:
"""


# ── Helpers ──────────────────────────────────────────────────────────────


def _write_pair(tmp_path: Path, s7dcl: str, s7res: str) -> tuple[Path, Path]:
    dcl = tmp_path / "DB2000_ED.s7dcl"
    res = tmp_path / "DB2000_ED.s7res"
    dcl.write_text(s7dcl, encoding="utf-8")
    # El .s7res se genera con BOM; lo escribimos con utf-8-sig para preservar.
    res.write_text(s7res, encoding="utf-8-sig")
    return dcl, res


def _read_pair(dcl: Path, res: Path) -> tuple[str, str]:
    return (
        dcl.read_text(encoding="utf-8"),
        res.read_text(encoding="utf-8-sig"),
    )


# ── Tests ────────────────────────────────────────────────────────────────


def test_slot_map_vacio(tmp_path: Path) -> None:
    """slot_map sin slot 0 → ValueError (fail-fast en __init__)."""
    dcl, res = _write_pair(tmp_path, S7DCL_WITH_SLOT0_MLC, S7RES_WITH_OLD)
    with pytest.raises(ValueError, match="NO USAR"):
        DispCommentUpdater(dcl, res, slot_map={1: "foo"}, db_array_name="ED")


def test_slot_0_sin_mlc_existente_crea_uno(tmp_path: Path) -> None:
    """El .s7dcl no tiene MLC para el slot 0 → updater crea uno."""
    dcl, res = _write_pair(tmp_path, S7DCL_NO_SLOT0_MLC, S7RES_EMPTY)
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR", 1: "Bomba 1"}, db_array_name="ED"
    )
    result = updater.update()
    updater.save()
    assert result.no_usar_mlc.startswith("MLC_")
    assert 0 in result.inserted  # slot 0 fue insertado (no había MLC previo)
    assert 1 in result.inserted
    new_dcl, new_res = _read_pair(dcl, res)
    # El bloque { S7_MLC := "..." } debe estar justo antes de "ED"[0] := ();
    assert "S7_MLC" in new_dcl
    assert 'ED"[0] := ();' in new_dcl
    # El .s7res debe tener la entrada del MLC nuevo con texto "NO USAR".
    assert f"id: {result.no_usar_mlc}" in new_res
    assert "NO USAR" in new_res


def test_slot_0_con_mlc_existente_lo_respeta(tmp_path: Path) -> None:
    """TIA ya tiene un MLC para slot 0 → NO se regenera."""
    dcl, res = _write_pair(tmp_path, S7DCL_WITH_SLOT0_MLC, S7RES_WITH_OLD)
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR", 1: "Bomba 1"}, db_array_name="ED"
    )
    result = updater.update()
    assert result.no_usar_mlc == "MLC_old0", "Debe respetar MLC existente"
    assert 0 in result.reused
    assert 0 not in result.inserted


def test_slot_nuevo_inserta_asignacion_y_mlc(tmp_path: Path) -> None:
    """Slot sin asignación previa → updater crea bloque + asignación."""
    s7dcl = """DATA_BLOCK DB2000_ED
    VAR
        "ED" : Array[0..10] of _.UDT_ZC_DISP_ED;
    END_VAR

        "ED"[0].Estado_AutoMan := FALSE;
        { S7_MLC := "MLC_old0" }
        "ED"[0] := ();

END_DATA_BLOCK
"""
    s7res = "MultiLingualTexts:\n  - id: MLC_old0\n    es-ES: NO USAR\n"
    dcl, res = _write_pair(tmp_path, s7dcl, s7res)
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR", 3: "Valvula 3"}, db_array_name="ED"
    )
    result = updater.update()
    updater.save()
    assert 0 in result.reused
    assert 3 in result.inserted
    new_dcl, _ = _read_pair(dcl, res)
    assert 'ED"[3] := ();' in new_dcl
    assert "END_DATA_BLOCK" in new_dcl  # la inserción se hizo antes del END_DATA_BLOCK


def test_slot_existente_sin_mlc_lo_anade(tmp_path: Path) -> None:
    """Asignación presente sin S7_MLC → updater añade SOLO el bloque."""
    s7dcl = """DATA_BLOCK DB2000_ED
    VAR
        "ED" : Array[0..10] of _.UDT_ZC_DISP_ED;
    END_VAR

        "ED"[0].Estado_AutoMan := FALSE;
        { S7_MLC := "MLC_old0" }
        "ED"[0] := ();
        "ED"[1].Estado_AutoMan := FALSE;
        "ED"[1] := ();

END_DATA_BLOCK
"""
    s7res = "MultiLingualTexts:\n  - id: MLC_old0\n    es-ES: NO USAR\n"
    dcl, res = _write_pair(tmp_path, s7dcl, s7res)
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR", 1: "Sensor 1"}, db_array_name="ED"
    )
    result = updater.update()
    updater.save()
    assert 0 in result.reused
    assert 1 in result.inserted
    new_dcl, _ = _read_pair(dcl, res)
    # El bloque se añadió justo antes de ED[1] := ();
    # Y la asignación ED[1] := (); sigue presente.
    assert new_dcl.count('ED"[1] := ();') == 1
    assert "S7_MLC" in new_dcl  # ahora hay un bloque S7_MLC para slot 1


def test_elimina_mlc_huerfano_del_s7res(tmp_path: Path) -> None:
    """Entrada en .s7res que ya no se referencia → desaparece."""
    s7dcl = """DATA_BLOCK DB2000_ED
    VAR
        "ED" : Array[0..10] of _.UDT_ZC_DISP_ED;
    END_VAR

        "ED"[0].Estado_AutoMan := FALSE;
        { S7_MLC := "MLC_old0" }
        "ED"[0] := ();

END_DATA_BLOCK
"""
    # El .s7res tiene MLC_old0 (referenciado) Y MLC_orphan (no referenciado).
    s7res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_old0\n"
        "    es-ES: NO USAR\n"
        "  - id: MLC_orphan\n"
        "    es-ES: HUERFANO\n"
    )
    dcl, res = _write_pair(tmp_path, s7dcl, s7res)
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR", 1: "X"}, db_array_name="ED"
    )
    result = updater.update()
    assert "MLC_orphan" not in updater._s7res  # type: ignore[attr-defined]
    assert result.total_mlcs_in_res == 2  # solo MLC_old0 y el nuevo de slot 1


def test_preserva_mlcs_de_cabecera_y_array(tmp_path: Path) -> None:
    """REGRESIÓN: los MLCs de cabecera del bloque (BlockComment, BlockTitle,
    S7_MLC en declaraciones de array) NO deben eliminarse del .s7res aunque
    no aparezcan en el slot_map.

    Bug original: ``_prune_s7res`` solo preservaba MLCs de slots, lo que
    dejaba el .s7res con menos entradas que referencias en el .s7dcl.
    TIA rechazaba el reimport con "Mlc ids present in resource file
    does not match the count of Mlc ids present in source file".
    """
    s7dcl = """{
    S7_BlockComment := "MLC_block_cmt";
    S7_BlockTitle := "MLC_block_title";
    S7_BlockNumber := "2000";
}
DATA_BLOCK DB2000_ED
    VAR RETAIN
        {
            S7_MLC := "MLC_arr_cmt";
        }
        "ED" : Array[0..10] of _.UDT_ZC_DISP_ED;
    END_VAR

        "ED"[0].Estado_AutoMan := FALSE;
        { S7_MLC := "MLC_old0" }
        "ED"[0] := ();

END_DATA_BLOCK
"""
    # .s7res contiene los 4 MLCs de cabecera/array/slot0.
    s7res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_block_cmt\n"
        "    es-ES: Cabecera del bloque\n"
        "  - id: MLC_block_title\n"
        "    es-ES: DB2000_ED\n"
        "  - id: MLC_arr_cmt\n"
        "    es-ES: Comentario del array\n"
        "  - id: MLC_old0\n"
        "    es-ES: NO USAR\n"
    )
    dcl, res = _write_pair(tmp_path, s7dcl, s7res)
    # Slot_map: solo modificamos el slot 0 (que ya tenía MLC_old0).
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR"}, db_array_name="ED"
    )
    updater.update()
    updater.save()
    _, new_res = _read_pair(dcl, res)
    # Los 3 MLCs de cabecera/array SIGUEN en el .s7res.
    for mlc_id in ("MLC_block_cmt", "MLC_block_title", "MLC_arr_cmt"):
        assert f"id: {mlc_id}" in new_res, (
            f"MLC de cabecera {mlc_id!r} fue borrado por _prune_s7res (regresión)."
        )
    # El MLC del slot 0 también.
    assert "id: MLC_old0" in new_res


def test_extract_all_mlcs_from_s7dcl_cubre_tres_formatos(tmp_path: Path) -> None:
    """El método ``_extract_all_mlcs_from_s7dcl`` captura los 3 formatos de
    referencia MLC que TIA contabiliza al comparar con el .s7res.
    """
    s7dcl = """{
    S7_Author := "HCR";
    S7_BlockComment := "MLC_cmt_1";
    S7_BlockNumber := "2000";
    S7_BlockTitle := "MLC_title_1";
}
DATA_BLOCK DB2000_ED
    VAR RETAIN
        {
            S7_MLC := "MLC_arr_1";
        }
        "ED" : Array[0..10] of _.UDT_ZC_DISP_ED;
    END_VAR

        "ED"[0].Estado_AutoMan := FALSE;
        { S7_MLC := "MLC_slot_0" }
        "ED"[0] := ();

END_DATA_BLOCK
"""
    s7res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_cmt_1\n"
        "    es-ES: x\n"
        "  - id: MLC_title_1\n"
        "    es-ES: x\n"
        "  - id: MLC_arr_1\n"
        "    es-ES: x\n"
        "  - id: MLC_slot_0\n"
        "    es-ES: NO USAR\n"
    )
    dcl, res = _write_pair(tmp_path, s7dcl, s7res)
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR"}, db_array_name="ED"
    )
    extracted = updater._extract_all_mlcs_from_s7dcl()  # type: ignore[attr-defined]
    assert "MLC_cmt_1" in extracted     # S7_BlockComment
    assert "MLC_title_1" in extracted   # S7_BlockTitle
    assert "MLC_arr_1" in extracted     # S7_MLC en bloque de array
    assert "MLC_slot_0" in extracted    # S7_MLC en bloque de slot
    assert len(extracted) == 4


def test_idempotencia_doble_apply(tmp_path: Path) -> None:
    """Aplicar el mismo slot_map 2 veces produce archivos byte-idénticos."""
    dcl, res = _write_pair(tmp_path, S7DCL_WITH_SLOT0_MLC, S7RES_WITH_OLD)
    slot_map = {0: "NO USAR", 1: "Bomba 1", 2: "Bomba 2"}
    updater1 = DispCommentUpdater(dcl, res, slot_map=slot_map, db_array_name="ED")
    updater1.update()
    updater1.save()

    dcl1 = dcl.read_text(encoding="utf-8")
    res1 = res.read_text(encoding="utf-8-sig")

    updater2 = DispCommentUpdater(dcl, res, slot_map=slot_map, db_array_name="ED")
    updater2.update()
    updater2.save()

    dcl2 = dcl.read_text(encoding="utf-8")
    res2 = res.read_text(encoding="utf-8-sig")

    assert dcl1 == dcl2, "Idempotencia .s7dcl rota"
    assert res1 == res2, "Idempotencia .s7res rota"


def test_escape_comillas_dobles_en_texto(tmp_path: Path) -> None:
    """Texto con comillas dobles → escapado en ambos archivos."""
    dcl, res = _write_pair(tmp_path, S7DCL_NO_SLOT0_MLC, S7RES_EMPTY)
    updater = DispCommentUpdater(
        dcl, res,
        slot_map={0: "NO USAR", 1: 'Bomba "A" principal'},
        db_array_name="ED",
    )
    result = updater.update()
    updater.save()
    _, new_res = _read_pair(dcl, res)
    # En YAML, comillas dobles se duplican.
    assert 'Bomba ""A"" principal' in new_res
    # En el .s7dcl, los IDs no llevan comillas en su contenido; verificar
    # que el MLC se generó y está en el .s7res.
    assert result.inserted[1] in new_res


def test_texto_vacio_se_convierte_a_punto(tmp_path: Path) -> None:
    """plc_comentario == '' → escribe '.' (convención TIA)."""
    dcl, res = _write_pair(tmp_path, S7DCL_NO_SLOT0_MLC, S7RES_EMPTY)
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR", 1: ""}, db_array_name="ED"
    )
    result = updater.update()
    updater.save()
    _, new_res = _read_pair(dcl, res)
    assert f"id: {result.inserted[1]}" in new_res
    # Buscar la línea de ese MLC concreto.
    lines = new_res.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"- id: {result.inserted[1]}":
            assert "es-ES: ." in lines[i + 1]
            break
    else:
        pytest.fail(f"No se encontró la entrada de {result.inserted[1]} en .s7res")


def test_unicode_acentos_en(tmp_path: Path) -> None:
    """Caracteres no-ASCII (ñ, tildes) se preservan en UTF-8."""
    dcl, res = _write_pair(tmp_path, S7DCL_NO_SLOT0_MLC, S7RES_EMPTY)
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR", 1: "Módulo de medición"}, db_array_name="ED"
    )
    updater.update()
    updater.save()
    _, new_res = _read_pair(dcl, res)
    assert "Módulo de medición" in new_res


def test_was_modified_true_si_cambia_algo(tmp_path: Path) -> None:
    """was_modified devuelve True si el updater modificó el contenido."""
    dcl, res = _write_pair(tmp_path, S7DCL_NO_SLOT0_MLC, S7RES_EMPTY)
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR", 1: "X"}, db_array_name="ED"
    )
    assert not updater.was_modified()
    updater.update()
    assert updater.was_modified()


def test_was_modified_false_si_idempotente(tmp_path: Path) -> None:
    """Re-aplicar el mismo slot_map → was_modified == False la 2ª vez."""
    dcl, res = _write_pair(tmp_path, S7DCL_WITH_SLOT0_MLC, S7RES_WITH_OLD)
    slot_map = {0: "NO USAR", 1: "X"}
    # Primera pasada: modifica (crea el MLC de slot 1).
    up1 = DispCommentUpdater(dcl, res, slot_map=slot_map, db_array_name="ED")
    up1.update()
    up1.save()
    # Segunda pasada: NO modifica (idempotente).
    up2 = DispCommentUpdater(dcl, res, slot_map=slot_map, db_array_name="ED")
    up2.update()
    assert not up2.was_modified()


def test_db_array_name_vacio_falla(tmp_path: Path) -> None:
    """db_array_name vacío → ValueError."""
    dcl, res = _write_pair(tmp_path, S7DCL_NO_SLOT0_MLC, S7RES_EMPTY)
    with pytest.raises(ValueError, match="db_array_name"):
        DispCommentUpdater(dcl, res, slot_map={0: "NO USAR", 1: "X"}, db_array_name="")


def test_no_modifica_otros_arrays(tmp_path: Path) -> None:
    """El updater no toca las asignaciones de otros arrays (Agrup, etc.)."""
    dcl, res = _write_pair(tmp_path, S7DCL_WITH_SLOT0_MLC, S7RES_WITH_OLD)
    updater = DispCommentUpdater(
        dcl, res, slot_map={0: "NO USAR", 1: "X"}, db_array_name="ED"
    )
    updater.update()
    updater.save()
    new_dcl, _ = _read_pair(dcl, res)
    # La sección de Agrup debe seguir intacta (no la hemos tocado).
    assert "Agrup" in new_dcl
    # Agrup está declarado en la sección VAR, no inicializado en el fixture.
    assert "Agrup : Array" in new_dcl
    # La sección de inicialización del array ED sigue conteniendo sus
    # propiedades declaradas (no las hemos tocado).
    assert '"ED"[0].Estado_AutoMan := FALSE;' in new_dcl
