"""zc_suite.nucleo.web.rutas.sesion — el estado de la sesion.

``GET /api/v1/sesion`` es lo que hidrata la SPA al cargar: el estado de TIA,
los PLCs, el PLC seleccionado con su escaneo y lo que cada area tenga en su
sesion.

La sesion vive en la memoria del backend. Un F5 de la web no la pierde; al
cerrar la app, si.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, current_app, jsonify

from zc_suite.nucleo.sesion import CLAVE_SESION, CLAVE_SESION_AREAS, Sesion
from zc_suite.nucleo.web.app import HTTPError, servicio

rutas = Blueprint("sesion", __name__, url_prefix="/api/v1")


@rutas.get("/sesion")
def estado_sesion() -> Response:
    """El estado de la sesion: lo que la SPA necesita para hidratarse."""
    estado = _sesion().estado()
    estado["tia"] = servicio().estado()
    estado["areas"] = {
        id_area: obtener()
        for id_area, obtener in current_app.config.get(CLAVE_SESION_AREAS, {}).items()
    }
    return jsonify(estado)


def _sesion() -> Sesion:
    """La sesion de la app.

    Raises:
        HTTPError: si la sesion no esta registrada.
    """
    valor = current_app.config.get(CLAVE_SESION)
    if valor is None:
        raise HTTPError("La sesion no esta registrada.", 500)
    return valor


def registrar(app: Any) -> None:
    """Monta las rutas de la sesion en la app."""
    app.register_blueprint(rutas)
