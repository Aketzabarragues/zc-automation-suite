"""zc_suite.areas.alimentacion.funciones.excel.recargar — recarga el Excel.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero
dentro del hilo de TIA.

**No exige conexion con TIA**: no toca el portal.
"""
from __future__ import annotations

import logging
from typing import Any

from zc_suite.areas.alimentacion.excel import almacen as modulo_almacen
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.errores import OperacionError
from zc_suite.nucleo.tia.job import Job

logger = logging.getLogger(__name__)


def recargar(job: Job, almacen: AlmacenExcel) -> dict[str, Any]:
    """Vuelve a parsear la copia guardada del Excel.

    Args:
        job: el trabajo en curso.
        almacen: la cache del area.

    Returns:
        ``{"archivo", "cargado_en", "plcs", "filas", "avisos"}``.
    """
    job.empezar(
        "Recargar el Excel",
        [
            ("buscar", "Buscar la copia guardada"),
            ("parsear", "Parsear el Excel"),
            ("avisos", "Revisar los avisos"),
        ],
    )
    with job.paso("buscar") as paso:
        ruta = modulo_almacen.ruta_persistida()
        if ruta is None:
            raise OperacionError("No hay ningun Excel guardado para recargar.")
        paso["detail"] = ruta.name

    with job.paso("parsear") as paso:
        datos = almacen.volcar(ruta)
        paso["detail"] = f"{len(datos['plcs'])} PLCs"

    avisos = modulo_almacen.avisos(almacen)
    with job.paso("avisos") as paso:
        paso["detail"] = modulo_almacen.detalle_de_avisos(avisos)
        for aviso in avisos:
            job.log(aviso, nivel="aviso")

    return {
        "archivo": almacen.archivo,
        "cargado_en": almacen.cargado_en,
        "plcs": list(datos["plcs"]),
        "filas": modulo_almacen.filas_totales(datos),
        "avisos": avisos,
    }
