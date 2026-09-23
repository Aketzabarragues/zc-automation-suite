"""Tests del ``DimensionesParser``.

Cobertura:
  - Extraccion basica de ``N_MAX_DISP_X`` (canonico TIA).
  - Title Case ``Num_Disp_X`` se traduce al canonico.
  - lowercase ``num_disp_x`` legacy se traduce al canonico.
  - Defined names con prefijos invalidos se ignoran.
  - Workbook sin ``defined_names`` devuelve instancia con extras vacios.
  - Con ``ConfigManager``, el mapeo es data-driven.
  - Excel del operario (mezcla de los 3 prefijos) -> todos canonicos.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName

from areas.alimentacion.data.data_Dimensiones import DimensionesDispositivos
from areas.alimentacion.helpers.excel.excel_parser_disp_dimensiones import DimensionesParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path) -> Path:
    """Escribe un config.json minimo con n_max_catalog de 6 hw_types."""
    cfg: dict[str, Any] = {
        "departments": {
            "alimentacion": {
                "global_config_table_name": "000_Config_Dispositivos",
                "tia_folders": {
                    "proceso":      "003_Procesos",
                    "dispositivos": "2000_Dispositivos",
                    "nmax":         "000_Sistema",
                },
                "n_max_catalog": [
                    {"name": "N_MAX_DISP_ED",   "hw_type": "ed"},
                    {"name": "N_MAX_DISP_EA",   "hw_type": "ea"},
                    {"name": "N_MAX_DISP_SA",   "hw_type": "sa"},
                    {"name": "N_MAX_DISP_V",    "hw_type": "v"},
                    {"name": "N_MAX_DISP_M",    "hw_type": "m"},
                    {"name": "N_MAX_DISP_M_VF", "hw_type": "m_vf"},
                ],
            }
        }
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def _add_named_value(
    wb: Workbook,
    sheet_name: str,
    cell: str,
    name: str,
    value: Any,
) -> None:
    """Anade un defined name que apunta a ``sheet!cell`` con ``value``."""
    if sheet_name not in wb.sheetnames:
        ws = wb.create_sheet(sheet_name)
    else:
        ws = wb[sheet_name]
    ws[cell] = value
    dn = DefinedName(name=name, attr_text=f"'{sheet_name}'!${cell}")
    wb.defined_names[name] = dn


# ---------------------------------------------------------------------------
# Tests de extraccion basica (canonico TIA, ``N_MAX_DISP_*``)
# ---------------------------------------------------------------------------


def test_extrae_canonicos_basicos():
    """Excel con 6 defined names ``N_MAX_DISP_X`` -> extras canonicos."""
    wb = Workbook()
    wb.remove(wb.active)
    values = [("ED", 10, "A1"), ("EA", 20, "A2"), ("SA", 30, "A3"),
              ("V", 40, "A4"), ("M", 50, "A5"), ("M_VF", 60, "A6")]
    for hw, val, cell in values:
        _add_named_value(wb, "Config", cell, f"N_MAX_DISP_{hw}", val)

    d = DimensionesParser().extraer(wb)
    assert isinstance(d, DimensionesDispositivos)
    assert d.extras == {
        "N_MAX_DISP_ED": 10,
        "N_MAX_DISP_EA": 20,
        "N_MAX_DISP_SA": 30,
        "N_MAX_DISP_V": 40,
        "N_MAX_DISP_M": 50,
        "N_MAX_DISP_M_VF": 60,
    }


def test_falta_canonico_aparece_en_extras():
    """Solo 2 definidos -> los otros 4 quedan fuera del extras (no son 0)."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_named_value(wb, "Config", "A1", "N_MAX_DISP_ED", 7)
    _add_named_value(wb, "Config", "A2", "N_MAX_DISP_V", 8)

    d = DimensionesParser().extraer(wb)
    assert d.extras == {"N_MAX_DISP_ED": 7, "N_MAX_DISP_V": 8}


# ---------------------------------------------------------------------------
# Tests de Title Case y lowercase legacy
# ---------------------------------------------------------------------------


def test_title_case_se_traduce_a_canonico():
    """``Num_Disp_X`` (Title Case del Excel del operario) -> ``N_MAX_DISP_X``."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_named_value(wb, "Config", "A1", "Num_Disp_ED", 21)
    _add_named_value(wb, "Config", "A2", "Num_Disp_M_SINA", 50)

    d = DimensionesParser().extraer(wb)
    assert d.extras == {
        "N_MAX_DISP_ED": 21,
    }
    # ``Num_Disp_M_SINA`` no esta en el fallback de 6 hw_types -> se descarta.
    assert "N_MAX_DISP_M_SINA" not in d.extras


def test_lowercase_legacy_se_traduce_a_canonico():
    """``num_disp_x`` (lowercase legacy) -> ``N_MAX_DISP_X``."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_named_value(wb, "Config", "A1", "num_disp_ed", 5)

    d = DimensionesParser().extraer(wb)
    assert d.extras == {"N_MAX_DISP_ED": 5}


def test_excel_operario_mezcla_3_prefijo_todo_canonico():
    """Mezcla de los 3 prefijos en un mismo Excel -> todos canonicos."""
    wb = Workbook()
    wb.remove(wb.active)
    # Hoja de definicion: canonico TIA.
    _add_named_value(wb, "Definicion", "A1", "N_MAX_DISP_ED", 10)
    # Hoja de configuracion: Title Case corporativo.
    _add_named_value(wb, "Configuracion", "A1", "Num_Disp_EA", 20)
    # Legacy lowercase.
    _add_named_value(wb, "Legacy", "A1", "num_disp_v", 30)

    d = DimensionesParser().extraer(wb)
    assert d.extras == {
        "N_MAX_DISP_ED": 10,
        "N_MAX_DISP_EA": 20,
        "N_MAX_DISP_V": 30,
    }


# ---------------------------------------------------------------------------
# Tests defensivos
# ---------------------------------------------------------------------------


def test_prefijo_invalido_se_ignora():
    """Defined names que NO empiezan por prefijo valido se ignoran."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_named_value(wb, "Config", "A1", "N_MAX_DISP_ED", 5)
    _add_named_value(wb, "Config", "A2", "OTRA_COSA", 999)
    _add_named_value(wb, "Config", "A3", "Empresa", "Acme")

    d = DimensionesParser().extraer(wb)
    assert d.extras == {"N_MAX_DISP_ED": 5}


def test_workbook_sin_defined_names_devuelve_extras_vacios():
    """Workbook sin defined names -> ``DimensionesDispositivos()`` con extras vacios."""
    wb = Workbook()
    wb.remove(wb.active)
    wb.create_sheet("Config")

    d = DimensionesParser().extraer(wb)
    assert d.extras == {}


# ---------------------------------------------------------------------------
# Tests con ConfigManager
# ---------------------------------------------------------------------------


def test_with_config_manager_resuelve_data_driven(tmp_path):
    """Con ``ConfigManager``, las entradas del catalogo se resuelven."""
    from core.infrastructure.config.config_manager import ConfigManager

    config_path = _write_config(tmp_path)
    cm = ConfigManager(config_path=config_path)

    wb = Workbook()
    wb.remove(wb.active)
    _add_named_value(wb, "Config", "A1", "N_MAX_DISP_ED", 11)
    _add_named_value(wb, "Config", "A2", "N_MAX_DISP_V", 33)

    d = DimensionesParser(config_manager=cm).extraer(wb)
    assert d.extras == {"N_MAX_DISP_ED": 11, "N_MAX_DISP_V": 33}
