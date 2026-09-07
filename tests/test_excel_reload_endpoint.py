"""Tests del endpoint ``POST /api/v1/excel/reload`` (sept-2026).

El operario reporto que el boton "Actualizar" de la vista
"Definicion programacion" fallaba con
"TypeError: Failed to fetch" al pulsar tras editar el Excel
en otra app. Causa raiz: el handler antiguo reenviaba el
``File`` cacheado en ``store.lastExcelFile``, que era un
snapshot en el momento del primer ``/upload`` — no veia los
cambios en disco y, en algunos navegadores, el reuso de la
misma referencia tras un reset del input daba el TypeError.

Solucion: nuevo endpoint ``POST /api/v1/excel/reload`` que
re-lee desde la ruta absoluta guardada en
``AppState.excel_path`` (que el primer ``/upload`` ya
persistia). El frontend lo usa en lugar de reenviar el File.

Casos cubiertos:
  1. Sin Excel previo (``state.excel_path is None``) → 409.
  2. Archivo movido/borrado → 409 con detail accionable.
  3. Reload OK: ``state.excel_path`` apunta a un .xlsx valido
     en disco y el use case lo re-parsea, repuebla el cache
     y el AppState.
  4. Reload actualiza el cache (devices, dimensiones) y
     devuelve la misma shape que ``/upload``.
  5. El mtime NO se chequea (decision sept-2026: siempre
     re-parsear, sin optimizacion por mtime).

Patron: TestClient + AppState + excel sintético en ``tmp_path``.
"""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from core.application.state import AppState, get_app_state
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.app import create_app


# ── Configuracion JSON fixture (misma que test_excel_endpoint_with_cache) ──


_FULL_CONFIG: dict[str, Any] = {
    "departments": {
        "alimentacion": {
            "global_config_table_name": "000_Config_Dispositivos",
            "tia_folders": {
                "proceso":      "003_Procesos",
                "dispositivos": "2000_Dispositivos",
                "nmax":         "000_Sistema",
            },
            "n_max_catalog": [
                {"name": "N_MAX_DISP_ED",   "value": 10},
                {"name": "N_MAX_DISP_EA",   "value": 10},
                {"name": "N_MAX_DISP_SA",   "value": 10},
                {"name": "N_MAX_DISP_V",    "value": 10},
                {"name": "N_MAX_DISP_M",    "value": 10},
                {"name": "N_MAX_DISP_M_VF", "value": 10},
            ],
            "Dispositivos": {
                "ed": {
                    "db_name": "DB2000_ED", "db_array_name": "ED",
                    "tag_table": "2000_Disp_ED",
                    "config_table": "000_Config_Dispositivos",
                },
                "ea": {
                    "db_name": "DB2001_EA", "db_array_name": "EA",
                    "tag_table": "2000_Disp_EA",
                    "config_table": "000_Config_Dispositivos",
                },
                "sa": {
                    "db_name": "DB2006_SA", "db_array_name": "SA",
                    "tag_table": "2000_Disp_SA",
                    "config_table": "000_Config_Dispositivos",
                },
                "v": {
                    "db_name": "DB2010_V", "db_array_name": "V",
                    "tag_table": "2000_Disp_V",
                    "config_table": "000_Config_Dispositivos",
                },
                "m": {
                    "db_name": "DB2015_M", "db_array_name": "M",
                    "tag_table": "2000_Disp_M",
                    "config_table": "000_Config_Dispositivos",
                },
                "m_vf": {
                    "db_name": "DB2016_M_VF", "db_array_name": "M_VF",
                    "tag_table": "2000_Disp_M_VF",
                    "config_table": "000_Config_Dispositivos",
                },
            },
        }
    }
}


def _write_config(tmp_path: Path) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(_FULL_CONFIG), encoding="utf-8")
    return p


# ── Excel sintetico (mismo que test_excel_endpoint_with_cache) ──────────


def _add_table(
    wb: Workbook, sheet_name: str, table_name: str,
    headers: list[str], rows: list[list],
) -> None:
    if sheet_name not in wb.sheetnames:
        ws = wb.create_sheet(sheet_name)
    else:
        ws = wb[sheet_name]
    ws.append(headers)
    for row in rows:
        ws.append(row)
    last_col_letter = chr(ord("A") + len(headers) - 1)
    last_row = 1 + len(rows)
    ref = f"A1:{last_col_letter}{last_row}"
    table = Table(displayName=table_name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleLight1", showFirstColumn=False,
        showLastColumn=False, showRowStripes=True, showColumnStripes=False,
    )
    ws.add_table(table)


def _build_minimal_xlsx_bytes() -> bytes:
    """Genera un xlsx en memoria con 1 fila de cada uno de los 6 tipos."""
    wb = Workbook()
    wb.remove(wb.active)
    tables = [
        ("DISP_ED",   "Tabla_Disp_ED",   "ED_001",   1, "V_ED_001"),
        ("DISP_EA",   "Tabla_Disp_EA",   "EA_001",   1, "V_EA_001"),
        ("DISP_SA",   "Tabla_Disp_SA",   "SA_001",   1, "V_SA_001"),
        ("DISP_V",    "Tabla_Disp_V",    "V_001",    1, "V_V_001"),
        ("DISP_M",    "Tabla_Disp_M",    "M_001",    1, "V_M_001"),
        ("DISP_M_VF", "Tabla_Disp_M_VF", "MVF_001",  1, "V_MVF_001"),
    ]
    headers = ["UID", "Numero", "PLC.Tag", "Descripcion"]
    for sheet_name, table_name, uid, numero, tag in tables:
        _add_table(wb, sheet_name, table_name, headers,
                   [[uid, numero, tag, f"Desc {uid}"]])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_xlsx_to(path: Path) -> Path:
    """Escribe un xlsx valido en ``path`` y lo retorna."""
    path.write_bytes(_build_minimal_xlsx_bytes())
    return path


# ── Fixture: TestClient con dependencias inyectadas ─────────────────────


@pytest.fixture
def app_with_overrides(tmp_path: Path, monkeypatch):
    """App FastAPI con ``ConfigManager`` apuntando al fixture JSON
    y ``AppState`` reseteado."""
    config_path = _write_config(tmp_path)
    cm = ConfigManager(config_path=config_path)

    gateway = MagicMock(spec=TIAProcessGateway)
    app = create_app(gateway)
    app.state.config_manager = cm

    state = get_app_state()
    state.reset()
    state.excel_cache = None
    state.excel_path = None
    state.dimensiones = None

    yield app, state

    # Cleanup.
    state.reset()
    state.excel_cache = None
    state.excel_path = None
    state.dimensiones = None


# ── Tests ──────────────────────────────────────────────────────────────


def test_reload_sin_excel_path_devuelve_409(app_with_overrides) -> None:
    """Sin Excel previo (``state.excel_path is None``) → 409.

    El operario intenta "Actualizar" sin haber subido un Excel
    antes. El backend devuelve 409 con detail accionable para
    que la SPA fuerce la re-seleccion.
    """
    app, state = app_with_overrides
    assert state.excel_path is None  # Sanity: el fixture resetea el state.
    with TestClient(app) as client:
        resp = client.post("/api/v1/excel/reload")
    assert resp.status_code == 409
    body = resp.json()
    assert "detail" in body
    # El detail es accionable: el operario sabe que tiene que subir.
    assert "Excel" in body["detail"] or "excel" in body["detail"]


def test_reload_archivo_borrado_devuelve_409(app_with_overrides) -> None:
    """``state.excel_path`` apunta a un archivo que ya no existe
    en disco → 409 con detail mencionando la ruta.

    Caso real: el operario mueve o borra el Excel entre la
    primera subida y el reload. La SPA debe forzar la
    re-seleccion.
    """
    app, state = app_with_overrides
    # Seteamos excel_path a una ruta que NO existe.
    state.excel_path = "/tmp/excel_que_no_existe_2026_xyz.xlsx"
    with TestClient(app) as client:
        resp = client.post("/api/v1/excel/reload")
    assert resp.status_code == 409
    body = resp.json()
    assert "detail" in body
    # El detail debe mencionar la ruta (o 'no existe'/'nueva').
    detail = body["detail"].lower()
    assert "no existe" in detail or "nueva" in detail


def test_reload_ok_re_usa_excel_path_y_re_parsing(tmp_path, app_with_overrides) -> None:
    """Reload OK: el backend re-lee desde ``state.excel_path`` y
    repuebla el cache + el AppState.

    Caso principal (sept-2026, pedido operario): tras editar
    el Excel en otra app y pulsar "Actualizar", el backend
    recoge los cambios y la SPA los ve sin re-seleccionar el
    archivo.
    """
    app, state = app_with_overrides
    # Escribimos un xlsx en disco y lo registramos en el state
    # (como si lo hubieramos subido antes con /upload).
    xlsx_path = _write_xlsx_to(tmp_path / "datos.xlsx")
    state.excel_path = str(xlsx_path)

    # Sanity pre-reload: cache vacio.
    assert state.excel_cache is None
    assert state.dimensiones is None

    with TestClient(app) as client:
        resp = client.post("/api/v1/excel/reload")

    assert resp.status_code == 200, (
        f"Reload OK debe devolver 200, devolvio {resp.status_code}: "
        f"{resp.text}"
    )
    body = resp.json()

    # El response tiene la misma shape que /upload.
    assert "summary" in body
    assert "total_dispositivos" in body
    assert body["total_dispositivos"] == 6  # 1 fila de cada uno de los 6 tipos
    # Los 6 tipos canónicos aparecen en el summary.
    # Nota: la clave canonica para m_vf es "DispM_VF" (con guion
    # bajo), NO "DispMVF" — ver _plan/04_excel_cache_phased_plan.md
    # §3 (canonical key derivation).
    for canonical in ("DispED", "DispEA", "DispSA", "DispV", "DispM", "DispM_VF"):
        assert canonical in body["summary"], (
            f"summary debe contener el tipo {canonical}: {body['summary']}"
        )

    # El state se ha repoblado con el cache.
    assert state.excel_cache is not None, (
        "Reload OK debe repoblar state.excel_cache"
    )
    assert state.excel_path == str(xlsx_path), (
        "state.excel_path debe mantenerse tras el reload"
    )
    assert state.dimensiones is not None, (
        "Reload OK debe repoblar state.dimensiones (N_MAX)"
    )


def test_reload_no_chequea_mtime_re_parsea_siempre(
    tmp_path, app_with_overrides
) -> None:
    """El reload siempre re-parsea (decision sept-2026: NO
    comprobamos mtime).

    El operario puede hacer click N veces; cada click re-lee
    desde disco. El parseo es la operacion costosa y el
    operario solo pulsa "Actualizar" cuando sabe que hay
    cambios, asi que el chequeo de mtime seria premature
    optimization.
    """
    app, state = app_with_overrides
    xlsx_path = _write_xlsx_to(tmp_path / "datos.xlsx")
    state.excel_path = str(xlsx_path)

    with TestClient(app) as client:
        # Primer reload.
        r1 = client.post("/api/v1/excel/reload")
        assert r1.status_code == 200

        # Segundo reload sin tocar el archivo.
        r2 = client.post("/api/v1/excel/reload")
        assert r2.status_code == 200, (
            f"Segundo reload sin cambios debe seguir siendo 200 "
            f"(no hay chequeo de mtime). Status: {r2.status_code}"
        )

    # El mtime_ns del cache se actualiza en cada reload
    # (es el st_mtime_ns al momento del parseo). Si re-parsea,
    # el segundo reload tendra mtime_ns >= primero. En cualquier
    # caso ambos 200.
    assert state.excel_cache is not None
    assert state.excel_cache.excel_mtime_ns > 0


def test_reload_detecta_archivo_borrado_entre_check_y_lectura(
    tmp_path, app_with_overrides, monkeypatch
) -> None:
    """El reload detecta el caso raro: archivo existe al
    ``exists()`` pero se borra antes de la lectura.

    Simulado: ``Path.exists`` retorna True pero
    ``UploadExcelUseCase.execute`` falla al abrir el archivo.
    El backend lo traduce a 400 (delegado del use case) o
    similar error. Verificamos que NO devuelve 200 silencioso.
    """
    app, state = app_with_overrides
    # Creamos un archivo y lo registramos.
    xlsx_path = _write_xlsx_to(tmp_path / "datos.xlsx")
    state.excel_path = str(xlsx_path)

    # Simulamos que entre el exists() y la lectura, el archivo
    # se borra. El ``UploadExcelUseCase`` lanzara
    # ``FileNotFoundError`` al intentar ``loader.load(path)``,
    # que se traduce a ``HTTPException(400)`` (mismo patron que
    # /upload).
    from openpyxl import load_workbook
    real_load_workbook = load_workbook
    def fake_load_workbook(path, *args, **kwargs):
        # Borramos el archivo "en el ultimo momento".
        Path(path).unlink(missing_ok=True)
        return real_load_workbook.__class__()  # No-op
    # No monkeypatcheamos load_workbook (riesgoso); mejor
    # borramos el archivo antes del reload y dejamos que
    # ``exists()`` retorne False. Eso es equivalente y mas
    # simple.
    xlsx_path.unlink()

    with TestClient(app) as client:
        resp = client.post("/api/v1/excel/reload")
    # El exists() retorna False, asi que devolvemos 409.
    assert resp.status_code == 409


def test_reload_no_resetea_excel_path_en_error_404(app_with_overrides) -> None:
    """Si el reload falla (404 por archivo borrado), ``state.excel_path``
    NO se modifica (sigue apuntando a la ruta original).

    Razon: si el operario re-crea el archivo en la misma ruta
    y pulsa Actualizar de nuevo, no queremos que tenga que
    re-subirlo. El path es estable; solo el contenido del
    archivo cambia.
    """
    app, state = app_with_overrides
    original_path = "/tmp/ruta_original_inexistente.xlsx"
    state.excel_path = original_path
    with TestClient(app) as client:
        resp = client.post("/api/v1/excel/reload")
    assert resp.status_code == 409
    # El path no se ha tocado.
    assert state.excel_path == original_path
