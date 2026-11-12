"""Tests del FB que escanea el PLC."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zc_suite.nucleo.funciones.plc.escanear import escanear
from zc_suite.nucleo.sesion import Sesion


def test_escanear_plc_devuelve_bloques_tablas_y_tipos(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(escanear, plc="ZC_PLC_STD", sesion=Sesion())
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert len(evento["resultado"]["bloques"]) == 2
    assert evento["resultado"]["tablas"][0]["nombre"] == "2000_Disp_ED"
    assert evento["resultado"]["tipos"] == []


def test_escanear_plc_declara_sus_pasos(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
    pasos: Callable[[list[tuple[str, dict[str, Any]]]], list[str]],
) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(escanear, plc="ZC_PLC_STD", sesion=Sesion())
    esperar_job(eventos, job_id)

    assert pasos(eventos) == ["bloques", "tablas", "tipos"]


def test_escanear_plc_deja_el_escaneo_en_la_sesion(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
) -> None:
    """El escaneo es parte del estado de la sesion: de el sale la vista."""
    servicio, _ts, _bloques, eventos = entorno
    sesion = Sesion()

    job_id = servicio.lanzar(escanear, plc="ZC_PLC_STD", sesion=sesion)
    esperar_job(eventos, job_id)

    escaneo = sesion.escaneo("ZC_PLC_STD")
    assert escaneo is not None
    assert len(escaneo.bloques) == 2
    assert escaneo.tablas[0]["nombre"] == "2000_Disp_ED"
    assert escaneo.caducado() is False
