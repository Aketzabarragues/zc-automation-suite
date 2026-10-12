"""Tests del parser de N_MAX multi-PLC.

Cobertura:
  - 1 fila por PLC -> DimensionesPLC con por_plc poblado.
  - Sufijos ``N_Max_<HW>`` se traducen al canonico ``N_MAX_DISP_<HW>``.
  - Filas sin PLC se descartan.
  - Celdas vacias / no numericas -> 0 (validacion soft, sin error).
  - Modo strict: solo lee columnas listadas en ``n_max_catalog.excel_column``.
  - Excel sin tabla -> contenedor vacio (no rompe).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock

import pytest
from openpyxl import Workbook

from areas.alimentacion.data.data_dimensiones import (
    DimensionesPLC,
)
from areas.alimentacion.helpers.excel.excel_parser_disp_dimensiones import (
    N_MAX_TABLE_NAME,
    DimensionesParser,
    SHEET,
)
from core.infrastructure.config.config_manager import ConfigManager


# ── helpers ──────────────────────────────────────────────────────────


def _config_manager_for_tests(tmp_path) -> MagicMock:
    """Mock de ConfigManager con un catalog ``n_max_catalog`` para tests.

    Las entradas ``excel_column`` son las mismas que el config real del
    departamento ``alimentacion``. Esto fuerza al parser a usar el path
    data-driven.
    """
    cm = MagicMock(spec=ConfigManager)
    cm.list_nmax_active.return_value = [
        "N_MAX_DISP_ED", "N_MAX_DISP_EA", "N_MAX_DISP_SA", "N_MAX_DISP_V",
        "N_MAX_DISP_M", "N_MAX_DISP_M_VF", "N_MAX_DISP_M_SINA",
        "N_MAX_DISP_TOT", "N_MAX_DISP_PID",
    ]
    excel_to_hw = {
        "N_Max_ED": "ed", "N_Max_EA": "ea", "N_Max_SA": "sa",
        "N_Max_V": "v", "N_Max_M": "m", "N_Max_M_VF": "m_vf",
        "N_Max_M_SINA": "m_sina", "N_Max_TOT": "tot", "N_Max_PID": "pid",
    }

    def _entry(name: str) -> dict[str, str]:
        # Invertimos el mapa hw -> excel_column.
        for excel_col, hw in excel_to_hw.items():
            if hw == name.replace("N_MAX_DISP_", "").lower():
                return {"name": name, "hw_type": hw, "excel_column": excel_col}
        return {}

    cm.get_nmax_entry.side_effect = _entry
    return cm


def _add_n_max_table(
    wb: Workbook,
    sheet_name: str,
    rows: list[dict[str, Any]],
) -> None:
    """Anade (o reemplaza) la tabla ``Tabla_Dimensiones`` en ``sheet_name``.

    La tabla vive en la hoja ``CONFIG`` (igual que ``Tabla_PLC``
    y ``Tabla_Procesos``). Anteriormente el nombre era ``Tabla_Dispositivos``
    (rename operativo al integrar N_MAX_ENT en la misma hoja).
    """
    if sheet_name not in wb.sheetnames:
        ws = wb.create_sheet(sheet_name)
    else:
        ws = wb[sheet_name]
    # Cabecera canonica + PLC + 6 columnas + N_Max_ENT (entregada
    # al final para tests legacy que no la setean: queda en None -> 0).
    headers = ["PLC", "N_Max_ED", "N_Max_EA", "N_Max_SA",
               "N_Max_V", "N_Max_M", "N_Max_M_VF", "N_Max_ENT"]
    # Borrar contenido previo (incluyendo cualquier cabecera previa).
    if ws.max_row > 0:
        ws.delete_rows(1, ws.max_row)
    # Borrar tablas previas en esta hoja.
    for tname in list(ws.tables.keys()):
        del ws.tables[tname]
    # Escribir cabecera + fila de datos.
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    last_col_letter = chr(ord("A") + len(headers) - 1)
    last_row = ws.max_row
    ref = f"A1:{last_col_letter}{last_row}"
    from openpyxl.worksheet.table import Table
    table = Table(displayName=N_MAX_TABLE_NAME, ref=ref)
    ws.add_table(table)


# ---------------------------------------------------------------------------
# Tests de extraccion basica
# ---------------------------------------------------------------------------


def test_extrae_una_fila_por_plc(tmp_path):
    """Tabla con 2 PLCs -> DimensionesPLC con 2 DataDimensionesPLC."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": 10, "N_Max_EA": 20, "N_Max_SA": 30,
         "N_Max_V": 40, "N_Max_M": 50, "N_Max_M_VF": 60},
        {"PLC": "PLC2", "N_Max_ED": 100, "N_Max_EA": 200, "N_Max_SA": 300,
         "N_Max_V": 400, "N_Max_M": 500, "N_Max_M_VF": 600},
    ])

    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)

    assert len(result.por_plc) == 2
    by_plc = {d.plc_name: d for d in result.por_plc}
    assert by_plc["PLC1"].extras == {
        "N_MAX_DISP_ED": 10, "N_MAX_DISP_EA": 20, "N_MAX_DISP_SA": 30,
        "N_MAX_DISP_V": 40, "N_MAX_DISP_M": 50, "N_MAX_DISP_M_VF": 60,
    }
    assert by_plc["PLC2"].extras == {
        "N_MAX_DISP_ED": 100, "N_MAX_DISP_EA": 200, "N_MAX_DISP_SA": 300,
        "N_MAX_DISP_V": 400, "N_MAX_DISP_M": 500, "N_MAX_DISP_M_VF": 600,
    }


def test_normaliza_sufijo_a_canonico(tmp_path):
    """``N_Max_ED`` -> ``N_MAX_DISP_ED`` (sufijo en mayusculas)."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": 7},
    ])
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)
    assert len(result.por_plc) == 1
    assert result.por_plc[0].plc_name == "PLC1"
    assert result.por_plc[0].extras.get("N_MAX_DISP_ED") == 7


def test_fila_sin_plc_se_descarta(tmp_path):
    """Filas sin ``PLC`` -> se descartan con WARNING."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": 5},
        {"PLC": "", "N_Max_ED": 999},       # PLC vacio: descartada.
        {"PLC": None, "N_Max_EA": 888},     # PLC None: descartada.
    ])
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)
    assert len(result.por_plc) == 1
    assert result.por_plc[0].plc_name == "PLC1"


def test_celda_vacia_o_no_numerica_es_cero(tmp_path):
    """Celdas vacias o no numericas -> 0 (validacion soft, sin error)."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": "", "N_Max_EA": None, "N_Max_SA": "abc"},
    ])
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)
    assert len(result.por_plc) == 1
    extras = result.por_plc[0].extras
    assert extras.get("N_MAX_DISP_ED") == 0
    assert extras.get("N_MAX_DISP_EA") == 0
    assert extras.get("N_MAX_DISP_SA") == 0


def test_tabla_inexistente_devuelve_contenedor_vacio(tmp_path):
    """Excel sin la tabla -> DimensionesPLC() con por_plc vacio (no rompe)."""
    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("CONFIG")
    # No anadimos ninguna ListObject.
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)
    assert isinstance(result, DimensionesPLC)
    assert result.por_plc == ()


def test_with_config_manager_excel_column(tmp_path):
    """Modo data-driven: usa ``excel_column`` del catalog.

    Si el Excel tiene una columna llamada ``N_Max_XX`` que NO esta en
    el catalog, se ignora (modo strict).
    """
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1",
         "N_Max_ED": 50,
         "N_Max_ColInexistente": 999},  # NO esta en catalog: ignorada.
    ])
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)
    assert len(result.por_plc) == 1
    extras = result.por_plc[0].extras
    # Solo la columna del catalog se incluye.
    assert "N_MAX_DISP_ED" in extras
    assert extras["N_MAX_DISP_ED"] == 50


def test_to_api_dict_shape_anidado(tmp_path):
    """``to_api_dict()`` devuelve ``{plc_name: {nmax_name: int}}`` (multi-PLC)."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": 10, "N_Max_EA": 20},
        {"PLC": "PLC2", "N_Max_ED": 100},
    ])
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)
    api = result.to_api_dict()
    assert "PLC1" in api
    assert "PLC2" in api
    assert api["PLC1"]["N_MAX_DISP_ED"] == 10
    assert api["PLC1"]["N_MAX_DISP_EA"] == 20
    assert api["PLC1"]["N_MAX_ENTIDAD"] == 0  # sin setear -> 0
    assert api["PLC2"]["N_MAX_DISP_ED"] == 100
    assert api["PLC2"]["N_MAX_ENTIDAD"] == 0


# ---------------------------------------------------------------------------
# Tests de N_MAX_ENTIDADES (columna ``N_Max_ENT``)
# ---------------------------------------------------------------------------


def test_n_max_entidades_se_popula_por_plc(tmp_path):
    """Columna ``N_MAX_ENTIDAD`` se popula en ``n_max_entidades`` del DTO."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": 10, "N_Max_ENT": 50},
        {"PLC": "PLC2", "N_Max_ED": 100, "N_Max_ENT": 75},
    ])
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)

    by_plc = {d.plc_name: d for d in result.por_plc}
    assert by_plc["PLC1"].n_max_entidades == 50
    assert by_plc["PLC2"].n_max_entidades == 75
    # Sanity: la columna N_MAX_ENT NO se filtra por el catalog.
    assert "N_Max_ENT" not in by_plc["PLC1"].extras


def test_n_max_entidades_celda_vacia_es_cero(tmp_path):
    """Celda ``N_MAX_ENTIDAD`` vacia -> ``n_max_entidades=0`` (back-compat)."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": 10},
    ])
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)

    assert len(result.por_plc) == 1
    assert result.por_plc[0].n_max_entidades == 0


def test_n_max_entidades_to_api_dict_incluye_por_plc(tmp_path):
    """``to_api_dict()`` emite ``N_MAX_ENTIDAD`` por PLC."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": 10, "N_Max_ENT": 50},
        {"PLC": "PLC2", "N_Max_ENT": 75},
    ])
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)
    api = result.to_api_dict()

    assert api["PLC1"]["N_MAX_ENTIDAD"] == 50
    assert api["PLC2"]["N_MAX_ENTIDAD"] == 75


def test_n_max_entidades_se_ignora_si_ausente_en_excel(tmp_path):
    """Si la columna ``N_Max_ENT`` no esta, ``n_max_entidades=0``.

    Back-compat con Excels legacy sin la columna ``N_Max_ENT``.
    """
    wb = Workbook()
    wb.remove(wb.active)
    # Construimos una tabla SIN la columna N_Max_ENT.
    headers = ["PLC", "N_Max_ED", "N_Max_EA"]
    ws = wb.create_sheet("CONFIG")
    ws.append(headers)
    ws.append(["PLC1", 10, 20])
    last_col_letter = chr(ord("A") + len(headers) - 1)
    from openpyxl.worksheet.table import Table
    table = Table(displayName="Tabla_Dimensiones",
                  ref=f"A1:{last_col_letter}{ws.max_row}")
    ws.add_table(table)

    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)

    assert len(result.por_plc) == 1
    assert result.por_plc[0].n_max_entidades == 0


def test_n_max_entidades_0_no_se_ignora(tmp_path):
    """Operario pone ``N_MAX_ENTIDAD=0`` explicitamente (reset): se respeta."""
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": 10, "N_Max_ENT": 0},
    ])
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)

    assert result.por_plc[0].n_max_entidades == 0
    # to_api_dict lo emite siempre (incluido 0) para que el
    # consumidor no tenga que distinguir "ausente" vs "valor 0".
    assert result.to_api_dict()["PLC1"]["N_MAX_ENTIDAD"] == 0


def test_data_dimensiones_plc_inmutable(tmp_path):
    """``DataDimensionesPLC`` es frozen: no se puede reasignar ``plc_name``.

    ``extras`` es un ``Mapping`` (read-only via ``MappingProxyType``),
    no se puede mutar. La validacion aqui es solo conceptual (no
    levantara ``FrozenInstanceError`` en dataclass para un Mapping).
    """
    from dataclasses import FrozenInstanceError
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": 1},
    ])
    cm = _config_manager_for_tests(tmp_path)
    parser = DimensionesParser(config_manager=cm)
    result = parser.extraer(wb)
    dim_plc = result.por_plc[0]
    # plc_name es field frozen: reasignar lanza FrozenInstanceError.
    with pytest.raises(FrozenInstanceError):
        dim_plc.plc_name = "OTRO"
    # extras es Mapping (inmutable por diseño).


def test_extraer_logea_debug_en_exito(caplog):
    """El parser emite ``logger.debug`` al terminar con exito (oct-2026).

    Antes solo logueaba cuando la tabla no existia; el caso normal
    (tabla existe, se extraen PLCs) quedaba silencioso y el operario
    no podia saber si el parser se ejecutaba o no. Mismo formato que
    los otros parsers (disp_sa.py:130, disp_ea.py:131).
    """
    import logging
    wb = Workbook()
    wb.remove(wb.active)
    _add_n_max_table(wb, "CONFIG", [
        {"PLC": "PLC1", "N_Max_ED": 10},
        {"PLC": "PLC2", "N_Max_ED": 20},
    ])
    cm = _config_manager_for_tests(None)
    parser = DimensionesParser(config_manager=cm)
    with caplog.at_level(
        logging.DEBUG,
        logger="areas.alimentacion.helpers.excel.excel_parser_disp_dimensiones",
    ):
        result = parser.extraer(wb)
    assert any(
        "Tabla_Dimensiones" in r.message and "2 filas" in r.message
        and "2 PLCs" in r.message
        for r in caplog.records
    ), (
        "El parser deberia emitir un logger.debug con formato "
        "'Parser[CONFIG/Tabla_Dimensiones]: 2 filas -> 2 PLCs "
        "extraidos'. Sin este log, el operario no puede saber si el "
        "parser se ejecuto o no (bug oct-2026)."
    )
    assert len(result.por_plc) == 2


def test_extraer_logea_debug_cuando_tabla_no_existe(caplog):
    """Si la tabla no existe, el log de debug sigue siendo consistente.

    Misma ruta que el resto de parsers que avisa con WARNING/DEBUG
    cuando la ``ListObject`` no esta presente.
    """
    import logging
    wb = Workbook()
    wb.remove(wb.active)
    wb.create_sheet("CONFIG")  # sin tabla
    cm = _config_manager_for_tests(None)
    parser = DimensionesParser(config_manager=cm)
    with caplog.at_level(
        logging.DEBUG,
        logger="areas.alimentacion.helpers.excel.excel_parser_disp_dimensiones",
    ):
        result = parser.extraer(wb)
    assert any(
        "Tabla_Dimensiones" in r.message and "no encontrada" in r.message
        for r in caplog.records
    )
    assert result.por_plc == ()
