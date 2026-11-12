"""Tests del FB que escanea el PLC."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zc_suite.nucleo.funciones.plc.escanear import escanear


def test_escanear_plc_devuelve_bloques_tablas_y_tipos(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(escanear, plc="ZC_PLC_STD")
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

    job_id = servicio.lanzar(escanear, plc="ZC_PLC_STD")
    esperar_job(eventos, job_id)

    assert pasos(eventos) == ["bloques", "tablas", "tipos"]
