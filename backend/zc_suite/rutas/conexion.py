"""zc_suite.rutas.conexion — conectar y desconectar de TIA Portal.

Las rutas no tocan el portal: encolan un trabajo en el hilo de TIA y
responden ``202`` con su identificador. El resultado llega por el stream SSE.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, jsonify

from zc_suite import tia
from zc_suite.web import exigir_origen, lanzar, servicio

rutas = Blueprint("conexion", __name__, url_prefix="/api/v1/tia")


@rutas.post("/conectar")
def conectar() -> tuple[Response, int]:
    """Encola la conexion con TIA Portal."""
    exigir_origen()
    return lanzar(tia.conectar)


@rutas.post("/desconectar")
def desconectar() -> tuple[Response, int]:
    """Encola la desconexion de TIA Portal."""
    exigir_origen()
    return lanzar(tia.desconectar)


@rutas.get("/estado")
def estado() -> Response:
    """Estado de la conexion: conectado, trabajo en curso y ultimo error."""
    return jsonify(servicio().estado())


def registrar(app: Any) -> None:
    """Monta las rutas de conexion en la app."""
    app.register_blueprint(rutas)
