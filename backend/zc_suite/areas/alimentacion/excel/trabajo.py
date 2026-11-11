"""Los trabajos del Excel maestro: cargar un fichero y recargar la copia.

Los dos trabajos **no exigen conexion con TIA**: no tocan el portal. Corren en
el hilo de TIA, que es donde se ejecutan los trabajos de la app, pero no
necesitan que haya un proyecto abierto.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.excel import almacen as modulo_almacen
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.tia import Job
from zc_suite.tia_ops import OperacionError

logger = logging.getLogger(__name__)

#: Prefijo de la carpeta temporal donde se deja la subida.
PREFIJO_TEMPORAL = "zc_excel_"


def cargar_excel(job: Job, ruta: str, almacen: AlmacenExcel) -> dict[str, Any]:
    """Parsea el fichero indicado y lo deja en la cache del area.

    Args:
        job: el trabajo en curso.
        ruta: el fichero ``.xlsx`` o ``.xlsm`` a parsear.
        almacen: la cache del area.

    Returns:
        ``{"archivo", "cargado_en", "plcs", "filas", "avisos"}``.
    """
    job.empezar(
        "Parsear y volcar Excel",
        [
            ("validar", "Validar el fichero"),
            ("parsear", "Parsear el Excel"),
            ("guardar", "Guardar la copia"),
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

        with job.paso("guardar") as paso:
            copia = almacen.persistir(fichero)
            paso["detail"] = str(copia)
    finally:
        _limpiar_temporal(fichero)

    avisos = _avisos(almacen)
    with job.paso("avisos") as paso:
        paso["detail"] = _detalle_de_avisos(avisos)
        for aviso in avisos:
            job.log(aviso, nivel="aviso")

    return {
        "archivo": almacen.archivo,
        "cargado_en": almacen.cargado_en,
        "plcs": list(datos["plcs"]),
        "filas": _filas_totales(datos),
        "avisos": avisos,
    }


def recargar_excel(job: Job, almacen: AlmacenExcel) -> dict[str, Any]:
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

    avisos = _avisos(almacen)
    with job.paso("avisos") as paso:
        paso["detail"] = _detalle_de_avisos(avisos)
        for aviso in avisos:
            job.log(aviso, nivel="aviso")

    return {
        "archivo": almacen.archivo,
        "cargado_en": almacen.cargado_en,
        "plcs": list(datos["plcs"]),
        "filas": _filas_totales(datos),
        "avisos": avisos,
    }


def _filas_totales(datos: dict[str, Any]) -> int:
    """Cuantas filas hay en todos los dominios del volcado."""
    total = len(datos.get("configuracion", {}).get("filas", []))
    for tabla in datos.get("dispositivos", []):
        total += len(tabla.get("filas", []))
    for tabla in datos.get("procesos", {}).values():
        total += len(tabla.get("filas", []))
    total += len(datos.get("entidades", {}).get("filas", []))
    return total


def _avisos(almacen: AlmacenExcel) -> list[str]:
    """Los avisos del ultimo parseo."""
    return list(almacen.estado().get("avisos") or [])


def _detalle_de_avisos(avisos: list[str]) -> str:
    """El detalle del paso de avisos: el primero y cuantos quedan."""
    if not avisos:
        return "sin avisos"
    if len(avisos) == 1:
        return avisos[0]
    return f"{avisos[0]} (+{len(avisos) - 1} más)"


def _limpiar_temporal(fichero: Path) -> None:
    """Borra la carpeta temporal de la subida, si lo es."""
    if fichero.parent.name.startswith(PREFIJO_TEMPORAL):
        shutil.rmtree(fichero.parent, ignore_errors=True)
