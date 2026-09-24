"""Tests del parser ``AlarmasParser`` (Fase 4 del plan).

Cubre la extracciÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â³n de ``Tabla_Alarmas`` (hoja ``ALARMAS``) y, en
particular, la invariante R-F4.1: ``DataAlarmaPLC`` NO tiene atributo
``visibilidad`` y el parser ignora silenciosamente la columna
``Visibilidad`` del Excel si esta existe.

Es la **implementaciÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â³n de referencia** que los 6 mini parsers de
dispositivos de Fase 5 imitarÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡n; los tests aquÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­ son la plantilla
que los tests de Fase 5 extenderÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡n.

Convenciones:
    * Excel sintÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©tico construido en ``tmp_path`` con ``Table`` real
      (R5 del plan).
    * Se carga con ``load_workbook`` para garantizar que la
      ``ListObject`` se registre en ``worksheet.tables``.
"""
from __future__ import annotations

from dataclasses import fields

from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from areas.alimentacion.data.data_alarmas import DataAlarmaPLC
from areas.alimentacion.helpers.excel.excel_parser_proc_alarmas import AlarmasParser


# ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ Helpers de construcciÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â³n de Excels sintÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ticos ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬


def _save_xlsx_with_alarmas_table(
    tmp_path,
    rows: list[list] | None,
    *,
    sheet_name: str = "ALARMAS",
    table_name: str = "Tabla_Alarmas",
    headers: list[str] | None = None,
) -> str:
    """Crea un .xlsx sintÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©tico con la tabla de alarmas.

    Args:
        tmp_path: fixture pytest de path temporal.
        rows: lista de filas de datos (``None`` o ``[]`` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ solo
            cabeceras, ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Âºtil para verificar que la tabla existe
            pero estÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡ vacÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­a).
        sheet_name: nombre de la hoja (default ``ALARMAS``).
        table_name: nombre de la ``ListObject`` (default
            ``Tabla_Alarmas``).
        headers: cabeceras (default: las del Excel legacy del
            corporativo, 6 columnas). Si se pasa otra lista, el
            test puede simular schema drift (p. ej. aÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â±adir
            ``Visibilidad`` para verificar R-F4.1).

    Returns:
        Path absoluto del .xlsx en str.
    """
    if headers is None:
        # Cabeceras del legacy: 6 columnas, SIN Visibilidad.
        headers = [
            "UID",
            "Numero",
            "Proceso",
            "Num.DB",
            "Descripcion",
            "ComentarioDB",
        ]
    if rows is None:
        rows = []

    xlsx_path = tmp_path / f"{table_name}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)

    # Registrar la Table (R5 del plan: sin esto, ``worksheet.tables``
    # no contiene la ``ListObject`` y el parser no la encontrarÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­a).
    last_col_letter = chr(ord("A") + len(headers) - 1)
    last_row = 1 + len(rows)
    ref = f"A1:{last_col_letter}{last_row}"
    table = Table(displayName=table_name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(table)
    wb.save(str(xlsx_path))
    return str(xlsx_path)


def _load(path: str) -> Workbook:
    """Carga un .xlsx desde disco preservando ``worksheet.tables``."""
    from openpyxl import load_workbook

    return load_workbook(path)


# ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ Tests del parser ``AlarmasParser`` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬


def test_extrae_alarmas_basico(tmp_path) -> None:
    """Excel con 1 fila vÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡lida ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ DTO con los 6 campos correctos.

    El test cubre los 6 campos del DTO ``DataAlarmaPLC``:
    ``uid``, ``numero``, ``proceso``, ``num_db``, ``descripcion``,
    ``comentario_db``. ``num_db`` se castea a ``int`` vÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­a
    ``_safe_int``. El resto son ``str`` con defaults tolerantes.
    """
    xlsx_path = _save_xlsx_with_alarmas_table(
        tmp_path,
        rows=[
            [
                "AL_1_001",  # UID
                "001",  # Numero
                "Proceso Uno",  # Proceso
                5001,  # Num.DB (DB alarmas = 5000+uid)
                "Presion alta en linea A",  # Descripcion
                "DB alarmas proceso 1",  # ComentarioDB
            ],
        ],
    )
    wb = _load(xlsx_path)

    result = AlarmasParser().extraer(wb)

    assert len(result) == 1
    a = result[0]
    assert isinstance(a, DataAlarmaPLC)
    assert a.uid == "AL_1_001"
    assert a.numero == "001"
    assert a.proceso == "Proceso Uno"
    assert a.num_db == 5001
    assert a.descripcion == "Presion alta en linea A"
    assert a.comentario_db == "DB alarmas proceso 1"


def test_hoja_inexistente_devuelve_lista_vacia(tmp_path) -> None:
    """Sheet ``ALARMAS`` no existe ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ ``[]`` (no lanza).

    PolÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­tica coherente con R1 del plan y con el resto de
    parsers de software: si la hoja no estÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡, no es un error
    (el Excel puede no traerla en alguna configuraciÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â³n).
    """
    xlsx_path = _save_xlsx_with_alarmas_table(
        tmp_path,
        rows=[["AL_1_001", "001", "P", 5001, "", ""]],
        sheet_name="OTRA_HOJA",
    )
    wb = _load(xlsx_path)

    result = AlarmasParser().extraer(wb)

    assert result == []


def test_tabla_inexistente_devuelve_lista_vacia(tmp_path) -> None:
    """Sheet existe pero ``Tabla_Alarmas`` no ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ ``[]`` (no lanza)."""
    # Construimos un .xlsx con OTRA tabla en ALARMAS.
    xlsx_path = tmp_path / "otro.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "ALARMAS"
    ws.append(["X", "Y"])
    ws.append([1, 2])
    table = Table(displayName="Tabla_Otra", ref="A1:B2")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(table)
    wb.save(str(xlsx_path))

    wb2 = _load(xlsx_path)
    result = AlarmasParser().extraer(wb2)
    assert result == []


def test_fila_sin_uid_se_descarta(tmp_path) -> None:
    """Fila con UID vacÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­o (``None``) NO aparece en el resultado.

    PolÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­tica consistente con ``ProcesosParser``/``PRealParser``/
    ``PIntParser`` (dropna por UID). Evita alarmas fantasma sin
    UID en el cache.
    """
    xlsx_path = _save_xlsx_with_alarmas_table(
        tmp_path,
        rows=[
            [None, "001", "P", 5001, "desc", "coment"],  # sin UID
            [
                "AL_1_001",  # vÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡lida
                "001",
                "Proceso Uno",
                5001,
                "desc",
                "coment",
            ],
        ],
    )
    wb = _load(xlsx_path)

    result = AlarmasParser().extraer(wb)

    # Solo la fila con UID vÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡lido se queda.
    assert len(result) == 1
    assert result[0].uid == "AL_1_001"


def test_sin_visibilidad_en_dto() -> None:
    """``DataAlarmaPLC`` NO expone atributo ``visibilidad`` (R-F4.1).

    Esta es una **invariante contractual**: la tabla de Alarmas
    del Excel corporativo no incluye ``Visibilidad`` (consistente
    con el legacy ``_legacy_reference/ZC_ALM_TOOLS/infrastructure/
    parsers/software/alarmas.py:21-31``), por lo que el DTO no
    expone ese campo. El test bloquea cualquier regresiÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â³n que
    aÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â±ada ``visibilidad`` al DTO por confusiÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â³n con
    ``DataParamRealPLC``/``DataParamIntPLC``.

    Se verifica doble:
        * ``hasattr(DataAlarmaPLC(...), 'visibilidad') == False``
          (invariante de instancia).
        * ``'visibilidad' not in [f.name for f in fields(DataAlarmaPLC)]``
          (invariante de clase / dataclass).
    """
    a = DataAlarmaPLC(
        uid="AL_1_001",
        numero="001",
        proceso="P",
        num_db=5001,
        descripcion="d",
        comentario_db="c",
    )
    # Invariante de instancia.
    assert not hasattr(a, "visibilidad")
    # Invariante de clase.
    field_names = {f.name for f in fields(DataAlarmaPLC)}
    assert "visibilidad" not in field_names
    # Sanity: los 6 campos esperados sÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­ estÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡n.
    assert field_names == {
        "uid",
        "numero",
        "proceso",
        "num_db",
        "descripcion",
        "comentario_db",
    }


def test_columna_visibilidad_en_excel_se_ignora(tmp_path) -> None:
    """Columna extra ``Visibilidad`` en el Excel se ignora (R-F4.1).

    Defensa contra schema drift: si el corporativo aÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â±ade una
    columna ``Visibilidad`` a ``Tabla_Alarmas`` en el futuro, el
    parser la **ignora silenciosamente**. El DTO se construye
    correctamente con sus 6 campos conocidos y el resultado NO
    tiene atributo ``visibilidad``.

    Por quÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â© funciona: ``AlarmasParser.extraer`` llama al
    constructor de ``DataAlarmaPLC`` con kwargs explÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­citos
    (``uid=...``, ``numero=...``, etc.) y NO usa ``**row``. La
    columna extra queda en el ``dict`` que devuelve
    ``extract_list_object_rows``, pero el constructor de la
    dataclass ``frozen=True`` nunca la lee. No se emite WARNING
    ni se descarta la fila: la alarma se conserva con sus 6
    campos originales.

    Esto es crÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­tico para la **back-compat con el legacy** y para
    que ``AlarmasParser`` siga siendo drop-in si el schema del
    Excel evoluciona.
    """
    # Cabecera con Visibilidad aÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â±adida al final (columna extra).
    headers_con_visibilidad = [
        "UID",
        "Numero",
        "Proceso",
        "Num.DB",
        "Descripcion",
        "ComentarioDB",
        "Visibilidad",  # columna extra (schema drift)
    ]
    # Una fila vÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡lida: el campo "Si" en Visibilidad debe ignorarse.
    fila = [
        "AL_1_001",
        "001",
        "Proceso Uno",
        5001,
        "Presion alta",
        "DB alarmas",
        "Si",  # valor de la columna ignorada
    ]
    xlsx_path = _save_xlsx_with_alarmas_table(
        tmp_path,
        rows=[fila],
        headers=headers_con_visibilidad,
    )
    wb = _load(xlsx_path)

    result = AlarmasParser().extraer(wb)

    # El parser devuelve 1 alarma: la fila es vÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¡lida para los 6
    # campos que conoce, y la columna "Visibilidad" simplemente
    # se ignora.
    assert len(result) == 1
    a = result[0]
    # El DTO tiene los 6 campos esperados con los valores correctos.
    assert a.uid == "AL_1_001"
    assert a.numero == "001"
    assert a.proceso == "Proceso Uno"
    assert a.num_db == 5001
    assert a.descripcion == "Presion alta"
    assert a.comentario_db == "DB alarmas"
    # El valor de "Visibilidad" NO aparece en el DTO.
    assert not hasattr(a, "visibilidad")
    # El dict crudo sÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­ traÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­a la clave (extract_list_object_rows la
    # recoge), pero el constructor de DataAlarmaPLC solo lee los 6
    # kwargs explÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â­citos. Verificamos que la fila cruda tiene la
    # clave para confirmar que el parser la "vio" pero no la usÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â³.
    from areas.alimentacion.helpers.excel._excel_helpers import (
        extract_list_object_rows,
    )
    raw_rows = extract_list_object_rows(wb, "ALARMAS", "Tabla_Alarmas")
    assert len(raw_rows) == 1
    assert raw_rows[0].get("Visibilidad") == "Si"
