"""La paridad del resultado de la prevision con la app anterior.

Los valores esperados estan escritos aqui, sacados de ejecutar el codigo real
de ``main`` (``FunctionDispGenerarPreview`` y sus helpers) sobre **el mismo
fixture**: el Excel maestro de ``conftest.py`` y las mismas tablas de TIA.

Lo que se compara es el resultado entero, no una parte: si un campo cambia de
sitio, si aparece uno de mas o si un valor se mueve, el test falla.
"""
from __future__ import annotations

from typing import Any

#: El resultado completo que produce ``main`` con este fixture.
RESULTADO_DE_MAIN: dict[str, Any] = {
    "agregados": [
        {"uid": "4", "table": "2000_Disp_ED", "plc_tag": "ED_004"},
    ],
    "eliminados": [
        {"uid": "99", "table": "2000_Disp_ED", "plc_tag": "ED_099"},
    ],
    "renombrados": [
        {
            "uid": "2",
            "table": "2000_Disp_ED",
            "actual": "ED_002",
            "nuevo": "ED_002_NUEVO",
        },
    ],
    "todos": [
        {
            "table": "2000_Disp_ED",
            "type": "ed",
            "uid": "1",
            "numero": 1,
            "actual": "ED_001",
            "nuevo": "ED_001",
            "status": "sin_cambios",
        },
        {
            "table": "2000_Disp_ED",
            "type": "ed",
            "uid": "2",
            "numero": 2,
            "actual": "ED_002",
            "nuevo": "ED_002_NUEVO",
            "status": "renombrar",
        },
        {
            "table": "2000_Disp_ED",
            "type": "ed",
            "uid": "3",
            "numero": 3,
            "actual": "ED_003",
            "nuevo": "ED_003",
            "status": "sin_cambios",
        },
        {
            "table": "2000_Disp_ED",
            "type": "ed",
            "uid": "4",
            "numero": 4,
            "actual": None,
            "nuevo": "ED_004",
            "status": "agregar",
        },
        {
            "table": "2000_Disp_ED",
            "type": "ed",
            "uid": "99",
            "numero": 99,
            "actual": "ED_099",
            "nuevo": None,
            "status": "eliminar",
        },
    ],
    "nmax": {
        "current": {
            "N_MAX_DISP_EA": 20,
            "N_MAX_DISP_ED": 5,
            "N_MAX_DISP_M_VF": 70,
            "N_MAX_DISP_PID": 115,
            "N_MAX_DISP_TOT": 110,
            "N_MAX_DISP_TQ": 80,
        },
        "desired": {
            "N_MAX_DISP_EA": 20,
            "N_MAX_DISP_ED": 10,
            "N_MAX_DISP_M": 60,
            "N_MAX_DISP_M_SINA": 80,
            "N_MAX_DISP_M_VF": 70,
            "N_MAX_DISP_PID": 120,
            "N_MAX_DISP_SA": 30,
            "N_MAX_DISP_SD": 40,
            "N_MAX_DISP_TOT": 110,
            "N_MAX_DISP_TQ": 90,
            "N_MAX_DISP_TQ_AE": 100,
            "N_MAX_DISP_V": 50,
        },
        "todos": [
            {"name": "N_MAX_DISP_EA", "actual": 20, "nuevo": 20, "status": "sin_cambios"},
            {"name": "N_MAX_DISP_ED", "actual": 5, "nuevo": 10, "status": "actualizar"},
            {"name": "N_MAX_DISP_M", "actual": None, "nuevo": 60, "status": "actualizar"},
            {
                "name": "N_MAX_DISP_M_SINA",
                "actual": None,
                "nuevo": 80,
                "status": "actualizar",
            },
            {
                "name": "N_MAX_DISP_M_VF",
                "actual": 70,
                "nuevo": 70,
                "status": "sin_cambios",
            },
            {
                "name": "N_MAX_DISP_PID",
                "actual": 115,
                "nuevo": 120,
                "status": "actualizar",
            },
            {"name": "N_MAX_DISP_SA", "actual": None, "nuevo": 30, "status": "actualizar"},
            {"name": "N_MAX_DISP_SD", "actual": None, "nuevo": 40, "status": "actualizar"},
            {
                "name": "N_MAX_DISP_TOT",
                "actual": 110,
                "nuevo": 110,
                "status": "sin_cambios",
            },
            {"name": "N_MAX_DISP_TQ", "actual": 80, "nuevo": 90, "status": "actualizar"},
            {
                "name": "N_MAX_DISP_TQ_AE",
                "actual": None,
                "nuevo": 100,
                "status": "actualizar",
            },
            {"name": "N_MAX_DISP_V", "actual": None, "nuevo": 50, "status": "actualizar"},
        ],
        "summary": {"actualizar": 9, "sin_cambios": 3, "total": 12},
        "nmax_error": None,
    },
    "summary": {
        "agregados": 1,
        "eliminados": 1,
        "renombrados": 1,
        "sin_cambios": 2,
        "total": 5,
    },
}


def test_el_resultado_es_igual_al_de_main(entorno_disp: Any) -> None:
    """El resultado entero es el mismo que produce la app anterior."""
    resultado = entorno_disp.prevision()

    assert resultado == RESULTADO_DE_MAIN


def test_el_bloque_de_n_max_no_tiene_claves_de_mas(entorno_disp: Any) -> None:
    """El bloque de N_MAX tiene exactamente las claves de ``main``."""
    resultado = entorno_disp.prevision()

    assert set(resultado["nmax"]) == {"current", "desired", "todos", "summary", "nmax_error"}


def test_cada_fila_del_diff_tiene_las_campos_de_main(entorno_disp: Any) -> None:
    """Cada fila tiene exactamente los campos de ``main``, ni uno mas."""
    resultado = entorno_disp.prevision()

    for fila in resultado["todos"]:
        assert set(fila) == {
            "table",
            "type",
            "uid",
            "numero",
            "actual",
            "nuevo",
            "status",
        }


def test_el_resumen_tiene_las_cinco_cifras_de_main(entorno_disp: Any) -> None:
    """El resumen son las cinco cifras de ``main``."""
    resultado = entorno_disp.prevision()

    assert set(resultado["summary"]) == {
        "agregados",
        "eliminados",
        "renombrados",
        "sin_cambios",
        "total",
    }
