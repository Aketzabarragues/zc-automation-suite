"""Tests del helper ``compute_diff_table``.

Cubre el contrato del diff entre desired (Excel) y base (TIA Portal):

  * ``numero >= 0`` con ``plc_tag`` no vacio entra en ``desired``.
    Esto incluye la fila ``numero=0`` que la macro del Excel siempre
    genera como placeholder (``ED_000``, ``EA_000``, etc.).
  * ``numero < 0`` o ``plc_tag`` vacio se filtran (defensivo).
  * Idempotente: si base y desired coinciden, ``added=removed=renamed=[]``.
  * Rename: si base tiene ``("0", "OLD")`` y desired ``("0", "ED_000")``
    → ``renamed={"0": ("OLD", "ED_000")}``.

El XML base se construye a mano con la estructura minima SimaticML
que ``PlcUserConstantParser`` espera: un nodo ``<SW.Tags.PlcUserConstant>``
con ``<AttributeList>`` que contiene ``<Name>`` y ``<Value>`` (int).

Restriccion: este test NO toca TIA real. El XML se genera en tmp_path.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from areas.alimentacion.helpers.disp.disp_generate_preview import (
    compute_diff_table,
)


SIM_NS = "http://www.siemens.com/automation/Openness/SW/Interface/v5"
ETREE_NS = {"sw": SIM_NS}


def _disp(numero: int, plc_tag: str) -> SimpleNamespace:
    """Adapter minimo que satisface ``DispositivoLike`` (Protocol)."""
    return SimpleNamespace(numero=numero, plc_tag=plc_tag)


def _write_plc_user_constants_xml(
    xml_path: Path,
    constants: list[tuple[str, str]],
) -> None:
    """Escribe un .xml SimaticML con N ``PlcUserConstants``.

    Args:
        xml_path: ruta destino.
        constants: lista de ``(name, value_str)``. Cada tupla se
            serializa como un PlcUserConstant con ``<Name>`` y ``<Value>``.
            ``value_str`` debe ser casteable a ``int`` (los PlcUserConstant
            no-int se descartan en el reader).
    """
    import xml.etree.ElementTree as ET

    ns_uri = SIM_NS
    root = ET.Element(f"{{{ns_uri}}}Document")
    tag_table = ET.SubElement(
        root, f"{{{ns_uri}}}SW.Tags.TagTable"
    )
    for name, value_str in constants:
        constant = ET.SubElement(
            tag_table, f"{{{ns_uri}}}SW.Tags.PlcUserConstant"
        )
        attribute_list = ET.SubElement(
            constant, f"{{{ns_uri}}}AttributeList"
        )
        name_el = ET.SubElement(attribute_list, f"{{{ns_uri}}}Name")
        name_el.text = name
        value_el = ET.SubElement(attribute_list, f"{{{ns_uri}}}Value")
        value_el.text = value_str
    ET.ElementTree(root).write(
        str(xml_path), encoding="utf-8", xml_declaration=True
    )


# ---------------------------------------------------------------------------
# Contrato basico (lock-in del comportamiento pre-existente)
# ---------------------------------------------------------------------------


def test_numero_positivo_con_plc_tag_entra_en_desired(tmp_path: Path) -> None:
    """``numero > 0`` con ``plc_tag`` no vacio entra en ``desired``."""
    xml_path = tmp_path / "2000_Disp_ED.xml"
    _write_plc_user_constants_xml(xml_path, [])

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[_disp(1, "ED_001"), _disp(2, "ED_002")],
        xml_path=xml_path,
    )

    assert diff.desired == {"1": "ED_001", "2": "ED_002"}
    assert diff.added == ["1", "2"]
    assert diff.removed == []
    assert diff.renamed == {}
    assert diff.missing_xml is False


def test_numero_positivo_con_plc_tag_vacio_se_filtra(tmp_path: Path) -> None:
    """``numero > 0`` pero ``plc_tag=""`` se filtra (defensivo)."""
    xml_path = tmp_path / "2000_Disp_ED.xml"
    _write_plc_user_constants_xml(xml_path, [])

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[_disp(1, ""), _disp(2, "ED_002")],
        xml_path=xml_path,
    )

    assert diff.desired == {"2": "ED_002"}
    assert diff.added == ["2"]


def test_numero_negativo_se_filtra(tmp_path: Path) -> None:
    """``numero < 0`` se filtra aunque tenga ``plc_tag``."""
    xml_path = tmp_path / "2000_Disp_ED.xml"
    _write_plc_user_constants_xml(xml_path, [])

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[_disp(-1, "X"), _disp(0, "ED_000"), _disp(1, "ED_001")],
        xml_path=xml_path,
    )

    assert diff.desired == {"0": "ED_000", "1": "ED_001"}


# ---------------------------------------------------------------------------
# Contrato del placeholder (numero=0 con plc_tag)
# ---------------------------------------------------------------------------


def test_placeholder_numero_cero_con_plc_tag_entra_en_desired(
    tmp_path: Path,
) -> None:
    """``numero=0`` con ``plc_tag`` no vacio entra en ``desired``."""
    xml_path = tmp_path / "2000_Disp_ED.xml"
    _write_plc_user_constants_xml(xml_path, [])

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[_disp(0, "ED_000")],
        xml_path=xml_path,
    )

    assert diff.desired == {"0": "ED_000"}
    assert diff.added == ["0"]
    assert diff.removed == []


def test_placeholder_no_se_marca_como_removed(tmp_path: Path) -> None:
    """Si base ya tiene el placeholder y desired lo quiere, NO va a removed."""
    xml_path = tmp_path / "2000_Disp_ED.xml"
    _write_plc_user_constants_xml(
        xml_path, [("ED_000", "0"), ("ED_001", "1"), ("ED_002", "2")],
    )

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[_disp(0, "ED_000"), _disp(1, "ED_001")],
        xml_path=xml_path,
    )

    assert "0" not in diff.removed
    assert diff.removed == ["2"]


def test_placeholder_idempotente(tmp_path: Path) -> None:
    """Re-sync con mismo placeholder NO genera cambios."""
    xml_path = tmp_path / "2000_Disp_ED.xml"
    _write_plc_user_constants_xml(
        xml_path, [("ED_000", "0"), ("ED_001", "1")],
    )

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[_disp(0, "ED_000"), _disp(1, "ED_001")],
        xml_path=xml_path,
    )

    assert diff.added == []
    assert diff.removed == []
    assert diff.renamed == {}
    assert diff.is_empty is True


def test_placeholder_rename_si_plc_tag_difiere(tmp_path: Path) -> None:
    """Si base tiene ``("0", "OLD")`` y desired ``("0", "ED_000")``
    → ``renamed={"0": ("OLD", "ED_000")}``.
    """
    xml_path = tmp_path / "2000_Disp_ED.xml"
    _write_plc_user_constants_xml(
        xml_path, [("OLD", "0"), ("ED_001", "1")],
    )

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[_disp(0, "ED_000"), _disp(1, "ED_001")],
        xml_path=xml_path,
    )

    assert diff.added == []
    assert diff.removed == []
    assert diff.renamed == {"0": ("OLD", "ED_000")}


def test_placeholder_con_plc_tag_vacio_se_filtra(tmp_path: Path) -> None:
    """``numero=0`` con ``plc_tag=""`` se filtra (defensivo)."""
    xml_path = tmp_path / "2000_Disp_ED.xml"
    _write_plc_user_constants_xml(xml_path, [])

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[_disp(0, ""), _disp(1, "ED_001")],
        xml_path=xml_path,
    )

    assert "0" not in diff.desired
    assert diff.desired == {"1": "ED_001"}


# ---------------------------------------------------------------------------
# Edge cases de base
# ---------------------------------------------------------------------------


def test_xml_inexistente_devuelve_base_vacio(tmp_path: Path) -> None:
    """Si el XML no esta, ``base={}`` y ``missing_xml=True``."""
    xml_path = tmp_path / "no_existe.xml"

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[_disp(0, "ED_000"), _disp(1, "ED_001")],
        xml_path=xml_path,
    )

    assert diff.base == {}
    assert diff.missing_xml is True
    assert diff.added == ["0", "1"]


def test_base_con_disp_reales_y_placeholder_existente_no_genera_ops(
    tmp_path: Path,
) -> None:
    """Base=base completa con placeholder + disp reales, desired=igual
    → diff vacio (idempotencia end-to-end).
    """
    xml_path = tmp_path / "2000_Disp_ED.xml"
    _write_plc_user_constants_xml(
        xml_path,
        [
            ("ED_000", "0"),
            ("ED_001", "1"),
            ("ED_002", "2"),
            ("ED_003", "3"),
        ],
    )

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[
            _disp(0, "ED_000"),
            _disp(1, "ED_001"),
            _disp(2, "ED_002"),
            _disp(3, "ED_003"),
        ],
        xml_path=xml_path,
    )

    assert diff.is_empty is True
    assert diff.n_total_changes == 0


def test_base_con_placeholder_y_deseado_solo_placeholder_marca_remove_disp(
    tmp_path: Path,
) -> None:
    """Caso real del bug: base tiene placeholder+5 disp, desired solo
    placeholder → SOLO los 5 disp van a removed; el placeholder NO.
    """
    xml_path = tmp_path / "2000_Disp_ED.xml"
    _write_plc_user_constants_xml(
        xml_path,
        [
            ("ED_000", "0"),
            ("ED_001", "1"),
            ("ED_002", "2"),
            ("ED_003", "3"),
            ("ED_004", "4"),
            ("ED_005", "5"),
        ],
    )

    diff = compute_diff_table(
        table_name="2000_Disp_ED",
        desired_devices=[_disp(0, "ED_000")],
        xml_path=xml_path,
    )

    assert diff.added == []
    assert diff.renamed == {}
    assert diff.removed == ["1", "2", "3", "4", "5"]
    # El placeholder NO esta en removed (es lo que arregla el bug).
    assert "0" not in diff.removed