"""Tests del FB que aplica los cambios a los bloques."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zc_suite.nucleo.funciones.bloques.aplicar import aplicar
from zc_suite.nucleo.sesion import Sesion


def test_editar_aplica_los_cambios_y_refresca(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
    pasos: Callable[[list[tuple[str, dict[str, Any]]]], list[str]],
) -> None:
    servicio, _ts, bloques, eventos = entorno

    job_id = servicio.lanzar(
        aplicar,
        plc="ZC_PLC_STD",
        cambios={"DB10": {"Name": "DB10_NUEVO"}},
        sesion=Sesion(),
    )
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert pasos(eventos) == [
        "validar",
        "diferencias",
        "aplicar",
        "verificar",
        "refrescar",
    ]
    assert bloques[0].get_name() == "DB10_NUEVO"
    refrescados = evento["resultado"]["bloques"]
    assert [bloque["nombre"] for bloque in refrescados] == ["DB10_NUEVO", "OB1_MAIN"]


def test_editar_sin_cambios_falla(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(aplicar, plc="ZC_PLC_STD", cambios={}, sesion=Sesion())
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "No hay cambios" in evento["error"]


def test_editar_actualiza_el_escaneo_de_la_sesion(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
) -> None:
    """Tras aplicar, el escaneo del PLC refleja los nombres nuevos."""
    servicio, _ts, _bloques, eventos = entorno
    sesion = Sesion()
    sesion.guardar_escaneo(
        "ZC_PLC_STD",
        [{"nombre": "DB10"}, {"nombre": "OB1_MAIN"}],
        [{"nombre": "2000_Disp_ED"}],
        [],
    )

    job_id = servicio.lanzar(
        aplicar,
        plc="ZC_PLC_STD",
        cambios={"DB10": {"Name": "DB10_NUEVO"}},
        sesion=sesion,
    )
    esperar_job(eventos, job_id)

    escaneo = sesion.escaneo("ZC_PLC_STD")
    assert escaneo is not None
    assert [bloque["nombre"] for bloque in escaneo.bloques] == ["DB10_NUEVO", "OB1_MAIN"]
    # Las tablas de tags no cambian al renombrar un bloque: se conservan.
    assert escaneo.tablas == [{"nombre": "2000_Disp_ED"}]


def test_editar_sin_escaneo_previo_no_inventa_uno(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
) -> None:
    """Un escaneo con solo bloques no vale: no se crea."""
    servicio, _ts, _bloques, eventos = entorno
    sesion = Sesion()

    job_id = servicio.lanzar(
        aplicar,
        plc="ZC_PLC_STD",
        cambios={"DB10": {"Name": "DB10_NUEVO"}},
        sesion=sesion,
    )
    esperar_job(eventos, job_id)

    assert sesion.escaneo("ZC_PLC_STD") is None
