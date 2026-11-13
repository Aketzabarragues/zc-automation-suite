"""Las rutas del area de alimentacion: el Excel maestro, los dispositivos y
las entidades.

- ``GET  /excel``            el volcado que tiene el backend.
- ``POST /excel``            sube un ``.xlsx`` y encola su parseo.
- ``POST /dispositivos/preview``    encola la prevision de los dispositivos.
- ``POST /dispositivos/sincronizar`` encola la sincronizacion contra TIA.
- ``POST /entidades/preview``    encola la prevision de las entidades.
- ``POST /entidades/sincronizar`` encola la sincronizacion contra TIA.

Las POST responden ``202`` con el ``job_id``: el trabajo va en un trabajo y su
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

from zc_suite.areas.alimentacion.excel.almacen import EXTENSIONES, AlmacenExcel
from zc_suite.areas.alimentacion.funciones.dispositivos.generar_prevision import (
    generar_prevision,
)
from zc_suite.areas.alimentacion.funciones.dispositivos.sincronizar import sincronizar
from zc_suite.areas.alimentacion.funciones.entidades.generar_prevision import (
    generar_prevision as ent_generar_prevision,
)
from zc_suite.areas.alimentacion.funciones.entidades.sincronizar import (
    sincronizar as ent_sincronizar,
)
from zc_suite.areas.alimentacion.funciones.excel.cargar import cargar
from zc_suite.nucleo.sesion import CLAVE_SESION, Sesion
from zc_suite.nucleo.web.app import HTTPError, lanzar, servicio

logger = logging.getLogger(__name__)

#: Identificador del area.
ID = "alimentacion"

#: Clave del almacen del area en ``current_app.config``.
CLAVE_ALMACEN = "ZC_ALMACEN_ALIMENTACION"

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
    sufijo = Path(nombre).suffix.lower()
    if sufijo not in EXTENSIONES:
        admitidas = " o ".join(EXTENSIONES)
        return jsonify({"error": f"Solo se admiten ficheros {admitidas}."}), 400
    contenido = fichero.stream.read(TAMANO_MAXIMO + 1)
    if len(contenido) > TAMANO_MAXIMO:
        return jsonify({"error": "El fichero es demasiado grande (maximo 20 MB)."}), 400

    ruta = _guardar(contenido, nombre, sufijo)
    return lanzar(cargar, ruta=str(ruta), almacen=_almacen(), sesion=_sesion())


@rutas.post("/dispositivos/preview")
def preview_dispositivos() -> tuple[Response, int]:
    """Encola la prevision de dispositivos del PLC.

    Las precondiciones se comprueban **antes** de encolar: si falta el Excel,
    la conexion con TIA o el PLC, se responde con el mensaje y no se lanza
    ningun trabajo.
    """
    error = _precondiciones("generar la prevision")
    if error is not None:
        return jsonify({"error": error}), 400

    almacen = _almacen()
    return lanzar(
        generar_prevision,
        plc=_plc(),
        almacen=almacen,
        config=almacen.config,
        sesion=_sesion(),
    )


@rutas.post("/dispositivos/sincronizar")
def sincronizar_dispositivos() -> tuple[Response, int]:
    """Encola la sincronizacion de los dispositivos del PLC.

    Las precondiciones se comprueban **antes** de encolar: si falta el Excel,
    la conexion con TIA o el PLC, se responde con el mensaje y no se lanza
    ningun trabajo.
    """
    error = _precondiciones("sincronizar")
    if error is not None:
        return jsonify({"error": error}), 400

    almacen = _almacen()
    return lanzar(
        sincronizar,
        plc=_plc(),
        almacen=almacen,
        config=almacen.config,
        sesion=_sesion(),
    )


@rutas.post("/entidades/preview")
def preview_entidades() -> tuple[Response, int]:
    """Encola la prevision de las entidades del PLC.

    Las precondiciones se comprueban **antes** de encolar: si falta el Excel,
    la conexion con TIA o el PLC, se responde con el mensaje y no se lanza
    ningun trabajo.
    """
    error = _precondiciones("generar la prevision")
    if error is not None:
        return jsonify({"error": error}), 400

    almacen = _almacen()
    return lanzar(
        ent_generar_prevision,
        plc=_plc(),
        almacen=almacen,
        config=almacen.config,
        sesion=_sesion(),
    )


@rutas.post("/entidades/sincronizar")
def sincronizar_entidades() -> tuple[Response, int]:
    """Encola la sincronizacion de las entidades del PLC.

    Las precondiciones se comprueban **antes** de encolar: si falta el Excel,
    la conexion con TIA o el PLC, se responde con el mensaje y no se lanza
    ningun trabajo.
    """
    error = _precondiciones("sincronizar")
    if error is not None:
        return jsonify({"error": error}), 400

    almacen = _almacen()
    return lanzar(
        ent_sincronizar,
        plc=_plc(),
        almacen=almacen,
        config=almacen.config,
        sesion=_sesion(),
    )


def _plc() -> str:
    """El PLC que pide la peticion."""
    datos = request.get_json(silent=True) or {}
    return str(datos.get("plc") or "").strip()


def _precondiciones(accion: str) -> str | None:
    """El motivo por el que no se puede lanzar el trabajo, o ``None``.

    Comprueba el PLC, el Excel y la conexion con TIA, en ese orden: lo que
    falta primero es lo que el operario tiene que arreglar primero.
    """
    if not _plc():
        return f"Elige un PLC antes de {accion}."
    almacen = _almacen()
    if not almacen.estado()["cargado"]:
        return "No hay Excel cargado. Sube el Excel maestro primero."
    if not servicio().conectado:
        return f"TIA Portal no esta conectado. Conectate antes de {accion}."
    if almacen.config is None:
        return "El config del area no es valido: revisa el config.json en uso."
    return None


def _almacen() -> AlmacenExcel:
    """La cache del Excel del area.

    Raises:
        HTTPError: si el area no esta registrada en la app.
    """
    valor = current_app.config.get(CLAVE_ALMACEN)
    if valor is None:
        raise HTTPError("El almacen del Excel del area no esta registrado.", 500)
    return valor


def _sesion() -> Sesion | None:
    """La sesion del backend, o ``None`` si la app no la registra (tests)."""
    return current_app.config.get(CLAVE_SESION)


def _guardar(contenido: bytes, nombre: str, sufijo: str) -> Path:
    """Deja el fichero subido en un temporal y devuelve su ruta.

    La extension se conserva: el temporal tiene que seguir siendo legible
    por ``openpyxl`` como ``.xlsx`` o como ``.xlsm``.
    """
    carpeta = Path(tempfile.mkdtemp(prefix=PREFIJO_TEMPORAL))
    ruta = carpeta / (Path(nombre).stem + sufijo)
    ruta.write_bytes(contenido)
    return ruta


def registrar(app: Any) -> None:
    """Monta las rutas del area en la app.

    El area se registra sola en ``zc_suite.nucleo.app.main``. Esta funcion es para las
    pruebas, que montan la app sin el nucleo completo.
    """
    app.register_blueprint(rutas)
