"""zc_suite.nucleo.trabajos.plc — los trabajos del PLC.

- ``buscar_plcs``: los PLCs del proyecto abierto y los datos del proyecto.
- ``escanear_plc``: los bloques, las tablas de tags y los tipos de usuario.
"""
from __future__ import annotations

import logging
from typing import Any

from zc_suite.nucleo.tia.job import Job
from zc_suite.tia_ops.bloques import escanear_bloques, escanear_tipos_de_usuario
from zc_suite.tia_ops.proyecto import info_proyecto, listar_plcs
from zc_suite.tia_ops.tablas import escanear_tablas_tags

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


def escanear_plc(job: Job, plc: str) -> dict[str, Any]:
    """Escanea el PLC: bloques, tablas de tags y tipos de usuario.

    Returns:
        ``{"plc", "bloques", "tablas", "tipos"}``.
    """
    job.empezar(
        f"Escanear {plc}",
        [
            ("bloques", "Escanear bloques"),
            ("tablas", "Escanear tablas de tags"),
            ("tipos", "Escanear tipos de usuario"),
        ],
    )
    with job.paso("bloques") as paso:
        bloques = escanear_bloques(job.tia.portal, plc)
        paso["detail"] = f"{len(bloques)} bloques"
    with job.paso("tablas") as paso:
        tablas = escanear_tablas_tags(job.tia.portal, plc)
        paso["detail"] = f"{len(tablas)} tablas de tags"
    with job.paso("tipos") as paso:
        tipos = escanear_tipos_de_usuario(job.tia.portal, plc)
        paso["detail"] = f"{len(tipos)} tipos de usuario"
    return {"plc": plc, "bloques": bloques, "tablas": tablas, "tipos": tipos}
