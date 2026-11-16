"""zc_suite.nucleo.funciones.plc.escanear — escanea el PLC.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero
dentro del hilo de TIA.
"""
from __future__ import annotations

import logging
import time
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
    inicio_total = time.perf_counter()
    with job.paso("bloques") as paso:
        inicio = time.perf_counter()
        bloques = escanear_bloques(job.tia.portal, plc)
        logger.debug(
            "Fase bloques: %d bloques en %.2f s", len(bloques), time.perf_counter() - inicio
        )
        paso["detail"] = f"{len(bloques)} bloques"
    with job.paso("tablas") as paso:
        inicio = time.perf_counter()
        tablas = escanear_tablas_tags(job.tia.portal, plc)
        logger.debug(
            "Fase tablas: %d tablas de tags en %.2f s", len(tablas), time.perf_counter() - inicio
        )
        paso["detail"] = f"{len(tablas)} tablas de tags"
    with job.paso("tipos") as paso:
        inicio = time.perf_counter()
        tipos = escanear_tipos_de_usuario(job.tia.portal, plc)
        logger.debug(
            "Fase tipos: %d tipos de usuario en %.2f s", len(tipos), time.perf_counter() - inicio
        )
        paso["detail"] = f"{len(tipos)} tipos de usuario"
    logger.debug(
        "Escaneo de %s: %d bloques, %d tablas, %d tipos en %.2f s",
        plc,
        len(bloques),
        len(tablas),
        len(tipos),
        time.perf_counter() - inicio_total,
    )
    sesion.guardar_escaneo(plc, bloques, tablas, tipos)
    return {"plc": plc, "bloques": bloques, "tablas": tablas, "tipos": tipos}
