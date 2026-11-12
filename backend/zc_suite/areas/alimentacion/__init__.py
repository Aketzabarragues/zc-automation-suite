"""Area de alimentacion: dispositivos, procesos y entidades del PLC.

En esta version el area es **de solo consulta**: carga el Excel maestro y lo
ensena. No toca TIA.

Contrato del area:

- ``ID``       identificador estable.
- ``NOMBRE``   nombre legible para el menu.
- ``rutas``    ``Blueprint`` Flask con las rutas del area.
- ``catalogo(config)``  lo que la SPA necesita del backend.
- ``defaults(config)``  valores por defecto que el area aporta a la config.
- ``al_arrancar(config)``  deja el area lista para la sesion.
- ``estado_sesion()``  lo que el area tiene en la sesion: el Excel cargado.
- ``valida_config(config)``  el motivo por el que su seccion del
  ``config.json`` no vale, o ``None`` si vale.

El area no se importa desde el nucleo: ``zc_suite.nucleo.app.main`` la registra en la
lista ``AREAS`` y monta su Blueprint.
"""
from __future__ import annotations

import logging
from typing import Any

from flask.sansio.blueprints import BlueprintSetupState

from zc_suite.areas.alimentacion import config as config_area
from zc_suite.areas.alimentacion.dispositivos import catalogo as dispositivos_catalogo
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.rutas import CLAVE_ALMACEN, ID, rutas

logger = logging.getLogger(__name__)

__all__ = [
    "DESCRIPCION",
    "ICONO",
    "ID",
    "NOMBRE",
    "al_arrancar",
    "catalogo",
    "defaults",
    "estado_sesion",
    "rutas",
    "valida_config",
]

#: Nombre del area, como lo ve el operario.
NOMBRE = "Alimentacion"

#: Descripcion corta, para la tarjeta del selector de areas.
DESCRIPCION = "Dispositivos, sincronización e inspección de PLCs del área de alimentación."

#: Icono del area.
ICONO = "📁"

#: La cache del Excel maestro del area.
ALMACEN = AlmacenExcel()


@rutas.record_once
def _registrar_dependencias(estado: BlueprintSetupState) -> None:
    """Registra en la app las dependencias del area.

    El router las lee de ``current_app.config``: no importa singletons.
    """
    estado.app.config[CLAVE_ALMACEN] = ALMACEN


def catalogo(config: dict[str, Any]) -> dict[str, Any]:
    """El catalogo del area: lo que la SPA necesita del backend.

    Args:
        config: la seccion del area en el ``config.json``.

    Returns:
        Solo datos primitivos: las pestañas por tipo de dispositivo y las
        tarjetas de N_MAX. Vacio si la seccion del config no es valida.
    """
    modelo = _modelo(config)
    if modelo is None:
        return {"device_tabs": [], "nmax": []}
    return {
        "device_tabs": dispositivos_catalogo.construir_pestanas(modelo),
        "nmax": dispositivos_catalogo.construir_n_max(modelo),
    }


def defaults(config: dict[str, Any]) -> dict[str, Any]:
    """Los valores por defecto del area.

    Args:
        config: la seccion del area en el ``config.json``.

    Returns:
        Un dict con los ajustes por defecto del area.
    """
    return {"plantillas_procesos": "plantillas"}


def valida_config(config: dict[str, Any]) -> str | None:
    """El motivo por el que la seccion del area no vale, o ``None`` si vale.

    Args:
        config: la seccion del area en el ``config.json``.

    Returns:
        El mensaje para el operario, o ``None`` si la seccion es valida.
    """
    return config_area.problema(config)


def al_arrancar(config: dict[str, Any]) -> None:
    """Se llama al montar la app: deja el area lista para la sesion.

    El Excel maestro no se guarda entre arranques: cada sesion empieza sin
    Excel y el almacen queda vacio.

    Args:
        config: la seccion del area en el ``config.json``.
    """
    ALMACEN.vaciar()
    ALMACEN.config = _modelo(config)


def estado_sesion() -> dict[str, Any]:
    """Lo que el area tiene en la sesion.

    La SPA lo pide al hidratarse: aqui vive el Excel maestro que el operario
    subio en esta sesion.

    Returns:
        Un dict con ``excel``: el volcado del Excel y cuando se cargo.
    """
    return {"excel": ALMACEN.estado()}


def _modelo(config: dict[str, Any]) -> config_area.ConfigArea | None:
    """El modelo del area, o ``None`` si su seccion no es valida."""
    try:
        return config_area.cargar(config)
    except config_area.ConfigInvalidoError as exc:
        logger.error("Config del area invalido: %s", exc)
        return None
