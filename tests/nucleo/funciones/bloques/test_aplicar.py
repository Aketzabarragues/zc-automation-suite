"""Tests del FB que aplica los cambios a los bloques."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zc_suite.nucleo.funciones.bloques.aplicar import aplicar


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

    job_id = servicio.lanzar(aplicar, plc="ZC_PLC_STD", cambios={})
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "No hay cambios" in evento["error"]
