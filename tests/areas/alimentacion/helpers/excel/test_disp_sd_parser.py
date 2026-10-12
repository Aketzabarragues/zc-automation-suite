"""Tests del ``DispSDParser`` (Salidas Digitales).

Cubre la extraccion de ``Tabla_Disp_SD`` (hoja ``DISP_SD``) y la
construccion de ``DispSD``. Sigue el patron de los tests de los
parsers existentes (no usa el helper compartido porque ``SD`` no
esta registrado ahi todavia: este test vive solo en su archivo).

Convenciones:
    * Cabeceras literales del Excel (con puntos y mayusculas).
    * Las filas sin UID ni Numero se descartan (criterio legacy).
    * Las filas invalidas se descartan con WARNING sin romper la tabla.
"""
from __future__ import annotations

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from areas.alimentacion.data.data_dispositivos import DispSD
from areas.alimentacion.helpers.excel.excel_parser_disp_sd import DispSDParser


CABECERAS_SD: list[str] = [
    "UID", "Numero", "PLC.Tag", "PLC.Comentario", "Descripcion",
    "Tag", "FAT", "S.Byte", "S.Bit", "Gr.Alarma", "Cuadro",
    "Observaciones", "PLC.Tipo", "PLC.Index", "Hmi.Index",
    "Hmi.Texto", "Cfg.Habilitar", "Cfg.ByteEntrada",
    "Cfg.BitEntrada", "Cfg.GrupoAlarma", "ComentarioDB",
]


def _save_xlsx_sd(
    tmp_path,
    rows: list[list],
    *,
    sheet_name: str = "DISP_SD",
    table_name: str = "Tabla_Disp_SD",
    headers: list[str] | None = None,
) -> str:
    """Crea un .xlsx sintetico con la ``Tabla_Disp_SD``.

    Inyecta automaticamente la columna ``PLC`` con ``"PLC1"`` para
    cumplir el contrato multi-PLC sin que el caller tenga que
    repetirla.
    """
    if headers is None:
        headers = list(CABECERAS_SD)
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


def _build_row_sd(
    *,
    uid: str = "SD_001",
    numero: int = 1,
    s_byte: int = 4,
    s_bit: int = 3,
) -> list:
    """Devuelve una fila valida para la Tabla_Disp_SD con los 21 campos."""
    return [
        uid,                              # UID
        numero,                           # Numero
        f"V_SD_{numero:03d}",             # PLC.Tag
        f"Comentario SD {numero}",        # PLC.Comentario
        f"Salida digital {numero}",       # Descripcion
        f"T_SD_{numero:03d}",             # Tag
        f"F_SD_{numero:03d}",             # FAT
        s_byte,                           # S.Byte
        s_bit,                            # S.Bit
        1,                                # Gr.Alarma
        "C1",                             # Cuadro
        "Obs",                            # Observaciones
        "Bool",                           # PLC.Tipo
        0,                                # PLC.Index
        2,                                # Hmi.Index
        f"Texto HMI SD {numero}",         # Hmi.Texto
        "cfg_hab := 1;",                  # Cfg.Habilitar
        "cfg_byte := 4;",                 # Cfg.ByteEntrada
        "cfg_bit := 3;",                  # Cfg.BitEntrada
        "cfg_ga := 1;",                   # Cfg.GrupoAlarma
        f"DB SD {numero} comentario",     # ComentarioDB
    ]


# ── Tests ──────────────────────────────────────────────────────────────


def test_extrae_disp_sd_basico(tmp_path) -> None:
    """Excel con 1 fila valida -> ``DispSD`` con los campos correctos."""
    xlsx_path = _save_xlsx_sd(
        tmp_path,
        rows=[_build_row_sd()],
    )
    wb = load_workbook(xlsx_path)

    result = DispSDParser().extraer(wb)

    assert len(result) == 1
    d = result[0]
    assert isinstance(d, DispSD)
    assert d.uid == "SD_001"
    assert d.numero == 1
    assert d.plc_tag == "V_SD_001"
    assert d.plc_comentario == "Comentario SD 1"
    assert d.descripcion == "Salida digital 1"
    assert d.tag == "T_SD_001"
    assert d.fat == "F_SD_001"
    assert d.s_byte == 4
    assert d.s_bit == 3
    assert d.gr_alarma == 1
    assert d.cuadro == "C1"
    assert d.observaciones == "Obs"
    assert d.plc_tipo == "Bool"
    assert d.plc_index == 0
    assert d.hmi_index == 2
    assert d.hmi_texto == "Texto HMI SD 1"
    assert d.cfg_habilitar == "cfg_hab := 1;"
    assert d.cfg_byte_entrada == "cfg_byte := 4;"
    assert d.cfg_bit_entrada == "cfg_bit := 3;"
    assert d.cfg_grupo_alarma == "cfg_ga := 1;"
    assert d.comentario_db == "DB SD 1 comentario"
    assert d.plc_name == "PLC1"


def test_hoja_inexistente_devuelve_lista_vacia(tmp_path) -> None:
    """Hoja ``DISP_SD`` no existe -> ``[]`` (no lanza)."""
    xlsx_path = _save_xlsx_sd(
        tmp_path,
        rows=[_build_row_sd()],
        sheet_name="OTRA_HOJA",
    )
    wb = load_workbook(xlsx_path)
    result = DispSDParser().extraer(wb)
    assert result == []


def test_tabla_inexistente_devuelve_lista_vacia(tmp_path) -> None:
    """Hoja existe pero ``Tabla_Disp_SD`` no -> ``[]`` (no lanza)."""
    xlsx_path = tmp_path / "otro.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "DISP_SD"
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
    assert DispSDParser().extraer(wb2) == []


def test_fila_sin_uid_se_descarta(tmp_path) -> None:
    """Fila sin UID ni Numero se descarta; fila valida se conserva."""
    xlsx_path = _save_xlsx_sd(
        tmp_path,
        rows=[
            [None, None, "X", "X", "X"],   # sin UID ni Numero
            _build_row_sd(uid="SD_002"),
        ],
    )
    wb = load_workbook(xlsx_path)
    result = DispSDParser().extraer(wb)
    assert len(result) == 1
    assert result[0].uid == "SD_002"


def test_multiples_filas_validas(tmp_path) -> None:
    """Varias filas validas -> lista de multiples ``DispSD``."""
    rows = [
        _build_row_sd(uid="SD_001", numero=1, s_byte=0, s_bit=0),
        _build_row_sd(uid="SD_002", numero=2, s_byte=0, s_bit=1),
        _build_row_sd(uid="SD_003", numero=3, s_byte=1, s_bit=4),
    ]
    xlsx_path = _save_xlsx_sd(tmp_path, rows=rows)
    wb = load_workbook(xlsx_path)

    result = DispSDParser().extraer(wb)

    assert len(result) == 3
    uids = [d.uid for d in result]
    assert uids == ["SD_001", "SD_002", "SD_003"]
    assert result[0].s_bit == 0
    assert result[1].s_bit == 1
    assert result[2].s_byte == 1


def test_defaults_when_only_uid_and_numero(tmp_path) -> None:
    """Sin columnas especificas -> defaults tolerantes (str '', int 0)."""
    xlsx_path = _save_xlsx_sd(
        tmp_path,
        rows=[["SD_001", 1, "V_SD_001", "c", "d"]],
        headers=["UID", "Numero", "PLC.Tag", "PLC.Comentario", "Descripcion"],
    )
    wb = load_workbook(xlsx_path)
    result = DispSDParser().extraer(wb)
    assert len(result) == 1
    d = result[0]
    assert d.tag == ""
    assert d.fat == ""
    assert d.s_byte == 0
    assert d.s_bit == 0
    assert d.gr_alarma == 0
    assert d.cfg_byte_entrada == ""
    assert d.cfg_bit_entrada == ""
    assert d.cfg_grupo_alarma == ""
    assert d.comentario_db == ""


def test_log_debug_contiene_sheet_y_count(tmp_path, caplog) -> None:
    """El log de debug lleva el formato ``Parser[<sheet>/<table>]: N -> M``."""
    import logging

    rows = [
        _build_row_sd(uid="SD_001", numero=1),
        _build_row_sd(uid="SD_002", numero=2),
    ]
    xlsx_path = _save_xlsx_sd(tmp_path, rows=rows)
    wb = load_workbook(xlsx_path)

    with caplog.at_level(logging.DEBUG, logger="areas.alimentacion.helpers.excel.excel_parser_disp_sd"):
        result = DispSDParser().extraer(wb)

    assert len(result) == 2
    debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("Parser[DISP_SD/Tabla_Disp_SD]" in m for m in debug_msgs), (
        f"No se encontro el log 'Parser[DISP_SD/Tabla_Disp_SD]:' en: {debug_msgs}"
    )
    assert any("2 filas -> 2 extraidas" in m for m in debug_msgs), (
        f"No se encontro el conteo esperado: 2 -> 2 en {debug_msgs}"
    )
