"""La prevision de los procesos.

Exporta del PLC la tabla de variables del proceso y sus dos DBs, y los
compara con el Excel. No escribe nada en TIA.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from zc_suite.nucleo.sesion import Sesion

from .conftest import DB_ALM, DB_PARAM, NOMBRE_PLC, PROC_UID, TABLA_PROCESO


def _sesion_con_escaneo() -> Sesion:
    """Una sesion con el escaneo del PLC: la tabla y los dos DBs."""
    sesion = Sesion()
    sesion.guardar_escaneo(
        NOMBRE_PLC,
        bloques=[{"nombre": DB_PARAM}, {"nombre": DB_ALM}],
        tablas=[{"nombre": TABLA_PROCESO}],
        tipos=[],
    )
    return sesion


def test_la_prevision_exporta_la_tabla_y_los_dbs(
    entorno_prevision: Any, tmp_path: Path
) -> None:
    """El preview deja la tabla y los dos DBs exportados."""
    evento = entorno_prevision.prevision(PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    preview = tmp_path / "procesos" / "preview"
    assert (preview / "disp" / f"{TABLA_PROCESO}.xml").is_file()
    assert (preview / "bloques" / f"{DB_PARAM}.s7dcl").is_file()
    assert (preview / "bloques" / f"{DB_PARAM}.s7res").is_file()
    assert (preview / "bloques" / f"{DB_ALM}.s7dcl").is_file()
    assert (preview / "bloques" / f"{DB_ALM}.s7res").is_file()


def test_la_prevision_devuelve_el_shape(entorno_prevision: Any) -> None:
    """La prevision trae el shape que consume la SPA."""
    evento = entorno_prevision.prevision(PROC_UID, _sesion_con_escaneo())

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["proc_uid"] == PROC_UID
    assert resultado["proc_codigo"] == "CPR"
    assert resultado["precondiciones_ok"] is True
    assert resultado["missing_blocks"] == []
    assert resultado["db_param_name"] == DB_PARAM
    assert resultado["db_alm_name"] == DB_ALM
    assert resultado["table_name"] == TABLA_PROCESO
    assert resultado["db_present"] == {"param": True, "alm": True}
    assert resultado["table_present"] is True


def test_la_prevision_detecta_las_acciones_por_slot(entorno_prevision: Any) -> None:
    """Las acciones de los slots: sin_cambios, renombrar, agregar y eliminar."""
    evento = entorno_prevision.prevision(PROC_UID, _sesion_con_escaneo())

    assert evento["estado"] == "ok", evento.get("error")
    preal = evento["resultado"]["arrays"]["PReal"]["slot_map"]
    assert preal["1"] == {
        "current": "PARAMETRO UNO",
        "desired": "PARAMETRO UNO",
        "action": "sin_cambios",
    }
    # El comentario_db vacio del Excel se mapea a ".".
    assert preal["2"]["desired"] == "."
    assert preal["2"]["current"] == "PARAMETRO DOS"
    assert preal["2"]["action"] == "renombrar"
    # El slot 3 solo esta en TIA: se elimina.
    assert preal["3"]["current"] == "PARAMETRO TRES"
    assert preal["3"]["desired"] is None
    assert preal["3"]["action"] == "eliminar"

    pint = evento["resultado"]["arrays"]["PInt"]["slot_map"]
    assert pint["1"]["action"] == "sin_cambios"

    alm = evento["resultado"]["arrays"]["ALM"]["slot_map"]
    assert alm["1"]["action"] == "sin_cambios"
    assert alm["2"]["action"] == "sin_cambios"
    assert alm["3"]["action"] == "eliminar"


def test_la_prevision_resume_los_arrays(entorno_prevision: Any) -> None:
    """El resumen cuenta los slots por accion."""
    evento = entorno_prevision.prevision(PROC_UID, _sesion_con_escaneo())

    assert evento["estado"] == "ok", evento.get("error")
    arrays = evento["resultado"]["arrays"]
    # Los counts cuentan tambien el placeholder del slot 0.
    assert arrays["PReal"]["current_count"] == 4
    assert arrays["PReal"]["desired_count"] == 3
    assert arrays["PInt"]["current_count"] == 2
    assert arrays["PInt"]["desired_count"] == 2
    assert arrays["ALM"]["current_count"] == 4
    assert arrays["ALM"]["desired_count"] == 3
    assert arrays["PReal"]["satellite_arrays"] == ["PReal_Vis", "Aux.PReal_ValorAnterior"]
    assert arrays["ALM"]["satellite_arrays"] == []
    assert evento["resultado"]["summary"] == {
        "total": 7,
        "agregados": 0,
        "renombrados": 1,
        "eliminados": 2,
        "sin_cambios": 4,
    }


def test_la_prevision_detecta_el_n_max(entorno_prevision: Any) -> None:
    """Los N_MAX del proceso salen del Excel contra el XML de TIA."""
    evento = entorno_prevision.prevision(PROC_UID, _sesion_con_escaneo())

    assert evento["estado"] == "ok", evento.get("error")
    nmax = evento["resultado"]["nmax"]
    assert nmax["current"] == {
        f"{PROC_UID}_N_MAX_PREAL": 3,
        f"{PROC_UID}_N_MAX_PINT": 1,
        f"{PROC_UID}_N_MAX_ALM": 2,
        f"{PROC_UID}_N_MAX_ALM_HMI": 1,
    }
    assert nmax["desired"] == {
        f"{PROC_UID}_N_MAX_PREAL": 2,
        f"{PROC_UID}_N_MAX_PINT": 1,
        f"{PROC_UID}_N_MAX_ALM": 2,
        f"{PROC_UID}_N_MAX_ALM_HMI": 2,
    }
    assert nmax["nmax_error"] is None
    assert nmax["summary"] == {"actualizar": 2, "sin_cambios": 2, "total": 4}
    by_name = {fila["name"]: fila for fila in nmax["todos"]}
    assert by_name[f"{PROC_UID}_N_MAX_PREAL"]["status"] == "actualizar"
    assert by_name[f"{PROC_UID}_N_MAX_PREAL"]["kind"] == "preal"
    assert by_name[f"{PROC_UID}_N_MAX_ALM_HMI"]["status"] == "actualizar"
    assert by_name[f"{PROC_UID}_N_MAX_ALM_HMI"]["kind"] == "alm_hmi"
    assert by_name[f"{PROC_UID}_N_MAX_PINT"]["status"] == "sin_cambios"


def test_la_prevision_avisa_de_el_comentario_vacio(entorno_prevision: Any) -> None:
    """El comentario_db vacio del Excel se mapea a '.' (convencion TIA)."""
    evento = entorno_prevision.prevision(PROC_UID, _sesion_con_escaneo())

    assert evento["estado"] == "ok", evento.get("error")
    preal = evento["resultado"]["arrays"]["PReal"]["slot_map"]
    assert preal["2"]["desired"] == "."


def test_la_prevision_se_guarda_en_la_sesion(entorno_prevision: Any) -> None:
    """La prevision sobrevive a un F5: se guarda en la sesion del backend."""
    sesion = _sesion_con_escaneo()

    evento = entorno_prevision.prevision(PROC_UID, sesion)

    assert evento["estado"] == "ok", evento.get("error")
    guardado = sesion.datos_area("alimentacion").get("prevision_procesos")
    assert guardado is not None
    assert guardado["plc"] == NOMBRE_PLC
    assert guardado["proc_uid"] == PROC_UID
    assert guardado["resultado"]["proc_codigo"] == "CPR"


def test_sin_escaneo_no_hay_precondiciones(entorno_prevision: Any) -> None:
    """Sin escaneo en la sesion, la presencia no se puede comprobar."""
    evento = entorno_prevision.prevision(PROC_UID)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["precondiciones_ok"] is False
    assert resultado["table_present"] is False
    assert resultado["arrays"] == {}
    assert resultado["nmax"]["summary"] == {"actualizar": 0, "sin_cambios": 0, "total": 0}
    assert resultado["summary"] == {
        "total": 0,
        "agregados": 0,
        "renombrados": 0,
        "eliminados": 0,
        "sin_cambios": 0,
    }
    assert resultado["missing_blocks"] == [
        f"Tabla de variables: {TABLA_PROCESO}",
        f"DB de parametros: {DB_PARAM}",
        f"DB de alarmas: {DB_ALM}",
    ]
    assert any(DB_PARAM in aviso for aviso in resultado["warnings"])
    assert any(DB_ALM in aviso for aviso in resultado["warnings"])


def test_falta_un_db_y_se_sigue(entorno_prevision: Any) -> None:
    """Falta un DB solo y se sigue: se omite ese DB, con aviso."""
    sesion = Sesion()
    sesion.guardar_escaneo(
        NOMBRE_PLC,
        bloques=[{"nombre": DB_PARAM}],
        tablas=[{"nombre": TABLA_PROCESO}],
        tipos=[],
    )

    evento = entorno_prevision.prevision(PROC_UID, sesion)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["precondiciones_ok"] is True
    assert resultado["db_present"] == {"param": True, "alm": False}
    assert resultado["missing_blocks"] == []
    assert any(DB_ALM in aviso for aviso in resultado["warnings"])


def test_falta_el_proceso_del_excel(entorno_prevision: Any) -> None:
    """Un uid que no esta en el Excel es un fallo de operacion."""
    evento = entorno_prevision.prevision(999)

    assert evento["estado"] == "error"
    assert "uid=999" in evento["error"]
