"""zc_suite.web — app Flask, estaticos y el stream de eventos.

El shell HTTP es Flask. Sus dependencias (el hilo de TIA y el bus de
eventos) viven en ``current_app.config``; los routers las leen de ahi y
nunca importan singletons globales.

Contratos:

- ``GET /api/eventos`` es el stream SSE con los cuatro tipos de evento.
- ``lanzar(funcion, **params)`` encola un trabajo y responde ``202`` con el
  ``job_id``. Si hay un trabajo en curso, responde ``409``.
- Las POST comprueban la cabecera ``Origin``: solo se aceptan las que
  vienen de la propia app.
- La SPA se sirve desde ``frontend/dist``. La ruta no acepta ``..``.
"""
from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from flask import Flask, Response, current_app, jsonify, request, send_from_directory

from zc_suite.eventos import (
    BusCerradoError,
    BusEventos,
    HandlerEventos,
    Suscripcion,
    conectar_logging,
)
from zc_suite.tia import OcupadoError, ServicioTIA

#: Claves de las dependencias en ``current_app.config``.
CLAVE_SERVICIO = "ZC_TIA"
CLAVE_BUS = "ZC_BUS"
CLAVE_DIST = "ZC_DIST"
CLAVE_ORIGENES = "ZC_ORIGENES"
CLAVE_DESARROLLO = "ZC_DESARROLLO"

#: Puerto de escucha por defecto.
PUERTO_POR_DEFECTO = 9484

#: Hosts a los que responde la app. La app es local: no escucha mas que en
#: loopback. La lista es fija y no se deduce de la cabecera ``Host``.
HOSTS_PERMITIDOS = ("127.0.0.1", "localhost")

#: Origenes de la SPA en desarrollo (Vite). Solo se aceptan si la app se
#: arranca en modo desarrollo.
ORIGENES_DEV = frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})

#: Metodos que no llevan cabecera ``Origin`` y no se comprueban.
METODOS_SIN_ORIGEN = ("GET", "HEAD", "OPTIONS")

#: Segundos entre keep-alive del stream SSE.
TIMEOUT_SSE = 15.0


class HTTPError(Exception):
    """Error con codigo HTTP propio."""

    def __init__(self, mensaje: str, codigo: int = 400) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


# ── dependencias ───────────────────────────────────────────────────────────


def servicio() -> ServicioTIA:
    """El hilo de TIA de la aplicacion.

    Raises:
        HTTPError: si la dependencia no esta registrada.
    """
    valor = current_app.config.get(CLAVE_SERVICIO)
    if valor is None:
        raise HTTPError("El hilo de TIA no esta registrado.", 500)
    return valor


def bus() -> BusEventos:
    """El bus de eventos de la aplicacion.

    Raises:
        HTTPError: si la dependencia no esta registrada.
    """
    valor = current_app.config.get(CLAVE_BUS)
    if valor is None:
        raise HTTPError("El bus de eventos no esta registrado.", 500)
    return valor


# ── stream de eventos ──────────────────────────────────────────────────────


def stream_eventos(bus_eventos: BusEventos, timeout: float = TIMEOUT_SSE) -> Iterator[str]:
    """Genera el cuerpo del stream SSE.

    Cada evento sale como ``data: {...}``. Cuando solo vence el timeout se
    emite un comentario SSE, que es lo que mantiene viva la conexion sin
    inventar un quinto tipo de evento.

    La suscripcion se abre al llamar a esta funcion y no al empezar a
    iterar: si no, se perderian los eventos que lleguen entre la peticion y
    el primer ``next``.
    """
    return _stream_susripcion(bus_eventos.suscribir(), timeout)


def _stream_susripcion(suscriptor: Suscripcion, timeout: float) -> Iterator[str]:
    """Cuerpo del stream a partir de una suscripcion ya abierta."""
    try:
        while True:
            evento = suscriptor.siguiente(timeout=timeout)
            if evento is None:
                yield ": keep-alive\n\n"
            else:
                yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
    except BusCerradoError:
        return
    finally:
        suscriptor.cerrar()


# ── encolado de trabajos ───────────────────────────────────────────────────


def lanzar(funcion: Callable[..., Any], **params: Any) -> tuple[Response, int]:
    """Encola un trabajo y responde con su identificador.

    Returns:
        Tupla ``(respuesta, codigo)``: ``202`` si el trabajo se ha encolado,
        ``409`` si ya hay un trabajo en curso.
    """
    try:
        job_id = servicio().lanzar(funcion, **params)
    except OcupadoError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify({"job_id": job_id}), 202


# ── origen de las peticiones ───────────────────────────────────────────────


def origenes_permitidos() -> set[str]:
    """Origenes que pueden hacer POST.

    La lista es fija: se construye con el puerto de escucha y no con la
    cabecera ``Host`` de la peticion, que controla el atacante. Un POST con
    ``Host`` y ``Origin`` iguales a un dominio ajeno devuelve ``403``.
    """
    puerto = current_app.config.get("ZC_PUERTO", PUERTO_POR_DEFECTO)
    permitidos = {f"http://{host}:{puerto}" for host in HOSTS_PERMITIDOS}
    if current_app.config.get(CLAVE_DESARROLLO):
        permitidos |= set(current_app.config.get(CLAVE_ORIGENES) or ())
    return permitidos


def exigir_origen() -> None:
    """Rechaza las POST que no vengan de la propia app.

    Raises:
        HTTPError: ``403`` si falta la cabecera ``Origin`` o si el origen no
            esta permitido.
    """
    origen = request.headers.get("Origin")
    if not origen:
        raise HTTPError("Falta la cabecera Origin.", 403)
    if origen not in origenes_permitidos():
        raise HTTPError(f"Origen no permitido: {origen}", 403)


def exigir_host() -> None:
    """Rechaza las peticiones cuyo ``Host`` no sea uno de los de loopback.

    Se aplica a todas las peticiones, no solo a las POST: un ``Host``
    ajeno significa que el navegador esta hablando con otra maquina.

    Raises:
        HTTPError: ``403`` si el ``Host`` no cuadra.
    """
    puerto = current_app.config.get("ZC_PUERTO", PUERTO_POR_DEFECTO)
    permitidos = {f"{host}:{puerto}" for host in HOSTS_PERMITIDOS}
    host = request.headers.get("Host", "")
    if host not in permitidos:
        raise HTTPError(f"Host no permitido: {host}", 403)


# ── estaticos ──────────────────────────────────────────────────────────────


def ruta_dist_frontend() -> Path:
    """Ruta del build de la SPA."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", "")) / "frontend" / "dist"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def servir_spa(dist: Path, camino: str) -> Response:
    """Sirve un fichero de la SPA o su ``index.html``.

    Raises:
        HTTPError: ``404`` si la ruta se sale de la carpeta o si el frontend
            no esta compilado.
    """
    if not dist.is_dir():
        raise HTTPError(
            "El frontend no esta compilado. Ejecuta 'npm run build' en frontend/.",
            404,
        )
    raiz = dist.resolve()
    if camino:
        destino = (raiz / camino).resolve()
        if raiz not in destino.parents:
            raise HTTPError("Ruta no valida.", 404)
        if destino.is_file():
            return send_from_directory(raiz, camino)
    return send_from_directory(raiz, "index.html")


# ── app ────────────────────────────────────────────────────────────────────


def crear_app(
    servicio_tia: ServicioTIA,
    bus_eventos: BusEventos,
    dist_frontend: Path | None = None,
    origenes: set[str] | None = None,
    desarrollo: bool = False,
    puerto: int = PUERTO_POR_DEFECTO,
) -> Flask:
    """Crea la app Flask con sus dependencias registradas.

    Args:
        servicio_tia: el hilo de TIA.
        bus_eventos: el bus de eventos.
        dist_frontend: carpeta del build de la SPA. Por defecto,
            ``frontend/dist`` del repo.
        origenes: origenes extra permitidos. Solo se usan en modo
            desarrollo.
        desarrollo: si es ``True``, se admiten los origenes del servidor de
            Vite. En produccion solo se admiten los de la propia app.
        puerto: puerto de escucha. Marca los origenes y los ``Host``
            validos.
    """
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    app.config[CLAVE_SERVICIO] = servicio_tia
    app.config[CLAVE_BUS] = bus_eventos
    app.config[CLAVE_DIST] = dist_frontend or ruta_dist_frontend()
    app.config[CLAVE_ORIGENES] = set(origenes) if origenes is not None else set(ORIGENES_DEV)
    app.config[CLAVE_DESARROLLO] = desarrollo
    app.config["ZC_PUERTO"] = puerto
    _conectar_logging(bus_eventos)
    _registrar_rutas(app)
    return app


def _conectar_logging(bus_eventos: BusEventos) -> None:
    """Engancha el bus al logger ``zc_suite``.

    No se engancha al root: el root tambien recibe los logs de las librerias
    de terceros, y la consola de la SPA solo quiere los de la app.

    Sustituye el puente anterior: solo puede haber uno, o cada linea de log
    se publicaria tantas veces como apps se hayan creado.
    """
    logger_padre = logging.getLogger("zc_suite")
    for handler in list(logger_padre.handlers):
        if isinstance(handler, HandlerEventos):
            logger_padre.removeHandler(handler)
    conectar_logging(bus_eventos, logger_padre)


def _registrar_rutas(app: Flask) -> None:
    """Monta las rutas del nucleo."""

    @app.before_request
    def _comprobar_peticion() -> None:
        """Valida el Host de todas las peticiones y el origen de las que
        modifican algo.

        Los metodos seguros (``GET``, ``HEAD``, ``OPTIONS``) no llevan
        ``Origin``: no cambian nada y el navegador puede pedirlos sin
        Origin (un ``<img>`` o un enlace, por ejemplo).
        """
        exigir_host()
        if request.method not in METODOS_SIN_ORIGEN:
            exigir_origen()

    @app.get("/api/eventos")
    def eventos() -> Response:
        """Stream SSE con los eventos del backend."""
        return Response(
            stream_eventos(bus()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/", defaults={"camino": ""})
    @app.get("/<path:camino>")
    def estaticos(camino: str) -> Response:
        """Sirve la SPA."""
        return servir_spa(current_app.config[CLAVE_DIST], camino)

    @app.errorhandler(HTTPError)
    def _error_http(exc: HTTPError) -> tuple[Response, int]:
        return jsonify({"error": exc.mensaje}), exc.codigo

    @app.errorhandler(404)
    def _no_encontrado(exc: Any) -> tuple[Response, int]:
        return jsonify({"error": "No encontrado."}), 404

    @app.errorhandler(405)
    def _metodo_no_valido(exc: Any) -> tuple[Response, int]:
        return jsonify({"error": "Metodo no permitido."}), 405

    @app.errorhandler(500)
    def _error_interno(exc: Any) -> tuple[Response, int]:
        return jsonify({"error": "Error interno."}), 500
