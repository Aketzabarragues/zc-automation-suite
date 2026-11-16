"""Las rutas del area de alimentacion: el Excel maestro, los dispositivos,
las entidades y los procesos.

- ``GET  /excel``            el volcado que tiene el backend.
- ``POST /excel``            sube un ``.xlsx`` y encola su parseo.
- ``POST /dispositivos/preview``    encola la prevision de los dispositivos.
- ``POST /dispositivos/sincronizar`` encola la sincronizacion contra TIA.
- ``POST /entidades/preview``    encola la prevision de las entidades.
- ``POST /entidades/sincronizar`` encola la sincronizacion contra TIA.
- ``POST /procesos/preview``    encola la prevision de un proceso.
- ``POST /procesos/sincronizar`` encola la sincronizacion de un proceso.
- ``GET  /procesos/plantillas``    las plantillas de procesos disponibles.
- ``PUT  /procesos/plantillas``    guarda la ruta de las plantillas en el
  ``config.json`` del usuario y recarga el config en memoria.
- ``POST /procesos/crear/preview``    encola la prevision de crear un proceso
  desde una plantilla.
- ``POST /procesos/crear/aplicar``    encola la creacion del proceso desde
  la plantilla.

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
from zc_suite.areas.alimentacion.funciones.procesos.crear import (
    crear as proc_crear_aplicar,
)
from zc_suite.areas.alimentacion.funciones.procesos.generar_prevision import (
    generar_prevision as proc_generar_prevision,
)
from zc_suite.areas.alimentacion.funciones.procesos.generar_prevision_crear import (
    carpeta_plantillas,
)
from zc_suite.areas.alimentacion.funciones.procesos.generar_prevision_crear import (
    generar_prevision_crear as proc_crear_prevision,
)
from zc_suite.areas.alimentacion.funciones.procesos.sincronizar import (
    sincronizar as proc_sincronizar,
)
from zc_suite.areas.alimentacion.procesos.plantillas import proc_listar_plantillas
from zc_suite.nucleo.app.config import ConfigError
from zc_suite.nucleo.sesion import CLAVE_SESION, Sesion
from zc_suite.nucleo.web.app import (
    CLAVE_RECARGA_CONFIG,
    HTTPError,
    lanzar,
    servicio,
)

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


@rutas.post("/procesos/preview")
def preview_procesos() -> tuple[Response, int]:
    """Encola la prevision del proceso del PLC.

    Las precondiciones se comprueban **antes** de encolar: si falta el PLC,
    el ``proc_uid``, el Excel o la conexion con TIA, se responde con el
    mensaje y no se lanza ningun trabajo.
    """
    error = _precondiciones("generar la prevision")
    if error is not None:
        return jsonify({"error": error}), 400
    error = _precondicion_proc_uid("generar la prevision")
    if error is not None:
        return jsonify({"error": error}), 400

    almacen = _almacen()
    return lanzar(
        proc_generar_prevision,
        proc_uid=_proc_uid(),
        plc=_plc(),
        almacen=almacen,
        config=almacen.config,
        sesion=_sesion(),
    )


@rutas.post("/procesos/sincronizar")
def sincronizar_procesos() -> tuple[Response, int]:
    """Encola la sincronizacion del proceso del PLC.

    Las precondiciones se comprueban **antes** de encolar: si falta el PLC,
    el ``proc_uid``, el Excel o la conexion con TIA, se responde con el
    mensaje y no se lanza ningun trabajo.
    """
    error = _precondiciones("sincronizar")
    if error is not None:
        return jsonify({"error": error}), 400
    error = _precondicion_proc_uid("sincronizar")
    if error is not None:
        return jsonify({"error": error}), 400

    almacen = _almacen()
    return lanzar(
        proc_sincronizar,
        proc_uid=_proc_uid(),
        plc=_plc(),
        almacen=almacen,
        config=almacen.config,
        sesion=_sesion(),
    )


@rutas.get("/procesos/plantillas")
def listar_plantillas_procesos() -> tuple[Response, int]:
    """Las plantillas de procesos de la carpeta del config.

    Siempre responde ``200``: si la carpeta no existe o no se puede leer,
    la lista sale vacia y el aviso lo explica (el frontend puede mostrar
    un CTA "configura la ruta" sin tratarlo como error).
    """
    almacen = _almacen()
    if almacen.config is None:
        error = "El config del area no es valido: revisa el config.json en uso."
        return jsonify({"error": error}), 400
    plantillas_carpeta = carpeta_plantillas(None, almacen.config)
    if plantillas_carpeta is None:
        # Cadena vacia en el config: "sin configurar". No se toca el disco:
        # el frontend muestra el CTA "configura la ruta" sin tratarlo como
        # error (como main).
        return jsonify(
            {
                "plantillas": [],
                "plantillas_path": "",
                "aviso": "La ruta de plantillas no esta configurada.",
            }
        ), 200
    plantillas, aviso = proc_listar_plantillas(plantillas_carpeta)
    return jsonify(
        {
            "plantillas": plantillas,
            "plantillas_path": str(plantillas_carpeta),
            "aviso": aviso,
        }
    ), 200


@rutas.put("/procesos/plantillas")
def guardar_ruta_plantillas() -> tuple[Response, int]:
    """Guarda la ruta de las plantillas en el ``config.json`` del usuario.

    Body: ``{"plantillas_path": str}``. La cadena vacia es valida (resetea a
    "sin configurar"). El ``config.json`` se escribe de forma atomica
    (``.tmp`` + rename) y se recarga en memoria: el siguiente GET y los FB
    ven la nueva ruta sin reiniciar la app.

    ``200`` con ``{ok, plantillas_path}``; ``400`` si el body no es un dict
    o ``plantillas_path`` no es str; ``500`` si no se puede escribir el
    config (permisos, disco lleno) o si la recarga falla.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "El body debe ser un JSON de objetos."}), 400
    if "plantillas_path" not in body or not isinstance(body["plantillas_path"], str):
        return jsonify({"error": "plantillas_path debe ser str."}), 400
    nueva_ruta = body["plantillas_path"]

    recargar = current_app.config.get(CLAVE_RECARGA_CONFIG)
    if recargar is None:
        return jsonify({"error": "No se puede guardar: la app no esta montada."}), 500
    try:
        ruta = recargar(ID, "plantillas_procesos", nueva_ruta)
    except ConfigError as exc:
        return jsonify({"error": str(exc)}), 500
    logger.info(
        "Ruta de plantillas de %s guardada: %r (%s)",
        ID,
        nueva_ruta,
        ruta,
    )
    return jsonify({"ok": True, "plantillas_path": nueva_ruta, "ruta": str(ruta)}), 200


@rutas.post("/procesos/crear/preview")
def preview_crear_proceso() -> tuple[Response, int]:
    """Encola la prevision de crear un proceso desde una plantilla.

    Las precondiciones se comprueban **antes** de encolar: si falta el PLC,
    el ``proc_uid`` o el nombre de la plantilla, el Excel o la conexion con
    TIA, se responde con el mensaje y no se lanza ningun trabajo.
    """
    error = _precondiciones("generar la prevision")
    if error is not None:
        return jsonify({"error": error}), 400
    error = _precondicion_proc_uid("generar la prevision")
    if error is not None:
        return jsonify({"error": error}), 400
    error = _precondicion_dir_plantilla("generar la prevision")
    if error is not None:
        return jsonify({"error": error}), 400

    almacen = _almacen()
    return lanzar(
        proc_crear_prevision,
        proc_uid=_proc_uid(),
        plc=_plc(),
        dir_plantilla_nombre=_dir_plantilla(),
        almacen=almacen,
        config=almacen.config,
        sesion=_sesion(),
    )


@rutas.post("/procesos/crear/aplicar")
def aplicar_crear_proceso() -> tuple[Response, int]:
    """Encola la creacion de un proceso desde una plantilla.

    Las precondiciones se comprueban **antes** de encolar: si falta el PLC,
    el ``proc_uid`` o el nombre de la plantilla, el Excel o la conexion con
    TIA, se responde con el mensaje y no se lanza ningun trabajo.
    """
    error = _precondiciones("crear el proceso")
    if error is not None:
        return jsonify({"error": error}), 400
    error = _precondicion_proc_uid("crear el proceso")
    if error is not None:
        return jsonify({"error": error}), 400
    error = _precondicion_dir_plantilla("crear el proceso")
    if error is not None:
        return jsonify({"error": error}), 400

    almacen = _almacen()
    return lanzar(
        proc_crear_aplicar,
        proc_uid=_proc_uid(),
        plc=_plc(),
        dir_plantilla_nombre=_dir_plantilla(),
        almacen=almacen,
        config=almacen.config,
        sesion=_sesion(),
    )


def _plc() -> str:
    """El PLC que pide la peticion."""
    datos = request.get_json(silent=True) or {}
    return str(datos.get("plc") or "").strip()


def _proc_uid() -> int | None:
    """El ``proc_uid`` que pide la peticion, o ``None`` si no es valido.

    Valido es un ``int`` (sin contar el ``bool``, que en Python es un ``int``)
    mayor que cero, o un ``str`` de solo digitos. Cualquier otra cosa
    (``"abc"``, ``[1]``, ``true``, ``0``, ``-5``, ``null``...) no es un
    proceso: la ruta responde con 400.
    """
    datos = request.get_json(silent=True) or {}
    valor = datos.get("proc_uid")
    if isinstance(valor, bool) or not isinstance(valor, int):
        if isinstance(valor, str) and valor.isdigit():
            return int(valor)
        return None
    if valor <= 0:
        return None
    return valor


def _precondicion_proc_uid(accion: str) -> str | None:
    """El motivo por el que falta el proceso, o ``None`` si va."""
    if _proc_uid() is None:
        return f"Indica el proceso que quieres {accion}."
    return None


def _dir_plantilla() -> str:
    """El nombre de la subcarpeta de la plantilla que pide la peticion."""
    datos = request.get_json(silent=True) or {}
    return str(datos.get("dir_plantilla_nombre") or "").strip()


def _precondicion_dir_plantilla(accion: str) -> str | None:
    """El motivo por el que falta la plantilla, o ``None`` si va.

    El nombre debe ser una subcarpeta simple dentro de la carpeta de
    plantillas: sin barras (relativas o absolutas) ni ``..``. El FB lo
    revalida al resolver la carpeta.
    """
    nombre = _dir_plantilla()
    if not nombre:
        return f"Indica la plantilla que quieres usar para {accion}."
    if "/" in nombre or "\\" in nombre or ".." in nombre:
        return (
            f"El nombre de la plantilla es invalido: {nombre!r}. Usa el nombre "
            "de la subcarpeta, sin barras ni rutas."
        )
    return None


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
