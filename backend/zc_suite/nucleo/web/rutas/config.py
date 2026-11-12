"""zc_suite.nucleo.web.rutas.config — el estado de la configuracion.

``GET /api/v1/config`` dice de donde sale el ``config.json`` y si sirve. Si
no vale (no tiene la seccion ``areas`` o le falta un area registrada), la SPA
ensea un banner rojo: el config del operario no se sustituye nunca.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, current_app, jsonify

#: Clave del estado de la configuracion en la configuracion de la app.
CLAVE_ESTADO_CONFIG = "ZC_ESTADO_CONFIG"

rutas = Blueprint("config", __name__, url_prefix="/api/v1")


@rutas.get("/config")
def estado_config() -> Response:
    """El estado de la configuracion: de donde sale y si es compatible."""
    return jsonify(current_app.config.get(CLAVE_ESTADO_CONFIG, {}))


def registrar(app: Any) -> None:
    """Monta las rutas de la configuracion en la app."""
    app.register_blueprint(rutas)
