"""zc_suite.nucleo.web.rutas.plc — el PLC: listarlo, escanearlo y editar sus bloques.

Las rutas no tocan el portal: encolan un trabajo en el hilo de TIA y
responden ``202`` con su identificador. El resultado llega por el stream SSE.

El portal es un objeto COM afin a hilo: solo el hilo de TIA puede leerlo. Por
eso **toda** operacion contra TIA es un trabajo, tambien la simple lista de
PLCs.

Los trabajos guardan su resultado en la sesion (los PLCs, el escaneo del
PLC): es lo que la SPA ve al hidratarse.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from zc_suite.nucleo.funciones.bloques.aplicar import aplicar
from zc_suite.nucleo.funciones.bloques.preparar import preparar
from zc_suite.nucleo.funciones.plc.buscar_plcs import buscar_plcs
from zc_suite.nucleo.funciones.plc.escanear import escanear
from zc_suite.nucleo.sesion import CLAVE_SESION, Sesion
from zc_suite.nucleo.web.app import HTTPError, lanzar

rutas = Blueprint("plc", __name__, url_prefix="/api/v1/tia")


@rutas.post("/plcs/listar")
def listar() -> tuple[Response, int]:
    """Encola la lista de PLCs del proyecto abierto."""
    return lanzar(buscar_plcs, sesion=_sesion())


@rutas.post("/plcs/seleccionar")
def seleccionar() -> tuple[Response, int]:
    """Selecciona un PLC y devuelve su escaneo si sigue valiendo.

    Con un escaneo fresco (de menos de 5 minutos) se devuelve tal cual. Si no
    hay escaneo, o ha caducado, se encola el escaneo: **una sola vez**, que
    es lo que evita el doble escaneo al seleccionar un PLC.
    """
    datos = request.get_json(silent=True) or {}
    plc = str(datos.get("plc") or "").strip()
    if not plc:
        return jsonify({"error": "No se ha indicado el PLC."}), 400

    sesion = _sesion()
    sesion.seleccionar(plc)
    escaneo = sesion.escaneo_fresco(plc)
    if escaneo is not None:
        return jsonify({"plc": plc, "escaneo": escaneo.estado()}), 200
    return lanzar(escanear, plc=plc, sesion=sesion)


@rutas.post("/plcs/<plc>/escanear")
def escanear_plc(plc: str) -> tuple[Response, int]:
    """Encola el escaneo del PLC: bloques, tablas de tags y tipos de usuario.

    Esto es el "Actualizar" de la vista: fuerza el escaneo, aunque el de la
    sesion siga en vigor.
    """
    return lanzar(escanear, plc=plc, sesion=_sesion())


@rutas.post("/plcs/<plc>/bloques/preparar")
def preparar_bloques(plc: str) -> tuple[Response, int]:
    """Encola la lectura de las propiedades de los bloques indicados."""
    datos = request.get_json(silent=True) or {}
    nombres = [str(nombre) for nombre in (datos.get("bloques") or [])]
    if not nombres:
        return jsonify({"error": "No se han indicado bloques."}), 400
    return lanzar(preparar, plc=plc, nombres=nombres)


@rutas.post("/plcs/<plc>/bloques/editar")
def editar_bloques(plc: str) -> tuple[Response, int]:
    """Encola la aplicacion de los cambios de nombre y numero."""
    datos = request.get_json(silent=True) or {}
    cambios = datos.get("cambios") or {}
    if not isinstance(cambios, dict) or not cambios:
        return jsonify({"error": "No hay cambios que aplicar."}), 400
    return lanzar(aplicar, plc=plc, cambios=cambios, sesion=_sesion())


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
    """Monta las rutas del PLC en la app."""
    app.register_blueprint(rutas)
