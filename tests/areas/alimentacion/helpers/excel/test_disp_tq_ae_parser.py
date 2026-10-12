"""Tests del ``DispTQ_AEParser`` (Tanques Aire Esteril).

Cubre la extraccion de ``Tabla_Disp_TQ_AE`` (hoja ``DISP_TQ_AE``) y
la construccion de ``DispTQ_AE``. Sigue el patron de los tests de
los parsers existentes (no usa el helper compartido porque
``TQ_AE`` no esta registrado ahi todavia: este test vive solo en
su archivo).

Convenciones:
    * Cabeceras literales del Excel (con puntos y mayusculas).
    * Las filas sin UID ni Numero se descartan (criterio legacy).
    * Las filas invalidas se descartan con WARNING sin romper la tabla.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from areas.alimentacion.data.data_dispositivos import DispTQ_AE
from areas.alimentacion.helpers.excel.excel_parser_disp_tq_ae import (
    DispTQ_AEParser,
)
from core.infrastructure.config.config_manager import ConfigManager


CABECERAS_TQ_AE: list[str] = [
    "UID", "Numero", "PLC.Tag", "PLC.Comentario", "Descripcion",
    "Tag", "FAT", "Observaciones", "PLC.Tipo", "PLC.Index",
    "Hmi.Index", "Hmi.Texto", "Cfg.Habilitar", "ComentarioDB",
]


def _save_xlsx_tq_ae(
    tmp_path,
    rows: list[list],
    *,
    sheet_name: str = "DISP_TQ_AE",
    table_name: str = "Tabla_Disp_TQ_AE",
    headers: list[str] | None = None,
) -> str:
    """Crea un .xlsx sintetico con la ``Tabla_Disp_TQ_AE``."""
    if headers is None:
        headers = list(CABECERAS_TQ_AE)
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


def _build_row_tq_ae(
    *,
    uid: str = "TQ_AE_001",
    numero: int = 1,
) -> list:
    """Devuelve una fila valida para la Tabla_Disp_TQ_AE con los 14 campos."""
    return [
        uid,                                  # UID
        numero,                               # Numero
        f"V_TQ_AE_{numero:03d}",              # PLC.Tag
        f"Comentario TQ_AE {numero}",         # PLC.Comentario
        f"Tanque aire esteril {numero}",      # Descripcion
        f"T_TQ_AE_{numero:03d}",              # Tag
        f"F_TQ_AE_{numero:03d}",              # FAT
        "AE_obs",                             # Observaciones
        "Real",                               # PLC.Tipo
        0,                                    # PLC.Index
        numero,                               # Hmi.Index
        f"Texto HMI TQ_AE {numero}",          # Hmi.Texto
        "cfg_hab := 1;",                      # Cfg.Habilitar
        f"DB TQ_AE {numero} comentario",      # ComentarioDB
    ]


# ── Tests ──────────────────────────────────────────────────────────────


def test_extrae_disp_tq_ae_basico(tmp_path) -> None:
    """Excel con 1 fila valida -> ``DispTQ_AE`` con todos los campos."""
    xlsx_path = _save_xlsx_tq_ae(tmp_path, rows=[_build_row_tq_ae()])
    wb = load_workbook(xlsx_path)

    result = DispTQ_AEParser().extraer(wb)

    assert len(result) == 1
    d = result[0]
    assert isinstance(d, DispTQ_AE)
    assert d.uid == "TQ_AE_001"
    assert d.numero == 1
    assert d.plc_tag == "V_TQ_AE_001"
    assert d.plc_comentario == "Comentario TQ_AE 1"
    assert d.descripcion == "Tanque aire esteril 1"
    assert d.tag == "T_TQ_AE_001"
    assert d.fat == "F_TQ_AE_001"
    assert d.observaciones == "AE_obs"
    assert d.plc_tipo == "Real"
    assert d.plc_index == 0
    assert d.hmi_index == 1
    assert d.hmi_texto == "Texto HMI TQ_AE 1"
    assert d.cfg_habilitar == "cfg_hab := 1;"
    assert d.comentario_db == "DB TQ_AE 1 comentario"
    assert d.plc_name == "PLC1"


def test_hoja_inexistente_devuelve_lista_vacia(tmp_path) -> None:
    """Hoja ``DISP_TQ_AE`` no existe -> ``[]`` (no lanza)."""
    xlsx_path = _save_xlsx_tq_ae(
        tmp_path,
        rows=[_build_row_tq_ae()],
        sheet_name="OTRA_HOJA",
    )
    wb = load_workbook(xlsx_path)
    result = DispTQ_AEParser().extraer(wb)
    assert result == []


def test_tabla_inexistente_devuelve_lista_vacia(tmp_path) -> None:
    """Hoja existe pero ``Tabla_Disp_TQ_AE`` no -> ``[]`` (no lanza)."""
    xlsx_path = tmp_path / "otro.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "DISP_TQ_AE"
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
    assert DispTQ_AEParser().extraer(wb2) == []


def test_fila_sin_uid_se_descarta(tmp_path) -> None:
    """Fila sin UID ni Numero se descarta; fila valida se conserva."""
    xlsx_path = _save_xlsx_tq_ae(
        tmp_path,
        rows=[
            [None, None, "X", "X", "X"],   # sin UID ni Numero
            _build_row_tq_ae(uid="TQ_AE_002"),
        ],
    )
    wb = load_workbook(xlsx_path)
    result = DispTQ_AEParser().extraer(wb)
    assert len(result) == 1
    assert result[0].uid == "TQ_AE_002"


def test_multiples_filas_validas(tmp_path) -> None:
    """Varias filas validas -> lista de multiples ``DispTQ_AE``."""
    rows = [
        _build_row_tq_ae(uid="TQ_AE_001", numero=1),
        _build_row_tq_ae(uid="TQ_AE_002", numero=2),
        _build_row_tq_ae(uid="TQ_AE_003", numero=3),
    ]
    xlsx_path = _save_xlsx_tq_ae(tmp_path, rows=rows)
    wb = load_workbook(xlsx_path)

    result = DispTQ_AEParser().extraer(wb)

    assert len(result) == 3
    assert [d.uid for d in result] == ["TQ_AE_001", "TQ_AE_002", "TQ_AE_003"]
    assert [d.numero for d in result] == [1, 2, 3]


def test_defaults_when_only_uid_and_numero(tmp_path) -> None:
    """Sin columnas especificas -> defaults tolerantes."""
    xlsx_path = _save_xlsx_tq_ae(
        tmp_path,
        rows=[["TQ_AE_001", 1, "V_TQ_AE_001", "c", "d"]],
        headers=["UID", "Numero", "PLC.Tag", "PLC.Comentario", "Descripcion"],
    )
    wb = load_workbook(xlsx_path)
    result = DispTQ_AEParser().extraer(wb)
    assert len(result) == 1
    d = result[0]
    assert d.tag == ""
    assert d.fat == ""
    assert d.observaciones == ""
    assert d.cfg_habilitar == ""
    assert d.comentario_db == ""


def test_parser_respeta_config_manager_override(tmp_path) -> None:
    """Si el config_manager sobreescribe sheet/table, el parser lo respeta."""
    cm = MagicMock(spec=ConfigManager)
    cm.get_excel_target_for.return_value = {
        "sheet": "OTRA_HOJA_TQ_AE",
        "table": "Tabla_Disp_TQ_AE_Alt",
        "canonical": "DispTQ_AE",
    }

    xlsx_path = _save_xlsx_tq_ae(
        tmp_path,
        rows=[_build_row_tq_ae(uid="TQ_AE_002")],
        sheet_name="OTRA_HOJA_TQ_AE",
        table_name="Tabla_Disp_TQ_AE_Alt",
    )
    wb = load_workbook(xlsx_path)

    parser = DispTQ_AEParser(config_manager=cm)
    assert parser.SHEET == "OTRA_HOJA_TQ_AE"
    assert parser.TABLE == "Tabla_Disp_TQ_AE_Alt"
    result = parser.extraer(wb)
    assert len(result) == 1
    assert result[0].uid == "TQ_AE_002"


def test_log_debug_contiene_sheet_y_count(tmp_path, caplog) -> None:
    """El log de debug lleva el formato ``Parser[<sheet>/<table>]: N -> M``."""
    rows = [
        _build_row_tq_ae(uid="TQ_AE_001", numero=1),
        _build_row_tq_ae(uid="TQ_AE_002", numero=2),
    ]
    xlsx_path = _save_xlsx_tq_ae(tmp_path, rows=rows)
    wb = load_workbook(xlsx_path)

    with caplog.at_level(logging.DEBUG, logger="areas.alimentacion.helpers.excel.excel_parser_disp_tq_ae"):
        result = DispTQ_AEParser().extraer(wb)

    assert len(result) == 2
    debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("Parser[DISP_TQ_AE/Tabla_Disp_TQ_AE]" in m for m in debug_msgs), (
        f"No se encontro el log 'Parser[DISP_TQ_AE/Tabla_Disp_TQ_AE]:' en: {debug_msgs}"
    )
    assert any("2 filas -> 2 extraidas" in m for m in debug_msgs), (
        f"No se encontro el conteo esperado: 2 -> 2 en {debug_msgs}"
    )
