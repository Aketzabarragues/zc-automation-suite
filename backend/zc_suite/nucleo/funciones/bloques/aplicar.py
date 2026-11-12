"""zc_suite.nucleo.funciones.bloques.aplicar — aplica cambios a los bloques.

Es un **FB**: recibe el ``job``, declara sus pasos, abre la transaccion y
se ejecuta entero dentro del hilo de TIA.
"""
from __future__ import annotations

import logging
from typing import Any

from zc_suite.errores import OperacionError
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.transaccion import transaccion
from zc_suite.tia_ops.bloques import aplicar_cambios, escanear_bloques

logger = logging.getLogger(__name__)


def aplicar(
    job: Job,
    plc: str,
    cambios: dict[str, dict[str, Any]],
    sesion: Sesion,
) -> dict[str, Any]:
    """Aplica los cambios de nombre y numero de los bloques indicados.

    Todos los cambios van en **una sola transaccion**: si uno falla, se
    deshace todo el lote. Al final se reescanea el PLC, para que el arbol
    de la SPA vea los nombres nuevos, y el escaneo de la sesion queda
    actualizado.

    Returns:
        ``{"plc", "aplicados", "bloques"}``. ``bloques`` es el contenido del
        PLC despues de aplicar.
    """
    job.empezar(
        f"Aplicar cambios en {plc}",
        [
            ("validar", "Validar los cambios"),
            ("diferencias", "Calcular las diferencias"),
            ("aplicar", "Aplicar la transacción"),
            ("verificar", "Verificar el resultado"),
            ("refrescar", "Refrescar los bloques del PLC"),
        ],
    )
    with job.paso("validar") as paso:
        if not cambios:
            raise OperacionError("No hay cambios que aplicar.")
        paso["detail"] = f"{len(cambios)} bloques"
    with job.paso("diferencias") as paso:
        paso["detail"] = ", ".join(sorted(cambios))
    aplicados: list[dict[str, Any]] = []
    with job.paso("aplicar") as paso:
        with transaccion(job, "Editar bloques"):
            for nombre, propiedades in cambios.items():
                aplicados.append(
                    aplicar_cambios(job.tia.portal, plc, nombre, dict(propiedades))
                )
        paso["detail"] = f"{len(aplicados)} bloques"
    with job.paso("verificar") as paso:
        paso["detail"] = f"{len(aplicados)} bloques confirmados"
    with job.paso("refrescar") as paso:
        bloques = escanear_bloques(job.tia.portal, plc)
        sesion.actualizar_bloques(plc, bloques)
        paso["detail"] = f"{len(bloques)} bloques"
    return {"plc": plc, "aplicados": aplicados, "bloques": bloques}
