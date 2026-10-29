"""Tests del ``PLCListParser`` (Tabla_PLC del Excel, multi-PLC)."""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from areas.alimentacion.data.data_plc import DataPLC
from areas.alimentacion.helpers.excel.excel_parser_plc import PLCListParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_plc_table(
    wb: Workbook,
    sheet_name: str,
    rows: list[tuple],
) -> None:
    """Anade una ``Tabla_PLC`` a la hoja ``sheet_name`` con las filas dadas."""
    if sheet_name not in wb.sheetnames:
        ws = wb.create_sheet(sheet_name)
    else:
        ws = wb[sheet_name]
    headers = ["UID", "PLC"]
    ws.append(headers)
    for uid, plc in rows:
        ws.append([uid, plc])
    last_col_letter = chr(ord("A") + len(headers) - 1)
    last_row = ws.max_row
    ref = f"A1:{last_col_letter}{last_row}"
    table = Table(displayName="Tabla_PLC", ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showFirstColumn=False,
        showLastColumn=False, showRowStripes=True, showColumnStripes=False,
    )
    ws.add_table(table)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extrae_una_fila_por_plc():
    """Tabla con 3 PLCs -> lista de 3 DataPLC."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_plc_table(wb, "CONFIG", [
        (1, "PLC1"),
        (2, "PLC2"),
        (3, "PLC3"),
    ])
    result = PLCListParser().extraer(wb)
    assert len(result) == 3
    assert all(isinstance(p, DataPLC) for p in result)
    assert result[0].plc == "PLC1"
    assert result[2].uid == 3


def test_tabla_vacia_devuelve_lista_vacia():
    """Workbook sin Tabla_PLC -> []."""
    wb = Workbook()
    wb.remove(wb.active)
    wb.create_sheet("CONFIG")
    result = PLCListParser().extraer(wb)
    assert result == []


def test_fila_sin_plc_se_descarta():
    """Fila con PLC vacio -> descartada con WARNING."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_plc_table(wb, "CONFIG", [
        (1, "PLC1"),
        (2, ""),
    ])
    result = PLCListParser().extraer(wb)
    assert len(result) == 1
    assert result[0].plc == "PLC1"


def test_fila_sin_uid_se_descarta():
    """Fila con UID vacio -> descartada silenciosamente."""
    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("CONFIG")
    ws.append(["UID", "PLC"])
    ws.append([1, "PLC1"])
    ws.append([None, "PLC2"])  # UID vacio
    last_col_letter = "B"
    last_row = ws.max_row
    table = Table(displayName="Tabla_PLC", ref=f"A1:{last_col_letter}{last_row}")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showFirstColumn=False,
        showLastColumn=False, showRowStripes=True, showColumnStripes=False,
    )
    ws.add_table(table)
    result = PLCListParser().extraer(wb)
    assert len(result) == 1
    assert result[0].uid == 1


def test_uid_cero_es_valido():
    """uid=0 explicito se conserva (no es filtrado)."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_plc_table(wb, "CONFIG", [
        (0, "PLC_legacy"),
        (1, "PLC1"),
    ])
    result = PLCListParser().extraer(wb)
    assert len(result) == 2
    assert result[0].uid == 0
    assert result[0].plc == "PLC_legacy"


def test_nombre_clase_y_constantes():
    """Las constantes de la clase son correctas."""
    assert PLCListParser.SHEET == "CONFIG"
    assert PLCListParser.TABLE == "Tabla_PLC"