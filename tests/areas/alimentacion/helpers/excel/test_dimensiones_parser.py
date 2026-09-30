"""Tests del ``DimensionesParser`` (multi-PLC, sept-2026).

Cobertura:
  - Lectura de tabla ``Tabla_N_Max`` con columnas N_Max_<hw>.
  - Normalizacion a canonico TIA ``N_MAX_DISP_<X>``.
  - Multi-PLC: una entrada por PLC del Excel.
  - Filas sin PLC se descartan con WARNING.
  - Columnas no listadas en catalog se ignoran (modo strict).
  - Celdas vacias / no numericas -> 0 (validacion soft).
  - ConfigManager sin ``excel_column`` -> contenedor vacio.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from areas.alimentacion.data.data_dimensiones import (
    DataDimensionesPLC,
    DimensionesDispositivos,
)
from areas.alimentacion.helpers.excel.excel_parser_disp_dimensiones import (
    N_MAX_TABLE_NAME,
    DimensionesParser,
)
from core.infrastructure.config.config_manager import ConfigManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, *, with_excel_column: bool = True) -> Path:
    """Escribe un config.json minimo con n_max_catalog de 6 hw_types.

    Si ``with_excel_column`` es True, las entradas llevan el campo
    ``excel_column`` (modo strict nuevo). Si es False, lo omiten
    (modo legacy, no leemos nada).
    """
    catalog: list[dict[str, Any]] = [
        {"name": "N_MAX_DISP_ED",   "hw_type": "ed"},
        {"name": "N_MAX_DISP_EA",   "hw_type": "ea"},
        {"name": "N_MAX_DISP_SA",   "hw_type": "sa"},
        {"name": "N_MAX_DISP_V",    "hw_type": "v"},
        {"name": "N_MAX_DISP_M",    "hw_type": "m"},
        {"name": "N_MAX_DISP_M_VF", "hw_type": "m_vf"},
    ]
    if with_excel_column:
        for e in catalog:
            e["excel_column"] = f"N_Max_{e['hw_type'].upper()}"
    cfg: dict[str, Any] = {
        "departments": {
            "alimentacion": {
                "global_config_table_name": "Config",
                "n_max_catalog": catalog,
            }
        }
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def _config_manager_for_tests(tmp_path: Path) -> ConfigManager:
    """Helper: devuelve un ConfigManager con el catalog minimo para tests."""
    return ConfigManager(config_path=_write_config(tmp_path))


def _add_n_max_table(
    wb: Workbook,
    sheet_name: str,
    rows: list[dict[str, Any]],
) -> None:
    """Anade una tabla ``Tabla_N_Max`` a la hoja con las filas dadas."""
    if sheet_name not in wb.sheetnames:
        ws = wb.create_sheet(sheet_name)
    else:
        ws = wb[sheet_name]
    # Cabecera canonica + PLC + 6 columnas.
    headers = ["PLC", "N_Max_ED", "N_Max_EA", "N_Max_SA",
               "N_Max_V", "N_Max_M", "N_Max_M_VF"]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    # Registrar la ListObject.
    last_row = ws.max_row
    last_col = ws.max_column
    from openpyxl.utils import get_column_letter
    ref = f"A1:{get_column_letter(last_col)}{last_row}"
    from openpyxl.worksheet.table import Table
    table = Table(displayName=N_MAX_TABLE_NAME, ref=ref)
    ws.add_table(table)


# ---------------------------------------------------------------------------
# Tests de extraccion basica
# ---------------------------------------------------------------------------


def test_extrae_una_fila_por_plc(tmp_path):
    """Tabla con 2 PLCs -> DimensionesDispositivos con 2 DataDimensionesPLC."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "Config", [
        {"PLC": "PLC1", "N_Max_ED": 10, "N_Max_EA": 20, "N_Max_SA": 30,
         "N_Max_V": 40, "N_Max_M": 50, "N_Max_M_VF": 60},
        {"PLC": "PLC2", "N_Max_ED": 100, "N_Max_EA": 200, "N_Max_SA": 300,
         "N_Max_V": 400, "N_Max_M": 500, "N_Max_M_VF": 600},
    ])

    cm = _config_manager_for_tests(tmp_path)
    p_out = DimensionesParser(config_manager=cm).extraer(wb)
    assert isinstance(p_out, DimensionesDispositivos)
    assert len(p_out.por_plc) == 2

    plc1 = p_out.get_for_plc("PLC1")
    assert plc1 is not None
    assert plc1.get("N_MAX_DISP_ED") == 10
    assert plc1.get("N_MAX_DISP_M_VF") == 60

    plc2 = p_out.get_for_plc("PLC2")
    assert plc2 is not None
    assert plc2.get("N_MAX_DISP_ED") == 100


def test_normaliza_sufijo_a_canonico(tmp_path):
    """``N_Max_Ed`` (mixed case) -> ``N_MAX_DISP_ED`` (upper)."""
    wb = Workbook()
    wb.remove(wb.active)
    # Forzamos cabecera con casing mezclado modificando el helper.
    ws = wb.create_sheet("Config")
    ws.append(["PLC", "N_Max_Ed"])
    ws.append(["PLC1", 32])
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table
    ws.add_table(Table(displayName=N_MAX_TABLE_NAME, ref="A1:B2"))

    cm = _config_manager_for_tests(tmp_path)
    p_out = DimensionesParser(config_manager=cm).extraer(wb)
    plc1 = p_out.get_for_plc("PLC1")
    assert plc1 is not None
    assert plc1.get("N_MAX_DISP_ED") == 32


def test_fila_sin_plc_se_descarta(tmp_path):
    """Fila con PLC vacio -> descartada con WARNING."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "Config", [
        {"PLC": "PLC1", "N_Max_ED": 10, "N_Max_EA": 0, "N_Max_SA": 0,
         "N_Max_V": 0, "N_Max_M": 0, "N_Max_M_VF": 0},
        {"PLC": "", "N_Max_ED": 99, "N_Max_EA": 0, "N_Max_SA": 0,
         "N_Max_V": 0, "N_Max_M": 0, "N_Max_M_VF": 0},
    ])
    cm = _config_manager_for_tests(tmp_path)
    p_out = DimensionesParser(config_manager=cm).extraer(wb)
    assert len(p_out.por_plc) == 1
    assert p_out.get_for_plc("PLC1") is not None


def test_celda_vacia_o_no_numerica_es_cero(tmp_path):
    """Celdas vacias o no numericas -> 0 (validacion soft, sin error)."""
    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Config")
    ws.append(["PLC", "N_Max_ED", "N_Max_EA"])
    ws.append(["PLC1", "abc", None])
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table
    ws.add_table(Table(displayName=N_MAX_TABLE_NAME, ref="A1:C2"))

    cm = _config_manager_for_tests(tmp_path)
    p_out = DimensionesParser(config_manager=cm).extraer(wb)
    plc1 = p_out.get_for_plc("PLC1")
    assert plc1 is not None
    assert plc1.get("N_MAX_DISP_ED") == 0
    assert plc1.get("N_MAX_DISP_EA") == 0


def test_tabla_inexistente_devuelve_contenedor_vacio(tmp_path):
    """Workbook sin Tabla_N_Max -> ``DimensionesDispositivos()`` con por_plc vacio."""
    wb = Workbook()
    wb.remove(wb.active)
    wb.create_sheet("Config")

    cm = _config_manager_for_tests(tmp_path)
    p_out = DimensionesParser(config_manager=cm).extraer(wb)
    assert isinstance(p_out, DimensionesDispositivos)
    assert p_out.por_plc == ()


# ---------------------------------------------------------------------------
# Tests con ConfigManager
# ---------------------------------------------------------------------------


def test_with_config_manager_excel_column(tmp_path):
    """Con CM, lee solo las columnas listadas en excel_column."""
    config_path = _write_config(tmp_path, with_excel_column=True)
    cm = ConfigManager(config_path=config_path)

    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "Config", [
        {"PLC": "PLC1", "N_Max_ED": 11, "N_Max_EA": 22, "N_Max_SA": 33,
         "N_Max_V": 44, "N_Max_M": 55, "N_Max_M_VF": 66},
    ])

    p_out = DimensionesParser(config_manager=cm).extraer(wb)
    plc1 = p_out.get_for_plc("PLC1")
    assert plc1 is not None
    assert plc1.get("N_MAX_DISP_ED") == 11
    assert plc1.get("N_MAX_DISP_M_VF") == 66


def test_with_config_manager_sin_excel_column_devuelve_vacio(tmp_path):
    """Sin ``excel_column`` en el catalog, modo strict = nada se lee."""
    config_path = _write_config(tmp_path, with_excel_column=False)
    cm = ConfigManager(config_path=config_path)

    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "Config", [
        {"PLC": "PLC1", "N_Max_ED": 11, "N_Max_EA": 22},
    ])

    p_out = DimensionesParser(config_manager=cm).extraer(wb)
    # Sin excel_column no leemos nada -> contenedor vacio.
    assert p_out.por_plc == ()


def test_to_api_dict_shape_anidado(tmp_path):
    """``to_api_dict()`` retorna ``{plc_name: {nmax: int}}``.

    Las 6 columnas del catalog se incluyen: las presentes en el Excel
    con su valor, las ausentes con 0 (validacion soft).
    """
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "Config", [
        {"PLC": "PLC1", "N_Max_ED": 10},
        {"PLC": "PLC2", "N_Max_ED": 20},
    ])
    cm = _config_manager_for_tests(tmp_path)
    p_out = DimensionesParser(config_manager=cm).extraer(wb)
    api = p_out.to_api_dict()
    assert api["PLC1"]["N_MAX_DISP_ED"] == 10
    assert api["PLC1"]["N_MAX_DISP_EA"] == 0  # columna ausente -> 0
    assert api["PLC2"]["N_MAX_DISP_ED"] == 20
    assert api["PLC2"]["N_MAX_DISP_EA"] == 0


def test_data_dimensiones_plc_inmutable():
    """``DataDimensionesPLC`` y ``DimensionesDispositivos`` son frozen."""
    from dataclasses import FrozenInstanceError
    p = DataDimensionesPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 5})
    with pytest.raises(FrozenInstanceError):
        p.plc_name = "PLC2"  # type: ignore[misc]


import pytest