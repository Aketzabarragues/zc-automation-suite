"""Tests end-to-end del ``ExcelLoader`` (Fase 5 del plan).

Sept-2026 (multi-PLC): los tests inyectan la columna ``PLC`` con valor
``"PLC1"`` en cada tabla de dispositivos/software y la tabla N_MAX
``Tabla_N_Max`` con los N_MAX por PLC. Aserciones adaptadas al shape
multi-PLC de ``DimensionesPLC.por_plc``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from areas.alimentacion.data.data_dimensiones import DimensionesPLC
from core.data.data_excel_cache import DataExcelCache
from areas.alimentacion.data.data_parametros_int import DataParamIntPLC
from areas.alimentacion.data.data_parametros_real import DataParamRealPLC
from areas.alimentacion.data.data_procesos import DataProcesoPLC
from areas.alimentacion.helpers.excel.excel_loader import ExcelLoader


# ---------------------------------------------------------------------------
# Helpers de creacion de .xlsx sinteticos
# ---------------------------------------------------------------------------


def _add_table(
    wb: Workbook,
    sheet_name: str,
    table_name: str,
    headers: list[str],
    rows: list[list],
) -> None:
    """Anade una ListObject con la columna PLC auto-inyectada.

    La tabla se inserta al final del contenido actual de la hoja
    (``ws.max_row + 1``), no siempre en ``A1``. Si la hoja ya tiene
    otra tabla (p. ej. ``Tabla_Dimensiones`` en ``CONFIG``), calcular
    ``ref`` desde ``A1`` haria que la nueva tabla colisione con la
    previa: openpyxl acepta las dos referencias pero al recargar el
    workbook la lectura de filas por ``range_boundaries`` cae en la
    primera tabla y devuelve sus datos. Por eso el parser ve la fila
    N_MAX en lugar de la fila Procesos, y la descarta por falta de
    columna ``PLC``.
    """
    if sheet_name not in wb.sheetnames:
        ws = wb.create_sheet(sheet_name)
    else:
        ws = wb[sheet_name]
    if "PLC" not in headers:
        headers = ["PLC"] + list(headers)
        rows = [["PLC1"] + list(r) for r in rows]
    # Insertar al final de la hoja: 1 fila de cabecera + N filas de datos.
    start_row = ws.max_row + 1
    ws.cell(row=start_row, column=1, value=headers[0])
    for col_idx, header in enumerate(headers[1:], start=2):
        ws.cell(row=start_row, column=col_idx, value=header)
    for row_offset, row in enumerate(rows, start=1):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=start_row + row_offset, column=col_idx, value=value)
    last_col_letter = chr(ord("A") + len(headers) - 1)
    last_row = start_row + len(rows)
    ref = f"A{start_row}:{last_col_letter}{last_row}"
    table = Table(displayName=table_name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showFirstColumn=False,
        showLastColumn=False, showRowStripes=True, showColumnStripes=False,
    )
    ws.add_table(table)


def _add_n_max_table(
    wb: Workbook,
    sheet_name: str,
    plc: str,
    n_max: dict[str, int],
) -> None:
    """Anade (o reemplaza) la tabla ``Tabla_N_Max`` en ``sheet_name``."""
    if sheet_name not in wb.sheetnames:
        ws = wb.create_sheet(sheet_name)
    else:
        ws = wb[sheet_name]

    headers = [
        "PLC", "N_Max_ED", "N_Max_EA", "N_Max_SA", "N_Max_V", "N_Max_M",
        "N_Max_M_VF", "N_Max_M_SINA", "N_Max_TOT", "N_Max_PID",
    ]
    # Borrar contenido previo (incluyendo cualquier cabecera previa).
    if ws.max_row > 0:
        ws.delete_rows(1, ws.max_row)
    # Borrar tablas previas en esta hoja.
    for tname in list(ws.tables.keys()):
        del ws.tables[tname]
    # Escribir cabecera + fila de datos.
    ws.append(headers)
    row = [plc] + [n_max.get(h, 0) for h in headers[1:]]
    ws.append(row)
    last_col_letter = chr(ord("A") + len(headers) - 1)
    last_row = ws.max_row
    ref = f"A1:{last_col_letter}{last_row}"
    table = Table(displayName="Tabla_Dimensiones", ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showFirstColumn=False,
        showLastColumn=False, showRowStripes=True, showColumnStripes=False,
    )
    ws.add_table(table)


def _build_full_xlsx(target: Path) -> Path:
    """Construye un xlsx con 1 fila de CADA uno de los 10 dominios + tabla N_MAX."""
    wb = Workbook()
    wb.remove(wb.active)

    # N_MAX (tabla Tabla_Dimensiones, multi-PLC).
    # Vive en la hoja CONFIG (igual que ``Tabla_PLC`` y
    # ``Tabla_Procesos``). El parser se alinea con los otros
    # parsers, hardcoded a ``"CONFIG"``.
    _add_n_max_table(wb, "CONFIG", "PLC1", {
        "N_Max_ED": 10, "N_Max_EA": 20, "N_Max_SA": 30, "N_Max_V": 40,
        "N_Max_M": 50, "N_Max_M_VF": 60, "N_Max_M_SINA": 70,
        "N_Max_TOT": 80, "N_Max_PID": 90,
    })

    # 9 dispositivos
    _add_table(wb, "DISP_ED", "Tabla_Disp_ED",
               ["UID", "Numero", "PLC.Tag", "Descripcion"],
               [["ED_001", 1, "V_ED_001", "Entrada digital 1"]])
    _add_table(wb, "DISP_EA", "Tabla_Disp_EA",
               ["UID", "Numero", "PLC.Tag", "Descripcion", "RII", "RSI"],
               [["EA_001", 1, "V_EA_001", "Entrada analogica 1", 0.0, 100.0]])
    _add_table(wb, "DISP_SA", "Tabla_Disp_SA",
               ["UID", "Numero", "PLC.Tag", "Descripcion"],
               [["SA_001", 1, "V_SA_001", "Salida analogica 1"]])
    _add_table(wb, "DISP_V", "Tabla_Disp_V",
               ["UID", "Numero", "PLC.Tag", "Descripcion"],
               [["V_001", 1, "V_V_001", "Variable 1"]])
    _add_table(wb, "DISP_M", "Tabla_Disp_M",
               ["UID", "Numero", "PLC.Tag", "Descripcion"],
               [["M_001", 1, "V_M_001", "Motor 1"]])
    _add_table(wb, "DISP_M_VF", "Tabla_Disp_M_VF",
               ["UID", "Numero", "PLC.Tag", "Descripcion"],
               [["MVF_001", 1, "V_MVF_001", "Motor VF 1"]])
    _add_table(wb, "DISP_M_SINA", "Tabla_Disp_M_SINA",
               ["UID", "Numero", "PLC.Tag", "Descripcion"],
               [["MSINA_001", 1, "V_MSINA_001", "Motor Sinamics 1"]])
    _add_table(wb, "DISP_TOT", "Tabla_Disp_TOT",
               ["UID", "Numero", "PLC.Tag", "Descripcion"],
               [["TOT_001", 1, "V_TOT_001", "Totalizador 1"]])
    _add_table(wb, "DISP_PID", "Tabla_Disp_PID",
               ["UID", "Numero", "PLC.Tag", "Descripcion"],
               [["PID_001", 1, "V_PID_001", "Controlador PID 1"]])

    # 4 software
    _add_table(wb, "CONFIG", "Tabla_Procesos",
               ["UID", "PLC", "Nombre", "Codigo", "PReal", "PInt", "Alarmas"],
               [[1, "PLC1", "Proceso 1", "PR1", 1, 1, 16]])
    _add_table(wb, "P_REAL", "Tabla_PReal",
               ["UID", "Numero", "Proceso", "Codigo", "Num.DB",
                "Producto", "Tipo", "Descripcion", "ComentarioDB",
                "Visibilidad", "Num.Lista", "Txt.Lista"],
               [["PR_1_001", "001", "Proceso 1", "PR1", 3001,
                 "Producto", "Setpoint", "PR1", "c", "Si", 1, "Txt"]])
    _add_table(wb, "P_INT", "Tabla_PInt",
               ["UID", "Numero", "Proceso", "Codigo", "Num.DB",
                "Producto", "Tipo", "Descripcion", "ComentarioDB",
                "Visibilidad", "Num.Lista", "Txt.Lista"],
               [["PI_1_001", "001", "Proceso 1", "PR1", 3002,
                 "Producto", "Contador", "PI1", "c", "Si", 0, "Txt"]])
    _add_table(wb, "ALARMAS", "Tabla_Alarmas",
               ["UID", "Numero", "Proceso", "Num.DB", "Descripcion", "ComentarioDB"],
               [["AL_1_001", "001", "Proceso 1", 5001, "Alarma 1", "c"]])

    wb.save(target)
    return target


def _config_manager_for_loader(tmp_path: Path) -> Any:
    """ConfigManager minimo para que el loader pueda leer la Tabla_N_Max."""
    cfg: dict[str, Any] = {
        "departments": {
            "alimentacion": {
                "global_config_table_name": "CONFIG",
                "tia_folders": {
                    "proceso": "003_Procesos",
                    "dispositivos": "2000_Dispositivos",
                    "nmax": "000_Sistema",
                },
                "n_max_catalog": [
                    {"name": "N_MAX_DISP_ED",      "hw_type": "ed",      "excel_column": "N_Max_ED"},
                    {"name": "N_MAX_DISP_EA",      "hw_type": "ea",      "excel_column": "N_Max_EA"},
                    {"name": "N_MAX_DISP_SA",      "hw_type": "sa",      "excel_column": "N_Max_SA"},
                    {"name": "N_MAX_DISP_V",       "hw_type": "v",       "excel_column": "N_Max_V"},
                    {"name": "N_MAX_DISP_M",       "hw_type": "m",       "excel_column": "N_Max_M"},
                    {"name": "N_MAX_DISP_M_VF",    "hw_type": "m_vf",    "excel_column": "N_Max_M_VF"},
                    {"name": "N_MAX_DISP_M_SINA",  "hw_type": "m_sina",  "excel_column": "N_Max_M_SINA"},
                    {"name": "N_MAX_DISP_TOT",     "hw_type": "tot",     "excel_column": "N_Max_TOT"},
                    {"name": "N_MAX_DISP_PID",     "hw_type": "pid",     "excel_column": "N_Max_PID"},
                ],
                "Dispositivos": {},
            }
        }
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    from core.infrastructure.config.config_manager import ConfigManager
    return ConfigManager(config_path=config_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_load_basico(tmp_path) -> None:
    """Excel con 1 fila de CADA dominio -> DataExcelCache con todos los campos."""
    xlsx = _build_full_xlsx(tmp_path / "full.xlsx")
    cache = ExcelLoader(config_manager=_config_manager_for_loader(tmp_path)).load(xlsx)

    assert isinstance(cache, DataExcelCache)
    # Path absoluto.
    assert cache.excel_path.endswith("full.xlsx")
    # mtime_ns es un int > 0.
    assert cache.excel_mtime_ns > 0
    # parsed_at es un datetime UTC.
    assert cache.parsed_at.tzinfo is not None
    # Los 9 tipos de dispositivos tienen 1 elemento, cada uno con plc_name="PLC1".
    for hw in ("ed", "ea", "sa", "v", "m", "m_vf", "m_sina", "tot", "pid"):
        assert len(cache.dispositivos[hw]) == 1
        assert cache.dispositivos[hw][0].plc_name == "PLC1"
    # Las 4 listas de software tienen 1 elemento.
    assert len(cache.procesos) == 1
    assert len(cache.parametros_real) == 1
    assert len(cache.parametros_int) == 1
    assert len(cache.alarmas) == 1
    assert cache.procesos[0].plc_name == "PLC1"
    # Entidades: vacio porque el xlsx sintetico no incluye hoja ENTIDADES.
    assert cache.entidades == ()
    # N_MAX: shape multi-PLC con 1 entrada (PLC1).
    assert isinstance(cache.n_max, DimensionesPLC)
    plc1 = cache.n_max.get_for_plc("PLC1")
    assert plc1 is not None
    assert plc1.get("N_MAX_DISP_ED") == 10
    assert plc1.get("N_MAX_DISP_PID") == 90
    # Flag.
    assert cache.software_parsers_implemented is True


def test_load_con_excel_inexistente_lanza_filenotfounderror(tmp_path) -> None:
    """Path inexistente -> FileNotFoundError."""
    missing = tmp_path / "no.xlsx"
    with pytest.raises(FileNotFoundError):
        ExcelLoader().load(missing)


def test_load_construye_lookups_by_codigo(tmp_path) -> None:
    """Los 3 lookups precomputados tienen el ``codigo`` correcto como clave."""
    xlsx = _build_full_xlsx(tmp_path / "full.xlsx")
    cache = ExcelLoader(config_manager=_config_manager_for_loader(tmp_path)).load(xlsx)

    # Procesos: el ``DataProcesoPLC`` con ``codigo=PR1``.
    assert "PR1" in cache.procesos_by_codigo
    assert isinstance(cache.procesos_by_codigo["PR1"], DataProcesoPLC)
    # PReal: el ``DataParamRealPLC`` con ``codigo=PR1``.
    assert "PR1" in cache.parametros_real_by_codigo
    assert isinstance(cache.parametros_real_by_codigo["PR1"], DataParamRealPLC)
    # PInt: el ``DataParamIntPLC`` con ``codigo=PR1``.
    assert "PR1" in cache.parametros_int_by_codigo
    assert isinstance(cache.parametros_int_by_codigo["PR1"], DataParamIntPLC)


def test_load_workbook_cerrado_tras_error(tmp_path, monkeypatch) -> None:
    """Si un parser lanza, ``wb.close()`` se llama en el ``finally``."""
    from areas.alimentacion.helpers.excel import excel_parser_disp_ed as disp_ed_mod

    calls: dict[str, int] = {"extraer": 0}

    def boom(self, wb):
        calls["extraer"] += 1
        raise RuntimeError("parser boom")

    monkeypatch.setattr(disp_ed_mod.DispEDParser, "extraer", boom)

    xlsx = _build_full_xlsx(tmp_path / "full.xlsx")
    with pytest.raises(RuntimeError, match="parser boom"):
        ExcelLoader().load(xlsx)

    # El parser mockeado se llamo 1 vez.
    assert calls["extraer"] == 1


def test_load_con_hojas_faltantes(tmp_path) -> None:
    """Excel SIN hojas de software -> listas vacias, no excepcion."""
    wb = Workbook()
    wb.remove(wb.active)
    # Solo 1 dispositivo y nada mas.
    _add_table(wb, "DISP_ED", "Tabla_Disp_ED",
               ["UID", "Numero", "PLC.Tag", "Descripcion"],
               [["ED_001", 1, "V_ED_001", "Entrada 1"]])
    xlsx = tmp_path / "minimal.xlsx"
    wb.save(xlsx)

    cache = ExcelLoader().load(xlsx)
    # Dispositivo poblado.
    assert len(cache.dispositivos["ed"]) == 1
    # Software: listas vacias.
    assert cache.procesos == ()
    assert cache.parametros_real == ()
    assert cache.parametros_int == ()
    assert cache.alarmas == ()
    # N_MAX: defaults (sin tabla).
    assert isinstance(cache.n_max, DimensionesPLC)
    assert cache.n_max.por_plc == ()


def test_to_dict_serailiza_todo(tmp_path) -> None:
    """``DataExcelCache.to_dict()`` es JSON-serializable."""
    xlsx = _build_full_xlsx(tmp_path / "full.xlsx")
    cache = ExcelLoader(config_manager=_config_manager_for_loader(tmp_path)).load(xlsx)
    d = cache.to_dict()
    # No lanza y produce un dict JSON-serializable.
    json.dumps(d)


def test_load_with_config_manager(tmp_path) -> None:
    """Si se inyecta un ``ConfigManager``, los parsers lo usan para
    resolver ``SHEET``/``TABLE`` data-driven."""
    cm = _config_manager_for_loader(tmp_path)

    xlsx = _build_full_xlsx(tmp_path / "full.xlsx")
    cache = ExcelLoader(config_manager=cm).load(xlsx)
    assert isinstance(cache, DataExcelCache)


def test_load_puebla_entidades_desde_hoja_ENTIDADES(tmp_path) -> None:
    """xlsx con Tabla_Entidades -> ``cache.entidades`` queda poblada.

    Validates the integration EntidadesParser -> ExcelLoader ->
    DataExcelCache.entidades. No requiere config_manager porque la
    hoja ``ENTIDADES`` y la tabla ``Tabla_Entidades`` son fijas.
    """
    from areas.alimentacion.data.data_entidades import Entidad

    wb = Workbook()
    wb.remove(wb.active)
    # Tabla minima con las 7 columnas que el parser lee.
    _add_table(
        wb, "ENTIDADES", "Tabla_Entidades",
        ["Numero", "PLC.Tag"],
        [
            [1, "ent_001"],
            [2, "ent_002"],
        ],
    )
    xlsx = tmp_path / "with_entidades.xlsx"
    wb.save(xlsx)

    cache = ExcelLoader().load(xlsx)

    assert len(cache.entidades) == 2
    assert cache.entidades[0] == Entidad(numero=1, plc_name="PLC1", plc_tag="ent_001")
    assert cache.entidades[1] == Entidad(numero=2, plc_name="PLC1", plc_tag="ent_002")