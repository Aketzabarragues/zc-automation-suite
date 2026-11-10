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
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from flask import Flask, Response, current_app, jsonify, request, send_from_directory

from zc_suite.eventos import BusEventos, Suscripcion
from zc_suite.tia import OcupadoError, ServicioTIA

#: Claves de las dependencias en ``current_app.config``.
CLAVE_SERVICIO = "ZC_TIA"
CLAVE_BUS = "ZC_BUS"
CLAVE_DIST = "ZC_DIST"
CLAVE_ORIGENES = "ZC_ORIGENES"

#: Origenes de la SPA en desarrollo (Vite). En produccion sirve la propia app.
ORIGENES_DEV = frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})

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
    """Origenes que pueden hacer POST: el de la app y los de desarrollo."""
    permitidos = set(current_app.config.get(CLAVE_ORIGENES) or ())
    permitidos.add(f"{request.scheme}://{request.host}")
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
) -> Flask:
    """Crea la app Flask con sus dependencias registradas.

    Args:
        servicio_tia: el hilo de TIA.
        bus_eventos: el bus de eventos.
        dist_frontend: carpeta del build de la SPA. Por defecto,
            ``frontend/dist`` del repo.
        origenes: origenes permitidos ademas del de la propia app.
    """
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    app.config[CLAVE_SERVICIO] = servicio_tia
    app.config[CLAVE_BUS] = bus_eventos
    app.config[CLAVE_DIST] = dist_frontend or ruta_dist_frontend()
    app.config[CLAVE_ORIGENES] = set(origenes) if origenes is not None else set(ORIGENES_DEV)
    _registrar_rutas(app)
    return app


def _registrar_rutas(app: Flask) -> None:
    """Monta las rutas del nucleo."""

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
