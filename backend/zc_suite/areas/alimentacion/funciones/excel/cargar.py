"""zc_suite.areas.alimentacion.funciones.excel.cargar — carga el Excel maestro.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero
dentro del hilo de TIA.

**No exige conexion con TIA**: no toca el portal. Corre en el hilo de TIA,
que es donde se ejecutan los trabajos de la app, pero no necesita que haya
un proyecto abierto.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.dispositivos import CLAVE_PREVISION as CLAVE_PREVISION_DISPOSITIVOS
from zc_suite.areas.alimentacion.entidades import CLAVE_PREVISION as CLAVE_PREVISION_ENTIDADES
from zc_suite.areas.alimentacion.excel import almacen as modulo_almacen
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.errores import OperacionError
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job

#: Identificador del area.
AREA = "alimentacion"

logger = logging.getLogger(__name__)

#: Prefijo de la carpeta temporal donde se deja la subida.
PREFIJO_TEMPORAL = "zc_excel_"


def cargar(
    job: Job,
    ruta: str,
    almacen: AlmacenExcel,
    sesion: Sesion | None = None,
) -> dict[str, Any]:
    """Parsea el fichero indicado y lo deja en la cache del area.

    Args:
        job: el trabajo en curso.
        ruta: el fichero ``.xlsx`` o ``.xlsm`` a parsear.
        almacen: la cache del area.
        sesion: la sesion del backend. Un Excel nuevo deja sin valor la
            prevision de dispositivos guardada, asi que se borra.

    Returns:
        ``{"archivo", "cargado_en", "plcs", "filas", "avisos"}``.
    """
    job.empezar(
        "Parsear y volcar Excel",
        [
            ("validar", "Validar el fichero"),
            ("parsear", "Parsear el Excel"),
            ("avisos", "Revisar los avisos"),
        ],
    )
    fichero = Path(ruta)
    try:
        with job.paso("validar") as paso:
            if not fichero.is_file():
                raise OperacionError(f"No se encontro el Excel: '{fichero}'.")
            paso["detail"] = fichero.name

        with job.paso("parsear") as paso:
            datos = almacen.volcar(fichero)
            paso["detail"] = f"{len(datos['plcs'])} PLCs"
    finally:
        _limpiar_temporal(fichero)

    if sesion is not None:
        sesion.borrar_dato_area(AREA, CLAVE_PREVISION_DISPOSITIVOS)
        sesion.borrar_dato_area(AREA, CLAVE_PREVISION_ENTIDADES)

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


def _limpiar_temporal(fichero: Path) -> None:
    """Borra la carpeta temporal de la subida, si lo es."""
    if fichero.parent.name.startswith(PREFIJO_TEMPORAL):
        shutil.rmtree(fichero.parent, ignore_errors=True)
