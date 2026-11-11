"""zc_suite.rutas.catalogo — el catalogo de la app.

El catalogo lo compone cada area (su ``catalogo(config)``) y ``main`` lo
junta en ``current_app.config["ZC_CATALOGO"]``. Aqui solo se sirve: el
nucleo no conoce las areas.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, current_app, jsonify

#: Clave del catalogo compuesto en la configuracion de la app.
CLAVE_CATALOGO = "ZC_CATALOGO"

rutas = Blueprint("catalogo", __name__, url_prefix="/api/v1")


@rutas.get("/catalog")
def catalogo() -> Response:
    """El catalogo de todas las areas, con lo que la SPA necesita."""
    return jsonify(current_app.config.get(CLAVE_CATALOGO, {}))


def registrar(app: Any) -> None:
    """Monta las rutas del catalogo en la app."""
    app.register_blueprint(rutas)
