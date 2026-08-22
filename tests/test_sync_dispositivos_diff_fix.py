"""Tests del fix de diff por VALOR (PlcUserConstant)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from application.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)


def _write_plc_user_constants_xml(
    xml_path: Path,
    constants: list[tuple[str, str]],
) -> None:
    """Escribe un PlcTagTable XML con PlcUserConstant."""
    root = ET.Element("SW.Tags.PlcTagTable")
    al = ET.SubElement(root, "AttributeList")
    ET.SubElement(al, "Name").text = xml_path.stem
    ol = ET.SubElement(root, "ObjectList")
    for value, name in constants:
        const = ET.SubElement(
            ol, "SW.Tags.PlcUserConstant", {"ID": name}
        )
        attr_list = ET.SubElement(const, "AttributeList")
        ET.SubElement(attr_list, "Name").text = name
        ET.SubElement(attr_list, "DataTypeName").text = "Int"
        ET.SubElement(attr_list, "Value").text = value
    ET.ElementTree(root).write(
        str(xml_path), encoding="utf-8", xml_declaration=True
    )


def test_diff_no_false_adds_when_devices_exist():
    """Si el PLC tiene V_001 con Value=1 y el Excel pide V_VA_101 con numero=1,
    el diff debe generar un RENAME, no un ADD.
    """
    with TemporaryDirectory() as tmp:
        tags_base = Path(tmp) / "tags"
        tags_base.mkdir(parents=True)
        xml_path = tags_base / "2000_Disp_V.xml"
        _write_plc_user_constants_xml(
            xml_path,
            [
                ("1", "V_001"),
                ("2", "V_002"),
            ],
        )

        # desired_state: numero del Excel -> plc_tag deseado.
        desired_state = {
            "1": "V_VA_101",  # mismo numero, distinto nombre
            "2": "V_VA_102",
        }

        # Llamar directamente al método estático (sin gateway).
        added, removed, renamed, base = (
            SyncDispositivosInstancesUseCase._compute_diff_readonly(
                tags_base, desired_state
            )
        )

        assert added == [], f"No debe haber adds, pero hay: {added}"
        assert removed == [], f"No debe haber removes, pero hay: {removed}"
        assert "1" in renamed, f"Debe detectar rename del value=1: {renamed}"
        assert renamed["1"] == ("V_001", "V_VA_101")
        assert base == {"1": "V_001", "2": "V_002"}


def test_diff_empty_when_nothing_changes():
    """Si los plc_tags coinciden exactamente, NO debe haber operaciones."""
    with TemporaryDirectory() as tmp:
        tags_base = Path(tmp) / "tags"
        tags_base.mkdir(parents=True)
        xml_path = tags_base / "2000_Disp_V.xml"
        _write_plc_user_constants_xml(
            xml_path,
            [
                ("1", "V_VA_101"),
                ("2", "V_VA_102"),
            ],
        )

        desired_state = {"1": "V_VA_101", "2": "V_VA_102"}

        added, removed, renamed, base = (
            SyncDispositivosInstancesUseCase._compute_diff_readonly(
                tags_base, desired_state
            )
        )

        assert added == []
        assert removed == []
        assert renamed == {}


def test_diff_detects_added_devices():
    """Si el Excel tiene un dispositivo que el PLC no, debe detectarlo como add."""
    with TemporaryDirectory() as tmp:
        tags_base = Path(tmp) / "tags"
        tags_base.mkdir(parents=True)
        xml_path = tags_base / "2000_Disp_V.xml"
        _write_plc_user_constants_xml(
            xml_path,
            [("1", "V_001")],
        )

        desired_state = {
            "1": "V_001",
            "2": "V_VA_102",  # nuevo
        }

        added, removed, renamed, base = (
            SyncDispositivosInstancesUseCase._compute_diff_readonly(
                tags_base, desired_state
            )
        )

        assert added == ["2"]
        assert removed == []
        assert renamed == {}
