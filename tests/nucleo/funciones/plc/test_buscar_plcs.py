"""Tests del FB que lista los PLCs del proyecto."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zc_suite.nucleo.funciones.plc.buscar_plcs import buscar_plcs
from zc_suite.nucleo.sesion import Sesion


def test_buscar_plcs_devuelve_los_plcs_y_el_proyecto(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(buscar_plcs, sesion=Sesion())
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert evento["resultado"]["plcs"] == [{"nombre": "ZC_PLC_STD", "designacion": ""}]
    assert evento["resultado"]["proyecto"]["nombre"] == "ZC_PLC_STD"


def test_buscar_plcs_deja_los_plcs_en_la_sesion(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
) -> None:
    """La lista de PLCs es parte del estado de la sesion."""
    servicio, _ts, _bloques, eventos = entorno
    sesion = Sesion()

    job_id = servicio.lanzar(buscar_plcs, sesion=sesion)
    esperar_job(eventos, job_id)

    assert sesion.plcs == [{"nombre": "ZC_PLC_STD", "designacion": ""}]
    assert sesion.proyecto is not None
    assert sesion.proyecto["nombre"] == "ZC_PLC_STD"
