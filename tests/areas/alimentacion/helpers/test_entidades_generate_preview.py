"""Tests del helper puro ``areas/alimentacion/helpers/entidades/entidades_generate_preview``.

Replica el patron de ``test_disp_generate_preview`` para el feature ENTIDADES:
  - Sin XML (missing_xml=True).
  - Match 1:1.
  - Adds / removes / renames (numero cambia con mismo plc_tag).
  - Sin desired ni base.
  - Renombrado vs changed-by-value.
  - Comentarios UDT (added / updated / unchanged / missing).

El ``PlcUserConstantModifier`` (parser SimaticML) se mockea siempre: el
helper no es responsable del formato XML, solo de la logica del diff.
Tests del parser viven en ``tests/core/``.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from areas.alimentacion.helpers.entidades.entidades_generate_preview import (
    DiffComments,
    DiffEntities,
    compute_comments_diff,
    compute_diff_entities,
    compute_summary,
)


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------


class FakeEntidad:
    """Minimal ``EntidadLike`` para tests del helper puro."""

    def __init__(
        self,
        numero: int,
        plc_tag: str,
        plc_comentario: str = "",
        plc_name: str = "PLC_S1500",
    ) -> None:
        self.numero = numero
        self.plc_tag = plc_tag
        self.plc_comentario = plc_comentario
        self.plc_name = plc_name


def _mock_modifier_with_constants(plc_tag_to_numero: dict[str, int]) -> MagicMock:
    """Crea un mock de PlcUserConstantModifier con ``read_user_constants_with_uids``.

    Devuelve ``{str(numero): "<plc_tag>"}`` (formato real del parser
    tras C.10: el helper ya no quita prefijo ``ent_`` porque la tabla
    ``6_Entidades`` viene pre-filtrada por el operario y los nombres
    son canonicos en MAYUSCULAS, p.ej. ``ENT_000``).
    """
    modifier = MagicMock()
    raw = {
        str(numero): plc_tag
        for plc_tag, numero in plc_tag_to_numero.items()
    }
    modifier.read_user_constants_with_uids.return_value = raw
    return modifier


# ---------------------------------------------------------------------------
# Tests de compute_diff_entities
# ---------------------------------------------------------------------------


def test_compute_diff_entities_match_1_1(tmp_path: Path) -> None:
    """Match 1:1 entre desired y base."""
    xml = tmp_path / "6_Entidades.xml"
    xml.write_text("<dummy/>", encoding="utf-8")

    modifier = _mock_modifier_with_constants({"AAA": 1, "BBB": 2, "CCC": 3})
    desired = [
        FakeEntidad(numero=1, plc_tag="AAA"),
        FakeEntidad(numero=2, plc_tag="BBB"),
        FakeEntidad(numero=3, plc_tag="CCC"),
    ]
    with patch(
        "core.helpers.simatic_ml.PlcUserConstantModifier",
        return_value=modifier,
    ):
        diff = compute_diff_entities("6_Entidades", desired, xml)

    assert diff.missing_xml is False
    assert diff.added == []
    assert diff.removed == []
    assert diff.renamed == {}
    assert diff.base == {"AAA": 1, "BBB": 2, "CCC": 3}
    assert diff.desired == {"AAA": 1, "BBB": 2, "CCC": 3}
    assert diff.is_empty


def test_compute_diff_entities_sin_xml(tmp_path: Path) -> None:
    """Sin XML -> missing_xml=True, desired intacto, todos los desired como added."""
    xml = tmp_path / "no_existe.xml"
    desired = [FakeEntidad(numero=1, plc_tag="AAA")]

    diff = compute_diff_entities("6_Entidades", desired, xml)

    assert diff.missing_xml is True
    # Sin XML no podemos saber si los plc_tags del desired existen en
    # TIA. El sync los marcara como added (inyectar).
    assert diff.added == ["AAA"]
    assert diff.removed == []
    assert diff.renamed == {}
    assert diff.base == {}
    assert diff.desired == {"AAA": 1}


def test_compute_diff_entities_adds(tmp_path: Path) -> None:
    """Adds: plc_tag en Excel no en TIA."""
    xml = tmp_path / "6_Entidades.xml"
    xml.write_text("<dummy/>", encoding="utf-8")

    modifier = _mock_modifier_with_constants({"AAA": 1})
    desired = [
        FakeEntidad(numero=1, plc_tag="AAA"),
        FakeEntidad(numero=2, plc_tag="BBB"),
        FakeEntidad(numero=3, plc_tag="CCC"),
    ]
    with patch(
        "core.helpers.simatic_ml.PlcUserConstantModifier",
        return_value=modifier,
    ):
        diff = compute_diff_entities("6_Entidades", desired, xml)

    assert diff.added == ["BBB", "CCC"]
    assert diff.removed == []
    assert diff.renamed == {}


def test_compute_diff_entities_removes(tmp_path: Path) -> None:
    """Removes: plc_tag en TIA no en Excel."""
    xml = tmp_path / "6_Entidades.xml"
    xml.write_text("<dummy/>", encoding="utf-8")

    modifier = _mock_modifier_with_constants({"AAA": 1, "BBB": 2, "CCC": 3})
    desired = [FakeEntidad(numero=1, plc_tag="AAA")]
    with patch(
        "core.helpers.simatic_ml.PlcUserConstantModifier",
        return_value=modifier,
    ):
        diff = compute_diff_entities("6_Entidades", desired, xml)

    assert diff.added == []
    assert diff.removed == ["BBB", "CCC"]
    assert diff.renamed == {}


def test_compute_diff_entities_renames(tmp_path: Path) -> None:
    """Renames: plc_tag en ambos pero con numero distinto.

    En entidades, NO es rename real (es ``update_user_constant_value``).
    Se reporta como ``renamed`` para que la SPA lo muestre y el sync (D)
    decida la operacion.
    """
    xml = tmp_path / "6_Entidades.xml"
    xml.write_text("<dummy/>", encoding="utf-8")

    modifier = _mock_modifier_with_constants({"AAA": 1, "BBB": 2})
    desired = [
        FakeEntidad(numero=1, plc_tag="AAA"),
        FakeEntidad(numero=5, plc_tag="BBB"),  # mismo plc_tag, numero distinto
    ]
    with patch(
        "core.helpers.simatic_ml.PlcUserConstantModifier",
        return_value=modifier,
    ):
        diff = compute_diff_entities("6_Entidades", desired, xml)

    assert diff.added == []
    assert diff.removed == []
    assert diff.renamed == {"BBB": (2, 5)}


def test_compute_diff_entities_sin_desired(tmp_path: Path) -> None:
    """Excel vacio -> todos los entries de TIA son 'removed'."""
    xml = tmp_path / "6_Entidades.xml"
    xml.write_text("<dummy/>", encoding="utf-8")

    modifier = _mock_modifier_with_constants({"AAA": 1, "BBB": 2})
    with patch(
        "core.helpers.simatic_ml.PlcUserConstantModifier",
        return_value=modifier,
    ):
        diff = compute_diff_entities("6_Entidades", [], xml)

    assert diff.added == []
    assert diff.removed == ["AAA", "BBB"]
    assert diff.renamed == {}


def test_compute_diff_entities_sin_base_y_sin_desired(tmp_path: Path) -> None:
    """Ambos vacios -> diff vacio."""
    xml = tmp_path / "6_Entidades.xml"
    xml.write_text("<dummy/>", encoding="utf-8")

    modifier = _mock_modifier_with_constants({})
    with patch(
        "core.helpers.simatic_ml.PlcUserConstantModifier",
        return_value=modifier,
    ):
        diff = compute_diff_entities("6_Entidades", [], xml)

    assert diff.missing_xml is False
    assert diff.added == []
    assert diff.removed == []
    assert diff.renamed == {}


def test_compute_diff_entities_ignora_plc_tag_vacio(tmp_path: Path) -> None:
    """Filas del Excel con plc_tag vacio NO entran en desired."""
    xml = tmp_path / "6_Entidades.xml"
    xml.write_text("<dummy/>", encoding="utf-8")

    modifier = _mock_modifier_with_constants({"AAA": 1})
    desired = [
        FakeEntidad(numero=1, plc_tag="AAA"),
        FakeEntidad(numero=2, plc_tag=""),  # ignorado
        FakeEntidad(numero=3, plc_tag=None),  # ignorado
    ]
    with patch(
        "core.helpers.simatic_ml.PlcUserConstantModifier",
        return_value=modifier,
    ):
        diff = compute_diff_entities("6_Entidades", desired, xml)

    assert diff.desired == {"AAA": 1}
    assert diff.added == []


def test_compute_diff_entities_n_total_changes(tmp_path: Path) -> None:
    """``n_total_changes`` = len(added) + len(renamed)."""
    xml = tmp_path / "6_Entidades.xml"
    xml.write_text("<dummy/>", encoding="utf-8")

    modifier = _mock_modifier_with_constants({"AAA": 1, "BBB": 2})
    desired = [
        FakeEntidad(numero=1, plc_tag="AAA"),
        FakeEntidad(numero=5, plc_tag="BBB"),  # renamed
        FakeEntidad(numero=99, plc_tag="CCC"),  # added
    ]
    with patch(
        "core.helpers.simatic_ml.PlcUserConstantModifier",
        return_value=modifier,
    ):
        diff = compute_diff_entities("6_Entidades", desired, xml)

    assert diff.n_total_changes == 2  # 1 added + 1 renamed


# ---------------------------------------------------------------------------
# Tests de compute_comments_diff
# ---------------------------------------------------------------------------


def _fake_dcl_with_udt_slots(array_name: str, slots: list[int]) -> str:
    """Genera un .s7dcl fake con bloques ``{ S7_MLC := "id" }`` antes de cada slot.

    El formato real del simulador de SimaticSD requiere el MLC id
    adyacente a la asignacion ``ENT[i] := ();`` para que
    ``read_current_comments`` pueda mapear slot -> MLC id -> texto.
    Sin el MLC, el helper devuelve ``None`` para todos los slots.
    """
    lines = ["DATA_BLOCK DB6_ENT", "STRUCT", "  dummy : INT;", ""]
    for i, s in enumerate(slots):
        # MLC id unico (formato que acepta el regex S7_MLC).
        lines.append(f'        {{ S7_MLC := "MLC_TEST_{i}" }}')
        lines.append(f"        {array_name}[{s}] := ();")
    lines.extend(["END_STRUCT;", "END_DATA_BLOCK"])
    return "\n".join(lines)


def _fake_res_with_mlc(mlc_texts: dict[str, str]) -> str:
    """Genera un .s7res fake con MultiLingualTexts."""
    import yaml

    textos = [{"id": mid, "es-ES": txt} for mid, txt in mlc_texts.items()]
    return yaml.safe_dump({"MultiLingualTexts": textos}, allow_unicode=True)


def test_compute_comments_diff_added_slot() -> None:
    """Slot en Excel (no en TIA) -> added."""
    dcl = _fake_dcl_with_udt_slots("ENT", [0, 1])
    res = _fake_res_with_mlc({
        "MLC_TEST_0": "PLC_S1500",
        "MLC_TEST_1": "AAA",
    })

    desired = [FakeEntidad(numero=2, plc_tag="NEW", plc_comentario="nuevo slot")]
    diff = compute_comments_diff("DB6_ENT", "ENT", desired, dcl, res)

    assert diff.slots_tia == {0, 1}
    assert diff.added == [2]
    assert diff.updated == []
    assert diff.removed == []  # preservacion defensiva
    assert diff.unchanged == []


def test_compute_comments_diff_updated_slot() -> None:
    """Slot con comment distinto -> updated."""
    dcl = _fake_dcl_with_udt_slots("ENT", [0, 1])
    # Slot 0 -> MLC_TEST_0, slot 1 -> MLC_TEST_1.
    res = _fake_res_with_mlc({
        "MLC_TEST_0": "comentario antiguo slot 0",
        "MLC_TEST_1": "AAA",
    })

    desired = [
        FakeEntidad(numero=0, plc_tag="X", plc_comentario="comentario nuevo slot 0"),
        FakeEntidad(numero=1, plc_tag="AAA", plc_comentario="AAA"),
    ]
    diff = compute_comments_diff("DB6_ENT", "ENT", desired, dcl, res)

    assert diff.added == []
    assert diff.updated == [0]
    assert diff.removed == []
    assert diff.unchanged == [1]


def test_compute_comments_diff_unchanged_slot() -> None:
    """Slot con comment igual -> unchanged."""
    dcl = _fake_dcl_with_udt_slots("ENT", [0, 1])
    res = _fake_res_with_mlc({
        "MLC_TEST_0": "AAA",
        "MLC_TEST_1": "BBB",
    })

    desired = [
        FakeEntidad(numero=0, plc_tag="X", plc_comentario="AAA"),
        FakeEntidad(numero=1, plc_tag="Y", plc_comentario="BBB"),
    ]
    diff = compute_comments_diff("DB6_ENT", "ENT", desired, dcl, res)

    assert diff.added == []
    assert diff.updated == []
    assert diff.removed == []
    assert diff.unchanged == [0, 1]


def test_compute_comments_diff_slot_tia_sin_excel_no_se_elimina() -> None:
    """Slots en TIA sin Excel -> NO se eliminan en preview (preservacion)."""
    dcl = _fake_dcl_with_udt_slots("ENT", [0, 1, 2])
    res = _fake_res_with_mlc({
        "MLC_TEST_0": "comentario 0",
        "MLC_TEST_1": "comentario 1",
        "MLC_TEST_2": "comentario 2",
    })

    desired = [FakeEntidad(numero=0, plc_tag="X", plc_comentario="comentario 0")]
    diff = compute_comments_diff("DB6_ENT", "ENT", desired, dcl, res)

    # Slots 1 y 2 existen en TIA pero no en Excel: el preview los
    # PRESERVA (no los marca como removed). El sync (D) decidira.
    assert diff.added == []
    assert diff.updated == []
    assert diff.removed == []
    assert diff.unchanged == [0]


def test_compute_comments_diff_missing_xml() -> None:
    """Sin .s7dcl/.s7res -> missing_xml=True, slots_tia vacio."""
    diff = compute_comments_diff(
        "DB6_ENT", "ENT",
        [FakeEntidad(numero=0, plc_tag="X", plc_comentario="test")],
        dcl_text="",
        res_text="",
    )

    assert diff.missing_xml is True
    assert diff.slots_tia == set()
    assert diff.current == {}


# ---------------------------------------------------------------------------
# Tests de compute_summary
# ---------------------------------------------------------------------------


def test_compute_summary_agregado() -> None:
    """compute_summary agrega correctamente constantes + comments."""
    diff_ent = DiffEntities(
        table_name="6_Entidades",
        base={"AAA": 1, "BBB": 2},
        desired={"AAA": 1, "BBB": 2, "CCC": 3},
        added=["CCC"],
        removed=[],
        renamed={},
    )
    diff_com = DiffComments(
        db_name="DB6_ENT",
        array_name="ENT",
        slots_tia={0, 1},
        current={0: "foo", 1: "bar"},
        desired={0: "baz", 1: "bar"},  # 0 updated, 1 unchanged
        added=[],
        removed=[],
        updated=[0],
        unchanged=[1],
    )

    s = compute_summary(diff_ent, diff_com)

    assert s["constants_agregados"] == 1
    assert s["constants_sin_cambios"] == 2  # AAA + BBB
    assert s["comments_updated"] == 1
    assert s["comments_unchanged"] == 1
    assert s["total"] == 1 + 1  # 1 add + 1 updated


# ---------------------------------------------------------------------------
# Tests de Dataclasses (sanity)
# ---------------------------------------------------------------------------


def test_diff_entities_is_empty() -> None:
    """``DiffEntities.is_empty`` es True si no hay cambios."""
    diff = DiffEntities(
        table_name="6_Entidades",
        base={}, desired={},
        added=[], removed=[], renamed={},
    )
    assert diff.is_empty is True


def test_diff_comments_n_total_changes() -> None:
    """``DiffComments.n_total_changes`` = len(added) + len(updated)."""
    diff = DiffComments(
        db_name="DB6_ENT",
        array_name="ENT",
        slots_tia={0, 1, 2},
        current={}, desired={},
        added=[3], removed=[], updated=[0, 1], unchanged=[2],
    )
    assert diff.n_total_changes == 3