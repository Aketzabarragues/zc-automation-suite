"""zc_suite.nucleo.funciones.plc.escanear — escanea el PLC.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero
dentro del hilo de TIA.
"""
from __future__ import annotations

import logging
from typing import Any

from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job
from zc_suite.tia_ops.bloques import escanear_bloques, escanear_tipos_de_usuario
from zc_suite.tia_ops.tablas import escanear_tablas_tags

logger = logging.getLogger(__name__)


def escanear(job: Job, plc: str, sesion: Sesion) -> dict[str, Any]:
    """Escanea el PLC: bloques, tablas de tags y tipos de usuario.

    El escaneo queda en la sesion, con su momento: mientras no caduque, no
    hace falta volver a escanear.

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
    sesion.guardar_escaneo(plc, bloques, tablas, tipos)
    return {"plc": plc, "bloques": bloques, "tablas": tablas, "tipos": tipos}
