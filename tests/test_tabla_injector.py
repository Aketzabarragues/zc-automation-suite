"""Tests para ``TagTableValueInjector`` (inyector de ``<Value>`` en PlcTagTable).

Estos tests son OFFLINE: no requieren TIA Portal. Crean un PlcTagTable.xml
de fixture en un directorio temporal y verifican que el injector:
  - Localiza correctamente el archivo PlcTagTable.
  - Sobreescribe los ``<Value>`` de las constantes indicadas.
  - Es idempotente (segunda ejecución no cambia nada).
  - NO toca ``<Name>``, ``<ID>``, ``<CompositionName>``.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from infrastructure.xml.tabla_injector import TagTableValueInjector


_PLC_TAG_TABLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<SW.Tags.PlcTagTable CompositionName="UserConstants">
  <AttributeList>
    <Name>000_Config_Dispositivos</Name>
  </AttributeList>
  <ObjectList>
    <SW.Tags.PlcUserConstant ID="1" CompositionName="UserConstants">
      <AttributeList>
        <Name>N_MAX_DISP_ED</Name>
        <DataTypeName>Int</DataTypeName>
        <Value>25</Value>
      </AttributeList>
    </SW.Tags.PlcUserConstant>
    <SW.Tags.PlcUserConstant ID="2" CompositionName="UserConstants">
      <AttributeList>
        <Name>N_MAX_DISP_EA</Name>
        <DataTypeName>Int</DataTypeName>
        <Value>10</Value>
      </AttributeList>
    </SW.Tags.PlcUserConstant>
  </ObjectList>
</SW.Tags.PlcTagTable>
"""


@pytest.fixture
def build_dir(tmp_path: Path) -> Path:
    """Crea un .build/ temporal con un PlcTagTable.xml de fixture."""
    tabla_path = tmp_path / "000_Config_Dispositivos.xml"
    tabla_path.write_text(_PLC_TAG_TABLE_XML, encoding="utf-8")
    return tmp_path


def test_inject_modifies_existing_value(build_dir: Path) -> None:
    """El injector debe sobreescribir el <Value> de constantes existentes."""
    result = TagTableValueInjector.inject_into_build(
        ruta_build=build_dir,
        constants={"N_MAX_DISP_ED": 30},
    )
    assert result is True

    new_content = (build_dir / "000_Config_Dispositivos.xml").read_text(
        encoding="utf-8"
    )
    assert "<Value>30</Value>" in new_content
    assert "<Value>25</Value>" not in new_content
    # El nombre no debe cambiarse.
    assert "<Name>N_MAX_DISP_ED</Name>" in new_content
    # El ID no debe cambiarse.
    assert 'ID="1"' in new_content


def test_inject_is_idempotent(build_dir: Path) -> None:
    """Una segunda invocación con los mismos valores NO debe reportar cambios."""
    TagTableValueInjector.inject_into_build(
        ruta_build=build_dir,
        constants={"N_MAX_DISP_ED": 30},
    )
    # Segunda invocación con el mismo valor -> debe ser idempotente.
    second_result = TagTableValueInjector.inject_into_build(
        ruta_build=build_dir,
        constants={"N_MAX_DISP_ED": 30},
    )
    assert second_result is False  # 0 cambios


def test_inject_skips_unknown_constant(build_dir: Path) -> None:
    """Si la constante no existe en TIA, se omite sin error."""
    result = TagTableValueInjector.inject_into_build(
        ruta_build=build_dir,
        constants={"N_MAX_INEXISTENTE": 99},
    )
    # No debe haber cambios en el archivo.
    assert result is False
    new_content = (build_dir / "000_Config_Dispositivos.xml").read_text(
        encoding="utf-8"
    )
    assert "<Value>99</Value>" not in new_content


def test_inject_multiple_constants(build_dir: Path) -> None:
    """El injector debe procesar múltiples constantes en una sola llamada."""
    result = TagTableValueInjector.inject_into_build(
        ruta_build=build_dir,
        constants={
            "N_MAX_DISP_ED": 50,
            "N_MAX_DISP_EA": 20,
        },
    )
    assert result is True

    new_content = (build_dir / "000_Config_Dispositivos.xml").read_text(
        encoding="utf-8"
    )
    assert "<Value>50</Value>" in new_content
    assert "<Value>20</Value>" in new_content
    assert "<Value>25</Value>" not in new_content
    assert "<Value>10</Value>" not in new_content


def test_inject_build_dir_not_found() -> None:
    """Si el directorio no existe, retorna False sin lanzar excepción."""
    result = TagTableValueInjector.inject_into_build(
        ruta_build="/path/que/no/existe/12345",
        constants={"X": 1},
    )
    assert result is False


def test_inject_into_file_directly(tmp_path: Path) -> None:
    """``inject_into_file`` debe aceptar una ruta directa al XML."""
    xml_path = tmp_path / "mi_tabla.xml"
    xml_path.write_text(_PLC_TAG_TABLE_XML, encoding="utf-8")

    result = TagTableValueInjector.inject_into_file(
        xml_path=xml_path,
        constants={"N_MAX_DISP_ED": 99},
    )
    assert result is True
    new_content = xml_path.read_text(encoding="utf-8")
    assert "<Value>99</Value>" in new_content
