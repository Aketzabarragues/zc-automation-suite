"""Las rutas del area de alimentacion: el Excel maestro.

- ``GET  /excel``          el volcado que tiene el backend.
- ``POST /excel``          sube un ``.xlsx`` y encola su parseo.
- ``POST /excel/recargar`` vuelve a parsear la copia guardada.

Las POST responden ``202`` con el ``job_id``: el parseo va en un trabajo y su
resultado llega por el stream de eventos, no en la respuesta.

Las dependencias se leen de ``current_app.config``. El router no importa
singletons: el area registra su almacen al montarse.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from zc_suite.areas.alimentacion.excel import trabajo
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.web import HTTPError, lanzar

logger = logging.getLogger(__name__)

#: Identificador del area.
ID = "alimentacion"

#: Clave del almacen del area en ``current_app.config``.
CLAVE_ALMACEN = "ZC_ALMACEN_ALIMENTACION"

#: Extension de los ficheros admitidos.
EXTENSION = ".xlsx"

#: Tamano maximo del fichero, en bytes.
TAMANO_MAXIMO = 20 * 1024 * 1024

#: Campo del multipart donde va el fichero.
CAMPO_FICHERO = "fichero"

#: Prefijo de la carpeta temporal donde se deja la subida.
PREFIJO_TEMPORAL = "zc_excel_"

rutas = Blueprint(f"area_{ID}", __name__, url_prefix=f"/api/v1/areas/{ID}")


@rutas.get("/excel")
def ver_excel() -> Response:
    """El volcado del Excel que tiene el backend."""
    return jsonify(_almacen().estado())


@rutas.post("/excel")
def subir_excel() -> tuple[Response, int]:
    """Sube un Excel y encola su parseo."""
    fichero = request.files.get(CAMPO_FICHERO)
    if fichero is None or not fichero.filename:
        return jsonify({"error": "No se ha enviado ningun fichero."}), 400
    nombre = Path(fichero.filename).name
    if Path(nombre).suffix.lower() != EXTENSION:
        return jsonify({"error": f"Solo se admiten ficheros {EXTENSION}."}), 400
    contenido = fichero.stream.read(TAMANO_MAXIMO + 1)
    if len(contenido) > TAMANO_MAXIMO:
        return jsonify({"error": "El fichero es demasiado grande (maximo 20 MB)."}), 400

    ruta = _guardar(contenido, nombre)
    return lanzar(trabajo.cargar_excel, ruta=str(ruta), almacen=_almacen())


@rutas.post("/excel/recargar")
def recargar_excel() -> tuple[Response, int]:
    """Vuelve a parsear la copia guardada del Excel."""
    return lanzar(trabajo.recargar_excel, almacen=_almacen())


def _almacen() -> AlmacenExcel:
    """La cache del Excel del area.

    Raises:
        HTTPError: si el area no esta registrada en la app.
    """
    valor = current_app.config.get(CLAVE_ALMACEN)
    if valor is None:
        raise HTTPError("El almacen del Excel del area no esta registrado.", 500)
    return valor


def _guardar(contenido: bytes, nombre: str) -> Path:
    """Deja el fichero subido en un temporal y devuelve su ruta."""
    carpeta = Path(tempfile.mkdtemp(prefix=PREFIJO_TEMPORAL))
    ruta = carpeta / (Path(nombre).stem + EXTENSION)
    ruta.write_bytes(contenido)
    return ruta


def registrar(app: Any) -> None:
    """Monta las rutas del area en la app.

    El area se registra sola en ``zc_suite.main``. Esta funcion es para las
    pruebas, que montan la app sin el nucleo completo.
    """
    app.register_blueprint(rutas)
