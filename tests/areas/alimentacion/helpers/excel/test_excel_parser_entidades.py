"""Tests del ``EntidadesParser`` (hoja ``ENTIDADES``).

Patron seguido: Excel sintetico con ``Table`` real en ``tmp_path``,
replica de ``test_disp_ed_parser.py``. Cabeceras literales del
Excel (con puntos y mayusculas). ``extract_list_object_rows`` ya
esta cubierta por ``test_xlsx_helpers.py``; aqui solo verificamos
que el parser rellena los campos del DTO correctamente y descarta
filas invalidas sin romper la carga.
"""
from __future__ import annotations

import logging

from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from areas.alimentacion.data.data_entidades import Entidad
from areas.alimentacion.helpers.excel.excel_parser_entidades import EntidadesParser


# ── Helpers ──────────────────────────────────────────────────────────────


# Cabeceras por defecto: las 37 reales del Excel corporativo (Numero, PLC,
# Descripcion, 15×DispX.Tipo/Tag, PLC.Tag, PLC.Tipo, PLC.Index, PLC.Comentario).
_HEADERS_DEFAULT: list[str] = [
    "Numero", "PLC", "Descripcion",
    "Disp1.Tipo", "Disp1.Tag",
    "Disp2.Tipo", "Disp2.Tag",
    "Disp3.Tipo", "Disp3.Tag",
    "Disp4.Tipo", "Disp4.Tag",
    "Disp5.Tipo", "Disp5.Tag",
    "Disp6.Tipo", "Disp6.Tag",
    "Disp7.Tipo", "Disp7.Tag",
    "Disp8.Tipo", "Disp8.Tag",
    "Disp9.Tipo", "Disp9.Tag",
    "Disp10.Tipo", "Disp10.Tag",
    "Disp11.Tipo", "Disp11.Tag",
    "Disp12.Tipo", "Disp12.Tag",
    "Disp13.Tipo", "Disp13.Tag",
    "Disp14.Tipo", "Disp14.Tag",
    "Disp15.Tipo", "Disp15.Tag",
    "PLC.Tag", "PLC.Tipo", "PLC.Index", "PLC.Comentario",
]


def _row(campos: dict[str, object]) -> list:
    """Construye una fila como ``list`` alineada con ``_HEADERS_DEFAULT``.

    ``campos`` mapea ``nombre_columna`` -> valor. Cualquier columna no
    pasada queda como cadena vacia (cubre el caso de celdas vacias
    en el Excel).
    """
    return [campos.get(h, "") for h in _HEADERS_DEFAULT]


def _save_xlsx_with_entidades_table(
    tmp_path,
    rows: list[list] | None,
    *,
    sheet_name: str = "ENTIDADES",
    table_name: str = "Tabla_Entidades",
    headers: list[str] | None = None,
) -> str:
    """Crea un .xlsx sintetico con la ``Tabla_Entidades``."""
    if headers is None:
        headers = _HEADERS_DEFAULT
    if rows is None:
        rows = []
    xlsx_path = tmp_path / f"{table_name}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    last_col_letter = _col_letter(len(headers) - 1)
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


def _col_letter(idx_zero_based: int) -> str:
    """Convierte indice 0-based a letra de columna Excel (A, B, ..., ZZ)."""
    result = ""
    n = idx_zero_based
    while True:
        result = chr(ord("A") + (n % 26)) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


def _load(path: str) -> Workbook:
    from openpyxl import load_workbook
    return load_workbook(path)


# ── Tests ────────────────────────────────────────────────────────────────


def test_extrae_entidad_basica(tmp_path):
    """Excel con 1 fila valida -> ``Entidad`` con los 7 campos correctos."""
    xlsx = _save_xlsx_with_entidades_table(
        tmp_path,
        rows=[
            _row({
                "Numero": 1,
                "PLC": "PLC1",
                "Descripcion": "Valvula cierre",
                "PLC.Tag": "ent_001",
                "PLC.Tipo": 1,
                "PLC.Index": 7,
                "PLC.Comentario": "// comentario slot 1",
            }),
        ],
    )
    wb = _load(xlsx)
    entities = EntidadesParser(wb).parse()

    assert len(entities) == 1
    e = entities[0]
    assert e == Entidad(
        numero=1,
        plc_name="PLC1",
        plc_tag="ent_001",
        descripcion="Valvula cierre",
        plc_comentario="// comentario slot 1",
        plc_tipo=1,
        plc_index=7,
    )


def test_extrae_multiples_entidades_orden_preservado(tmp_path):
    """El orden del Excel se preserva en la salida (no se ordena)."""
    xlsx = _save_xlsx_with_entidades_table(
        tmp_path,
        rows=[
            _row({"Numero": 3, "PLC": "PLC1", "Descripcion": "Tercera", "PLC.Tag": "ent_003"}),
            _row({"Numero": 1, "PLC": "PLC1", "Descripcion": "Primera", "PLC.Tag": "ent_001"}),
            _row({"Numero": 2, "PLC": "PLC2", "Descripcion": "Segunda PLC2", "PLC.Tag": "ent_002"}),
        ],
    )
    wb = _load(xlsx)
    entities = EntidadesParser(wb).parse()

    assert [e.numero for e in entities] == [3, 1, 2]
    assert [e.plc_name for e in entities] == ["PLC1", "PLC1", "PLC2"]


def test_campos_opcionales_vacios_toman_defaults(tmp_path):
    """Celdas vacias en columnas opcionales -> defaults del DTO."""
    xlsx = _save_xlsx_with_entidades_table(
        tmp_path,
        rows=[
            _row({"Numero": 5, "PLC": "PLC1", "PLC.Tag": "ent_005"}),
        ],
    )
    wb = _load(xlsx)
    e = EntidadesParser(wb).parse()[0]
    assert e.descripcion == ""
    assert e.plc_comentario == ""
    assert e.plc_tipo == 0
    assert e.plc_index == 0


def test_dispX_ignorado_no_contamina_DTO(tmp_path):
    """Garbage en Disp1..Disp15 NO afecta a los 7 campos del DTO."""
    # Llenamos DispX con basura directamente (sin _row_dict, para
    # validar que el parser la IGNORA al construir el DTO).
    headers = _HEADERS_DEFAULT
    row = [""] * len(headers)
    # Indices por nombre
    by_name = {h: i for i, h in enumerate(headers)}
    row[by_name["Numero"]] = 1
    row[by_name["PLC"]] = "PLC1"
    row[by_name["Descripcion"]] = "OK"
    row[by_name["PLC.Tag"]] = "ent_OK"
    # Basura en TODAS las DispX
    for h in headers:
        if h.startswith("Disp"):
            row[by_name[h]] = "BASURA"

    xlsx = _save_xlsx_with_entidades_table(tmp_path, rows=[row])
    wb = _load(xlsx)
    e = EntidadesParser(wb).parse()[0]

    assert e.numero == 1
    assert e.plc_name == "PLC1"
    assert e.plc_tag == "ent_OK"
    assert e.descripcion == "OK"


def test_placeholder_no_usar_incluido_en_salida(tmp_path):
    """``Numero=0, Descripcion='NO USAR'`` se incluye.

    Es la fila placeholder del Excel corporativo (sept-2026).
    El parser NO filtra; el FB sync decide que hacer con slot 0.
    """
    xlsx = _save_xlsx_with_entidades_table(
        tmp_path,
        rows=[
            _row({"Numero": 0, "PLC": "PLC1", "Descripcion": "NO USAR", "PLC.Tag": "ent_000"}),
        ],
    )
    wb = _load(xlsx)
    entities = EntidadesParser(wb).parse()
    assert len(entities) == 1
    assert entities[0].numero == 0
    assert entities[0].descripcion == "NO USAR"


def test_descarta_fila_sin_PLC_Tag(tmp_path, caplog):
    """Fila sin ``PLC.Tag`` se descarta con WARNING (no rompe la carga)."""
    xlsx = _save_xlsx_with_entidades_table(
        tmp_path,
        rows=[
            # Valida
            _row({"Numero": 1, "PLC": "PLC1", "PLC.Tag": "ent_001"}),
            # Invalida: PLC.Tag vacio
            _row({"Numero": 2, "PLC": "PLC1", "Descripcion": "Sin tag"}),
        ],
    )
    wb = _load(xlsx)
    with caplog.at_level(
        logging.WARNING,
        logger="areas.alimentacion.helpers.excel.excel_parser_entidades",
    ):
        entities = EntidadesParser(wb).parse()

    assert len(entities) == 1
    assert entities[0].numero == 1
    assert any("PLC.Tag vacio" in r.message for r in caplog.records)


def test_descarta_fila_sin_PLC(tmp_path, caplog):
    """Fila sin ``PLC`` se descarta con WARNING."""
    xlsx = _save_xlsx_with_entidades_table(
        tmp_path,
        rows=[
            _row({"Numero": 1, "Descripcion": "Sin PLC", "PLC.Tag": "ent_001"}),
        ],
    )
    wb = _load(xlsx)
    with caplog.at_level(
        logging.WARNING,
        logger="areas.alimentacion.helpers.excel.excel_parser_entidades",
    ):
        entities = EntidadesParser(wb).parse()
    assert entities == []
    assert any("PLC vacio" in r.message for r in caplog.records)


def test_descarta_fila_con_numero_negativo(tmp_path, caplog):
    """Fila con ``Numero < 0`` se descarta con WARNING."""
    xlsx = _save_xlsx_with_entidades_table(
        tmp_path,
        rows=[
            _row({"Numero": -1, "PLC": "PLC1", "PLC.Tag": "ent_neg"}),
        ],
    )
    wb = _load(xlsx)
    with caplog.at_level(
        logging.WARNING,
        logger="areas.alimentacion.helpers.excel.excel_parser_entidades",
    ):
        entities = EntidadesParser(wb).parse()
    assert entities == []
    assert any("Numero negativo" in r.message for r in caplog.records)


def test_hoja_inexistente_devuelve_lista_vacia():
    """Workbook sin la hoja ``ENTIDADES`` -> ``[]`` sin lanzar."""
    wb = Workbook()
    ws = wb.active
    ws.title = "OTRA_HOJA"
    assert EntidadesParser(wb).parse() == []


def test_tabla_inexistente_devuelve_lista_vacia():
    """Hoja ``ENTIDADES`` sin la ``Tabla_Entidades`` -> ``[]`` sin lanzar."""
    wb = Workbook()
    ws = wb.active
    ws.title = "ENTIDADES"
    ws.append(["X", "Y"])
    assert EntidadesParser(wb).parse() == []


def test_workbook_sin_filas_devuelve_lista_vacia(tmp_path):
    """Tabla con cabecera pero 0 filas -> ``[]``."""
    xlsx = _save_xlsx_with_entidades_table(tmp_path, rows=[])
    wb = _load(xlsx)
    assert EntidadesParser(wb).parse() == []


def test_multi_PLC_mezclados_en_una_tabla(tmp_path):
    """Filas de distintos PLC en la misma hoja -> todas en la lista."""
    xlsx = _save_xlsx_with_entidades_table(
        tmp_path,
        rows=[
            _row({"Numero": 1, "PLC": "PLC1", "PLC.Tag": "ent_a"}),
            _row({"Numero": 2, "PLC": "PLC2", "PLC.Tag": "ent_b"}),
            _row({"Numero": 3, "PLC": "PLC1", "PLC.Tag": "ent_c"}),
        ],
    )
    wb = _load(xlsx)
    entities = EntidadesParser(wb).parse()
    assert [e.plc_name for e in entities] == ["PLC1", "PLC2", "PLC1"]


def test_PLC_Tipo_PLC_Index_string_se_coerce_a_int(tmp_path):
    """``PLC.Tipo`` / ``PLC.Index`` con string numerico (``"5"``) -> int.

    El Excel a veces entrega strings para celdas numericas pequenas;
    ``_safe_int`` los coercea.
    """
    xlsx = _save_xlsx_with_entidades_table(
        tmp_path,
        rows=[
            _row({
                "Numero": 1,
                "PLC": "PLC1",
                "PLC.Tag": "ent_x",
                "PLC.Tipo": "5",
                "PLC.Index": "3",
            }),
        ],
    )
    wb = _load(xlsx)
    e = EntidadesParser(wb).parse()[0]
    assert e.plc_tipo == 5
    assert e.plc_index == 3