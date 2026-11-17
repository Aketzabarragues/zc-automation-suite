"""zc_suite.nucleo.funciones.plc.listar_plcs — lista los PLCs del proyecto.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero
dentro del hilo de TIA.
"""
from __future__ import annotations

import logging
from typing import Any

from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job
from zc_suite.tia_ops import proyecto

logger = logging.getLogger(__name__)


def listar_plcs(job: Job, sesion: Sesion) -> dict[str, Any]:
    """Los PLCs del proyecto abierto y los datos del proyecto.

    La lista queda en la sesion: es lo que la SPA ve al hidratarse.

    Returns:
        ``{"plcs": [{"nombre", "designacion"}], "proyecto": {"nombre", "ruta"}}``.
    """
    job.empezar("Buscar PLCs", [("listar", "Listar los PLCs del proyecto")])
    with job.paso("listar") as paso:
        plcs = proyecto.listar_plcs(job.tia.portal)
        proyecto_info = proyecto.info_proyecto(job.tia.portal)
        paso["detail"] = f"{len(plcs)} PLCs"
    sesion.guardar_plcs(plcs, proyecto_info)
    return {"plcs": plcs, "proyecto": proyecto_info}
