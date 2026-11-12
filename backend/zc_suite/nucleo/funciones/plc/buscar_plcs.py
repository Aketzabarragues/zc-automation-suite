"""zc_suite.nucleo.funciones.plc.buscar_plcs — lista los PLCs del proyecto.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero
dentro del hilo de TIA.
"""
from __future__ import annotations

import logging
from typing import Any

from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job
from zc_suite.tia_ops.proyecto import info_proyecto, listar_plcs

logger = logging.getLogger(__name__)


def buscar_plcs(job: Job, sesion: Sesion) -> dict[str, Any]:
    """Los PLCs del proyecto abierto y los datos del proyecto.

    La lista queda en la sesion: es lo que la SPA ve al hidratarse.

    Returns:
        ``{"plcs": [{"nombre", "designacion"}], "proyecto": {"nombre", "ruta"}}``.
    """
    job.empezar("Buscar PLCs", [("listar", "Listar los PLCs del proyecto")])
    with job.paso("listar") as paso:
        plcs = listar_plcs(job.tia.portal)
        proyecto = info_proyecto(job.tia.portal)
        paso["detail"] = f"{len(plcs)} PLCs"
    sesion.guardar_plcs(plcs, proyecto)
    return {"plcs": plcs, "proyecto": proyecto}
