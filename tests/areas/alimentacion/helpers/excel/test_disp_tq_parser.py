"""Tests del ``DispTQParser`` (Tanques / sensor analogico de nivel).

Cubre la extraccion de ``Tabla_Disp_TQ`` (hoja ``DISP_TQ``) y la
construccion de ``DispTQ``. Sigue el patron de los tests de los
parsers existentes (no usa el helper compartido porque ``TQ`` no
esta registrado ahi todavia: este test vive solo en su archivo).

Convenciones:
    * Cabeceras literales del Excel (con puntos y mayusculas).
    * Las filas sin UID ni Numero se descartan (criterio legacy).
    * Las filas invalidas se descartan con WARNING sin romper la tabla.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from areas.alimentacion.data.data_dispositivos import DispTQ
from areas.alimentacion.helpers.excel.excel_parser_disp_tq import DispTQParser


CABECERAS_TQ: list[str] = [
    "UID", "Numero", "PLC.Tag", "PLC.Comentario", "Descripcion",
    "Tag", "FAT", "Observaciones", "PLC.Tipo", "PLC.Index",
    "Hmi.Index", "Hmi.Texto", "Cfg.Habilitar", "ComentarioDB",
]


def _save_xlsx_tq(
    tmp_path,
    rows: list[list],
    *,
    sheet_name: str = "DISP_TQ",
    table_name: str = "Tabla_Disp_TQ",
    headers: list[str] | None = None,
) -> str:
    """Crea un .xlsx sintetico con la ``Tabla_Disp_TQ``."""
    if headers is None:
        headers = list(CABECERAS_TQ)
    if "PLC" not in headers:
        headers = ["PLC"] + list(headers)
        rows = [["PLC1"] + list(r) for r in rows]
    xlsx_path = tmp_path / f"{table_name}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    last_col_letter = chr(ord("A") + len(headers) - 1)
    last_row = 1 + len(rows)
    ref = f"A1:{last_col_letter}{last_row}"
    table = Table(displayName=table_name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showFirstColumn=False,
        showLastColumn=False, showRowStripes=True, showColumnStripes=False,
    )
    ws.add_table(table)
    wb.save(str(xlsx_path))
    return str(xlsx_path)


def _build_row_tq(
    *,
    uid: str = "TQ_001",
    numero: int = 1,
) -> list:
    """Devuelve una fila valida para la Tabla_Disp_TQ con los 14 campos."""
    return [
        uid,                              # UID
        numero,                           # Numero
        f"V_TQ_{numero:03d}",             # PLC.Tag
        f"Comentario TQ {numero}",        # PLC.Comentario
        f"Tanque {numero}",               # Descripcion
        f"T_TQ_{numero:03d}",             # Tag
        f"F_TQ_{numero:03d}",             # FAT
        "Obs",                            # Observaciones
        "Real",                           # PLC.Tipo
        0,                                # PLC.Index
        numero,                           # Hmi.Index
        f"Texto HMI TQ {numero}",         # Hmi.Texto
        "cfg_hab := 1;",                  # Cfg.Habilitar
        f"DB TQ {numero} comentario",     # ComentarioDB
    ]


# ── Tests ──────────────────────────────────────────────────────────────


def test_extrae_disp_tq_basico(tmp_path) -> None:
    """Excel con 1 fila valida -> ``DispTQ`` con todos los campos."""
    xlsx_path = _save_xlsx_tq(tmp_path, rows=[_build_row_tq()])
    wb = load_workbook(xlsx_path)

    result = DispTQParser().extraer(wb)

    assert len(result) == 1
    d = result[0]
    assert isinstance(d, DispTQ)
    assert d.uid == "TQ_001"
    assert d.numero == 1
    assert d.plc_tag == "V_TQ_001"
    assert d.plc_comentario == "Comentario TQ 1"
    assert d.descripcion == "Tanque 1"
    assert d.tag == "T_TQ_001"
    assert d.fat == "F_TQ_001"
    assert d.observaciones == "Obs"
    assert d.plc_tipo == "Real"
    assert d.plc_index == 0
    assert d.hmi_index == 1
    assert d.hmi_texto == "Texto HMI TQ 1"
    assert d.cfg_habilitar == "cfg_hab := 1;"
    assert d.comentario_db == "DB TQ 1 comentario"
    assert d.plc_name == "PLC1"


def test_hoja_inexistente_devuelve_lista_vacia(tmp_path) -> None:
    """Hoja ``DISP_TQ`` no existe -> ``[]`` (no lanza)."""
    xlsx_path = _save_xlsx_tq(
        tmp_path,
        rows=[_build_row_tq()],
        sheet_name="OTRA_HOJA",
    )
    wb = load_workbook(xlsx_path)
    result = DispTQParser().extraer(wb)
    assert result == []


def test_tabla_inexistente_devuelve_lista_vacia(tmp_path) -> None:
    """Hoja existe pero ``Tabla_Disp_TQ`` no -> ``[]`` (no lanza)."""
    xlsx_path = tmp_path / "otro.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "DISP_TQ"
    ws.append(["X", "Y"])
    ws.append([1, 2])
    table = Table(displayName="Tabla_Otra", ref="A1:B2")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showFirstColumn=False,
        showLastColumn=False, showRowStripes=True, showColumnStripes=False,
    )
    ws.add_table(table)
    wb.save(str(xlsx_path))

    wb2 = load_workbook(xlsx_path)
    assert DispTQParser().extraer(wb2) == []


def test_fila_sin_uid_se_descarta(tmp_path) -> None:
    """Fila sin UID ni Numero se descarta; fila valida se conserva."""
    xlsx_path = _save_xlsx_tq(
        tmp_path,
        rows=[
            [None, None, "X", "X", "X"],   # sin UID ni Numero
            _build_row_tq(uid="TQ_002"),
        ],
    )
    wb = load_workbook(xlsx_path)
    result = DispTQParser().extraer(wb)
    assert len(result) == 1
    assert result[0].uid == "TQ_002"


def test_multiples_filas_validas(tmp_path) -> None:
    """Varias filas validas -> lista de multiples ``DispTQ``."""
    rows = [
        _build_row_tq(uid="TQ_001", numero=1),
        _build_row_tq(uid="TQ_002", numero=2),
        _build_row_tq(uid="TQ_003", numero=3),
    ]
    xlsx_path = _save_xlsx_tq(tmp_path, rows=rows)
    wb = load_workbook(xlsx_path)

    result = DispTQParser().extraer(wb)

    assert len(result) == 3
    assert [d.uid for d in result] == ["TQ_001", "TQ_002", "TQ_003"]
    assert [d.numero for d in result] == [1, 2, 3]


def test_defaults_when_only_uid_and_numero(tmp_path) -> None:
    """Sin columnas especificas -> defaults tolerantes."""
    xlsx_path = _save_xlsx_tq(
        tmp_path,
        rows=[["TQ_001", 1, "V_TQ_001", "c", "d"]],
        headers=["UID", "Numero", "PLC.Tag", "PLC.Comentario", "Descripcion"],
    )
    wb = load_workbook(xlsx_path)
    result = DispTQParser().extraer(wb)
    assert len(result) == 1
    d = result[0]
    assert d.tag == ""
    assert d.fat == ""
    assert d.observaciones == ""
    assert d.cfg_habilitar == ""
    assert d.comentario_db == ""


def test_log_debug_contiene_sheet_y_count(tmp_path, caplog) -> None:
    """El log de debug lleva el formato ``Parser[<sheet>/<table>]: N -> M``."""
    rows = [
        _build_row_tq(uid="TQ_001", numero=1),
        _build_row_tq(uid="TQ_002", numero=2),
    ]
    xlsx_path = _save_xlsx_tq(tmp_path, rows=rows)
    wb = load_workbook(xlsx_path)

    with caplog.at_level(logging.DEBUG, logger="areas.alimentacion.helpers.excel.excel_parser_disp_tq"):
        result = DispTQParser().extraer(wb)

    assert len(result) == 2
    debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("Parser[DISP_TQ/Tabla_Disp_TQ]" in m for m in debug_msgs), (
        f"No se encontro el log 'Parser[DISP_TQ/Tabla_Disp_TQ]:' en: {debug_msgs}"
    )
    assert any("2 filas -> 2 extraidas" in m for m in debug_msgs), (
        f"No se encontro el conteo esperado: 2 -> 2 en {debug_msgs}"
    )
