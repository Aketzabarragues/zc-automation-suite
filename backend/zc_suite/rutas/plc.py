"""zc_suite.rutas.plc — el PLC: listarlo, escanearlo y editar sus bloques.

Las rutas no tocan el portal: encolan un trabajo en el hilo de TIA y
responden ``202`` con su identificador. El resultado llega por el stream SSE.

El portal es un objeto COM afin a hilo: solo el hilo de TIA puede leerlo. Por
eso **toda** operacion contra TIA es un trabajo, tambien la simple lista de
PLCs.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, jsonify, request

from zc_suite import trabajos
from zc_suite.web import lanzar

rutas = Blueprint("plc", __name__, url_prefix="/api/v1/tia")


@rutas.post("/plcs/listar")
def listar() -> tuple[Response, int]:
    """Encola la lista de PLCs del proyecto abierto."""
    return lanzar(trabajos.buscar_plcs)


@rutas.post("/plcs/<plc>/escanear")
def escanear(plc: str) -> tuple[Response, int]:
    """Encola el escaneo del PLC: bloques, tablas de tags y tipos de usuario."""
    return lanzar(trabajos.escanear_plc, plc=plc)


@rutas.post("/plcs/<plc>/bloques/preparar")
def preparar(plc: str) -> tuple[Response, int]:
    """Encola la lectura de las propiedades de los bloques indicados."""
    datos = request.get_json(silent=True) or {}
    nombres = [str(nombre) for nombre in (datos.get("bloques") or [])]
    if not nombres:
        return jsonify({"error": "No se han indicado bloques."}), 400
    return lanzar(trabajos.preparar_bloques, plc=plc, nombres=nombres)


@rutas.post("/plcs/<plc>/bloques/editar")
def editar(plc: str) -> tuple[Response, int]:
    """Encola la aplicacion de los cambios de nombre y numero."""
    datos = request.get_json(silent=True) or {}
    cambios = datos.get("cambios") or {}
    if not isinstance(cambios, dict) or not cambios:
        return jsonify({"error": "No hay cambios que aplicar."}), 400
    return lanzar(trabajos.editar_bloques, plc=plc, cambios=cambios)


def registrar(app: Any) -> None:
    """Monta las rutas del PLC en la app."""
    app.register_blueprint(rutas)
