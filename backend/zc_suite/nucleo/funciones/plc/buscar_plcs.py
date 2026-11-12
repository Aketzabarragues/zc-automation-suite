"""zc_suite.nucleo.funciones.plc.buscar_plcs — lista los PLCs del proyecto.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero
dentro del hilo de TIA.
"""
from __future__ import annotations

import logging
from typing import Any

from zc_suite.nucleo.tia.job import Job
from zc_suite.tia_ops.proyecto import info_proyecto, listar_plcs

logger = logging.getLogger(__name__)


def buscar_plcs(job: Job) -> dict[str, Any]:
    """Los PLCs del proyecto abierto y los datos del proyecto.

    Returns:
        ``{"plcs": [{"nombre", "designacion"}], "proyecto": {"nombre", "ruta"}}``.
    """
    job.empezar("Buscar PLCs", [("listar", "Listar los PLCs del proyecto")])
    with job.paso("listar") as paso:
        plcs = listar_plcs(job.tia.portal)
        proyecto = info_proyecto(job.tia.portal)
        paso["detail"] = f"{len(plcs)} PLCs"
    return {"plcs": plcs, "proyecto": proyecto}
