"""Tests del ``ProcesoCommentUpdater``.

Cubre el updater offline análogo a ``DispCommentUpdater`` pero
parametrizado por ``array_name`` + ``satellite_arrays`` (sin slot 0
fijo) y con propagación de ``es-ES`` a los satélites del mismo
slot. No toca TIA, no toca red, no toca disco fuera de ``tmp_path``.

Estructura de los tests
-----------------------
* ``synthetic_s7dcl`` / ``synthetic_s7res``: fixture que escribe
  pares sintéticos ``.s7dcl`` / ``.s7res`` con el shape esperado
  (3 arrays paralelos: PReal, PReal_Vis, Aux.PReal_ValorAnterior,
  cada uno con slots 1..N). Aísla los tests del formato real de
  los ``_source/`` de la CPR (que pueden cambiar entre PRs).
* El test 6 (encoding) usa ``tmp_path`` directo.
* El resto usa la fixture sintética como base.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from areas.alimentacion.infrastructure.sd.mlc_registry import MLCRegistry
from areas.alimentacion.infrastructure.sd.proc_comment_updater import (
    ProcesoCommentResult,
    ProcesoCommentUpdater,
    strip_enclosing_quotes,
)


# ── Fixtures sintéticos ─────────────────────────────────────────────────


def _build_synthetic_s7dcl(n_slots: int = 30) -> str:
    """Genera un .s7dcl con 3 arrays paralelos (PReal, PReal_Vis, Aux.PReal_ValorAnterior)."""
    header = (
        '{\n'
        '    S7_Author := "ABH";\n'
        '    S7_BlockNumber := "53100";\n'
        '    S7_Family := "ZeusControl";\n'
        '    S7_Optimized := "TRUE";\n'
        '    S7_BlockComment := "MLC_bloque";\n'
        '    S7_BlockTitle := "MLC_titulo";\n'
        '}\n'
        'DATA_BLOCK "DB53100_TEST_PARAM"\n'
        '    VAR RETAIN\n'
        '        { S7_MLC := "MLC_RU" }\n'
        '        PReal : Array[1.._."50100_N_MAX_PREAL"] of _.UDT_ZC_PREAL;\n'
        '    END_VAR\n'
        '    VAR\n'
        '        { S7_MLC := "MLC_vis_arr" }\n'
        '        PReal_Vis : Array[1.._."50100_N_MAX_PREAL"] of Bool;\n'
        '    END_VAR\n'
        '    VAR\n'
        '        Aux : STRUCT\n'
        '            { S7_MLC := "MLC_aux_arr" }\n'
        '            PReal_ValorAnterior : Array[1.._."50100_N_MAX_PREAL"] of Real;\n'
        '        END_STRUCT;\n'
        '    END_VAR\n'
        '\n'
    )
    body = []
    for i in range(1, n_slots + 1):
        body.append(f'        {{ S7_MLC := "MLC_PR_{i:03d}" }}\n')
        body.append(f'        PReal[{i}] := ();\n')
        body.append(f'        {{ S7_MLC := "MLC_VIS_{i:03d}" }}\n')
        body.append(f'        PReal_Vis[{i}] := FALSE;\n')
        body.append(f'        {{ S7_MLC := "MLC_VA_{i:03d}" }}\n')
        body.append(f'        Aux.PReal_ValorAnterior[{i}] := ();\n')
    body.append("\nEND_DATA_BLOCK\n")
    return header + "".join(body)


def _build_synthetic_s7res(n_slots: int = 30) -> str:
    """Genera un .s7res con los MLCs de cabecera + slots."""
    lines = ["MultiLingualTexts:"]
    # MLCs de cabecera (cabecera del bloque y arrays declarados).
    lines.append("  - id: MLC_bloque")
    lines.append("    es-ES: Test block comment")
    lines.append("  - id: MLC_titulo")
    lines.append("    es-ES: Test block title")
    lines.append("  - id: MLC_RU")
    lines.append("    es-ES: PReal")
    lines.append("  - id: MLC_vis_arr")
    lines.append("    es-ES: PReal_Vis")
    lines.append("  - id: MLC_aux_arr")
    lines.append("    es-ES: Aux.PReal_ValorAnterior")
    for i in range(1, n_slots + 1):
        lines.append(f"  - id: MLC_PR_{i:03d}")
        lines.append(f"    es-ES: original_PR_{i}")
        lines.append(f"  - id: MLC_VIS_{i:03d}")
        lines.append(f"    es-ES: original_VIS_{i}")
        lines.append(f"  - id: MLC_VA_{i:03d}")
        lines.append(f"    es-ES: original_VA_{i}")
    return "\n".join(lines) + "\n"


@pytest.fixture
def synthetic_block(tmp_path: Path) -> tuple[Path, Path]:
    """Devuelve (s7dcl_path, s7res_path) en tmp_path."""
    dcl = tmp_path / "DB53100_TEST_PARAM.s7dcl"
    res = tmp_path / "DB53100_TEST_PARAM.s7res"
    dcl.write_text(_build_synthetic_s7dcl(30), encoding="utf-8")
    res.write_text(_build_synthetic_s7res(30), encoding="utf-8-sig")
    return dcl, res


@pytest.fixture
def registry_with_existing() -> MLCRegistry:
    reg = MLCRegistry()
    reg.reserve({"MLC_existente_1", "MLC_existente_2"})
    return reg


# ── Tests ───────────────────────────────────────────────────────────────


def test_slot_unico_inserta_mlc_y_actualiza_es_es(
    synthetic_block: tuple[Path, Path],
) -> None:
    """slot_map = {1: "nuevo"} → updater respeta MLC existente, actualiza es-ES."""
    dcl, res = synthetic_block
    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={1: "nuevo_PR_1"},
        array_name="PReal",
        satellite_arrays={"PReal_Vis", "Aux.PReal_ValorAnterior"},
        registry=MLCRegistry(),
    )
    result = updater.update()
    updater.save()
    assert isinstance(result, ProcesoCommentResult)
    assert updater.was_modified() is True
    # Slot 1: MLC reutilizado (MLC_PR_001 ya estaba).
    assert result.reused[1] == "MLC_PR_001"
    assert result.inserted == {}
    # (Nota: satellite_reused es dict con key=slot, así que solo
    # queda el último satélite escrito en el dict. La cobertura
    # completa de la propagación se verifica en el .s7res abajo
    # y en test_propagacion_a_satelites_mismo_slot.)
    content = res.read_text(encoding="utf-8-sig")
    # 3 entradas (principal + 2 satélites) con es-ES = "nuevo_PR_1"
    count = content.count("es-ES: nuevo_PR_1")
    assert count == 3, f"Esperaba 3 entradas con es-ES: nuevo_PR_1; encontré {count}"


def test_slot_map_mas_corto_que_el_array(
    synthetic_block: tuple[Path, Path],
) -> None:
    """slot_map = {1, 2, 3} → solo esos 3 se actualizan, resto intacto."""
    dcl, res = synthetic_block
    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={1: "x1", 2: "x2", 3: "x3"},
        array_name="PReal",
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    updater.update()
    updater.save()
    content = res.read_text(encoding="utf-8-sig")
    # Slots 1, 2, 3 actualizados.
    assert "es-ES: x1" in content
    assert "es-ES: x2" in content
    assert "es-ES: x3" in content
    # Slot 4 sigue con el texto original.
    assert "es-ES: original_PR_4" in content
    # Slot 30 (último) también intacto.
    assert "es-ES: original_PR_30" in content


def test_slot_map_vacio_no_modifica(
    synthetic_block: tuple[Path, Path],
) -> None:
    """slot_map = {} → was_modified() False, ningún cambio."""
    dcl, res = synthetic_block
    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={},
        array_name="PReal",
        satellite_arrays={"PReal_Vis"},
        registry=MLCRegistry(),
    )
    updater.update()
    assert updater.was_modified() is False


def test_idempotencia_doble_apply(
    synthetic_block: tuple[Path, Path],
) -> None:
    """Aplicar el mismo slot_map 2 veces → 2ª was_modified() False, sin cambios."""
    dcl, res = synthetic_block
    # Primera pasada.
    updater1 = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={1: "nuevo_PR_1", 2: "nuevo_PR_2"},
        array_name="PReal",
        satellite_arrays={"PReal_Vis"},
        registry=MLCRegistry(),
    )
    updater1.update()
    updater1.save()
    assert updater1.was_modified() is True
    # Segunda pasada con los MISMOS textos.
    updater2 = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={1: "nuevo_PR_1", 2: "nuevo_PR_2"},
        array_name="PReal",
        satellite_arrays={"PReal_Vis"},
        registry=MLCRegistry(),
    )
    updater2.update()
    assert updater2.was_modified() is False


def test_propagacion_a_satelites_mismo_slot(
    synthetic_block: tuple[Path, Path],
) -> None:
    """slot_map = {5: "nuevo"} → PReal_Vis[5] y Aux.PReal_ValorAnterior[5]
    también actualizan su es-ES con el mismo texto (MLCs distintos)."""
    dcl, res = synthetic_block
    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={5: "COMPARTIDO_5"},
        array_name="PReal",
        satellite_arrays={"PReal_Vis", "Aux.PReal_ValorAnterior"},
        registry=MLCRegistry(),
    )
    result = updater.update()
    updater.save()
    assert updater.was_modified() is True
    # MLC principal: slot 5 reutilizado.
    assert result.reused[5] == "MLC_PR_005"
    content = res.read_text(encoding="utf-8-sig")
    # 3 entradas (principal + 2 satélites) con es-ES = "COMPARTIDO_5"
    count = content.count("es-ES: COMPARTIDO_5")
    assert count == 3, f"Esperaba 3 entradas con es-ES: COMPARTIDO_5; encontré {count}"
    # El resto de slots conserva su texto original.
    assert "es-ES: original_PR_4" in content
    assert "es-ES: original_VIS_4" in content
    assert "es-ES: original_VA_4" in content


def test_sin_satelites_para_alm(
    tmp_path: Path,
) -> None:
    """ALM con satellite_arrays=set() funciona: no busca satélites,
    actualiza solo el array principal."""
    dcl_text = (
        'DATA_BLOCK "DB55100_TEST_ALM"\n'
        '    VAR RETAIN\n'
        '        { S7_MLC := "MLC_arr" }\n'
        '        ALM : Array[1..10] of _.UDT_ZC_ALARMA;\n'
        '    END_VAR\n'
        '\n'
        '        { S7_MLC := "MLC_ALM_001" }\n'
        '        ALM[1] := ();\n'
        '        { S7_MLC := "MLC_ALM_002" }\n'
        '        ALM[2] := ();\n'
        'END_DATA_BLOCK\n'
    )
    res_text = (
        "MultiLingualTexts:\n"
        "  - id: MLC_arr\n"
        "    es-ES: ALM\n"
        "  - id: MLC_ALM_001\n"
        "    es-ES: alarma_1_orig\n"
        "  - id: MLC_ALM_002\n"
        "    es-ES: alarma_2_orig\n"
    )
    dcl = tmp_path / "DB55100_TEST_ALM.s7dcl"
    res = tmp_path / "DB55100_TEST_ALM.s7res"
    dcl.write_text(dcl_text, encoding="utf-8")
    res.write_text(res_text, encoding="utf-8-sig")
    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={1: "alarma_1_nueva", 2: "alarma_2_nueva"},
        array_name="ALM",
        satellite_arrays=set(),  # ALM no tiene satélites
        registry=MLCRegistry(),
    )
    result = updater.update()
    updater.save()
    assert updater.was_modified() is True
    assert result.reused[1] == "MLC_ALM_001"
    assert result.reused[2] == "MLC_ALM_002"
    # No hay satélites.
    assert result.satellite_reused == {}
    content = res.read_text(encoding="utf-8-sig")
    assert "es-ES: alarma_1_nueva" in content
    assert "es-ES: alarma_2_nueva" in content


def test_encoding_utf8_sin_bom_s7dcl_utf8_sig_s7res(
    tmp_path: Path,
) -> None:
    """El .s7dcl se escribe como utf-8 sin BOM; el .s7res como utf-8-sig con BOM."""
    dcl = tmp_path / "DB53100_TEST_PARAM.s7dcl"
    res = tmp_path / "DB53100_TEST_PARAM.s7res"
    dcl.write_text(_build_synthetic_s7dcl(5), encoding="utf-8")
    res.write_text(_build_synthetic_s7res(5), encoding="utf-8-sig")

    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={1: "x1"},
        array_name="PReal",
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    updater.update()
    updater.save()

    # s7dcl: sin BOM.
    dcl_bytes = dcl.read_bytes()
    assert not dcl_bytes.startswith(b"\xef\xbb\xbf"), "s7dcl no debería tener BOM"
    # s7res: con BOM (utf-8-sig).
    res_bytes = res.read_bytes()
    assert res_bytes.startswith(b"\xef\xbb\xbf"), "s7res debería tener BOM"


def test_truncado_texto_a_254_chars(
    synthetic_block: tuple[Path, Path],
) -> None:
    """Texto > 254 chars se trunca con warning."""
    dcl, res = synthetic_block
    long_text = "x" * 300
    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={1: long_text},
        array_name="PReal",
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    updater.update()
    updater.save()
    content = res.read_text(encoding="utf-8-sig")
    # El texto aparece truncado a 254 chars.
    truncated_marker = "es-ES: " + ("x" * 254)
    assert truncated_marker in content
    # El texto completo (300 x's) NO aparece.
    assert "es-ES: " + ("x" * 300) not in content


def test_slot_map_mayor_que_array_inserta_nuevos_slots(
    tmp_path: Path,
) -> None:
    """slot_map con slots > N_MAX del array → updater inserta asignaciones nuevas."""
    dcl = tmp_path / "DB53100_TEST_PARAM.s7dcl"
    res = tmp_path / "DB53100_TEST_PARAM.s7res"
    dcl.write_text(_build_synthetic_s7dcl(5), encoding="utf-8")
    res.write_text(_build_synthetic_s7res(5), encoding="utf-8-sig")

    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={1: "x1", 6: "x6", 7: "x7"},  # 6 y 7 no existen en el DB
        array_name="PReal",
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    result = updater.update()
    updater.save()
    assert updater.was_modified() is True
    # Slot 1: MLC existente.
    assert result.reused[1] == "MLC_PR_001"
    # Slots 6 y 7: MLCs nuevos generados.
    assert 6 in result.inserted
    assert 7 in result.inserted
    content = dcl.read_text(encoding="utf-8")
    # Las nuevas asignaciones aparecen antes de END_DATA_BLOCK.
    assert "PReal[6] := ()" in content
    assert "PReal[7] := ()" in content


def test_slot_0_se_ignora(
    synthetic_block: tuple[Path, Path],
) -> None:
    """slot_map con slot 0 se ignora silenciosamente (los arrays de proceso empiezan en 1)."""
    dcl, res = synthetic_block
    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={0: "NO USAR", 1: "slot_1_nuevo"},
        array_name="PReal",
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    result = updater.update()
    # Slot 0 NO aparece en reused ni en inserted.
    assert 0 not in result.reused
    assert 0 not in result.inserted
    # Slot 1 sí se actualiza.
    assert result.reused[1] == "MLC_PR_001"


def test_comentario_vacio_se_mapea_a_punto(
    synthetic_block: tuple[Path, Path],
) -> None:
    """comentario_db vacío → es-ES = '.' (convención TIA 'sin comentario')."""
    dcl, res = synthetic_block
    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={1: ""},
        array_name="PReal",
        satellite_arrays=set(),
        registry=MLCRegistry(),
    )
    updater.update()
    updater.save()
    content = res.read_text(encoding="utf-8-sig")
    # MLC_PR_001 ahora tiene es-ES = "."
    assert "es-ES: ." in content


def test_construye_registry_con_mlcs_existentes(
    synthetic_block: tuple[Path, Path],
) -> None:
    """Si el .s7res tiene MLCs pre-existentes, el updater los respeta."""
    dcl, res = synthetic_block
    updater = ProcesoCommentUpdater(
        s7dcl_path=dcl,
        s7res_path=res,
        slot_map={1: "nuevo_PR_1"},
        array_name="PReal",
        satellite_arrays=set(),
        registry=MLCRegistry(),  # el updater inicializa desde .s7res
    )
    result = updater.update()
    # El MLC del slot 1 (MLC_PR_001) se respeta, no se genera uno nuevo.
    assert result.reused[1] == "MLC_PR_001"
    assert 1 not in result.inserted


# ── Comillas envolventes (TIA exporta a veces con '…' alrededor) ────────


class TestStripEnclosingQuotes:
    """Cubre el helper ``strip_enclosing_quotes`` (público).

    Se llama desde:
      * ``ProcesoCommentUpdater._build_mlc_text_map`` al leer el
        ``.s7res`` (lado TIA).
      * ``_sanitize_comment_text`` al escribir (apply).
      * ``proc_slot_map_builder._build_slot_map`` al leer el Excel
        (lado desired).

    La función es conservadora: solo actúa si el texto empieza Y
    termina con la MISMA comilla (simples o dobles).
    """

    def test_empty_string_devuelve_empty(self):
        assert strip_enclosing_quotes("") == ""

    def test_single_char_se_queda_igual(self):
        # Una sola comilla no es "envolvente" por longitud < 2.
        assert strip_enclosing_quotes("'") == "'"

    def test_sin_comillas_se_queda_igual(self):
        assert strip_enclosing_quotes("COMPACTO - FIJOS") == "COMPACTO - FIJOS"

    def test_comillas_simples_envolventes_se_quitan(self):
        # Caso típico que ve el operario: TIA exporta
        # ``es-ES: 'COMPACTO - FIJOS - '`` (con espacio al final).
        assert (
            strip_enclosing_quotes("'COMPACTO - FIJOS - '")
            == "COMPACTO - FIJOS -"
        )

    def test_comillas_dobles_envolventes_se_quitan(self):
        assert (
            strip_enclosing_quotes('"COMPACTO - FIJOS - "')
            == "COMPACTO - FIJOS -"
        )

    def test_comillas_no_balanceadas_se_quedan_igual(self):
        # Una sola comilla al inicio o al final NO se quita (puede
        # ser parte legítima del texto).
        assert strip_enclosing_quotes("'hola") == "'hola"
        assert strip_enclosing_quotes("hola'") == "hola'"

    def test_comillas_mixtas_no_se_quitan(self):
        # Empieza con ' y termina con " (o viceversa) → no es
        # "envolvente balanceada", se queda igual.
        assert strip_enclosing_quotes("'hola\"") == "'hola\""

    def test_espacios_dentro_de_comillas_se_stripean(self):
        # TIA a veces deja espacios colgando DENTRO de las comillas
        # (p. ej. ``'COMPACTO - ' `` con espacio tras el último
        # carácter). El helper los quita tras extraer el contenido.
        assert (
            strip_enclosing_quotes("'COMPACTO '")
            == "COMPACTO"
        )

    def test_texto_con_comilla_interna_al_final_se_conserva(self):
        # El texto contiene una comilla simple legítima en su
        # interior. NO debe quitarla.
        assert (
            strip_enclosing_quotes("Bomba de 6'' pulgada")
            == "Bomba de 6'' pulgada"
        )


class TestReadCurrentCommentsStripsEnclosingQuotes:
    """Verifica que ``ProcesoCommentUpdater.read_current_comments``
    quita comillas envolventes que TIA pone al exportar el ``.s7res``.

    Caso real visto por el operario: la UI mostraba
    ``'COMPACTO - FIJOS - '`` (con comillas) como ``current`` en
    lugar de ``COMPACTO - FIJOS -``. Eso provocaba que el diff
    reportara "renombrar" cuando en realidad el desired (Excel) y
    el current (TIA) eran el mismo texto.
    """

    def test_quita_comillas_simples_del_s7res(
        self, tmp_path, synthetic_block
    ):
        # Partimos del bloque sintético estándar (que tiene slots
        # 1..30 con el MLC correspondiente), pero sobrescribimos el
        # ``.s7res`` con un comentario ENTRE comillas simples en
        # el slot 1 (caso TIA real visto en producción).
        dcl, res = synthetic_block
        new_s7res = (
            "MultiLingualTexts:\n"
            "  - id: MLC_PR_001\n"
            "    es-ES: 'COMPACTO - FIJOS - '\n"
        )
        res.write_text(new_s7res, encoding="utf-8-sig")
        updater = ProcesoCommentUpdater(
            s7dcl_path=dcl,
            s7res_path=res,
            slot_map={},
        )
        # El ``current`` del slot 1 viene SIN comillas envolventes.
        result = updater.read_current_comments([1], "PReal")
        assert result[1] == "COMPACTO - FIJOS -", (
            f"esperaba 'COMPACTO - FIJOS -', recibí {result[1]!r}"
        )
