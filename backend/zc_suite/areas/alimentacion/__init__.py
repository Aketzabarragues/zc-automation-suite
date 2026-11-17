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
- ``al_recargar_config(config)``  aplica una seccion nueva del config sin
  tocar lo que el area tiene en la sesion.
- ``estado_sesion()``  lo que el area tiene en la sesion: el Excel cargado.
- ``valida_config(config)``  el motivo por el que su seccion del
  ``config.json`` no vale, o ``None`` si vale.
- ``ALMACEN``  la cache del Excel maestro del area.

El area no se importa desde el nucleo: ``zc_suite.nucleo.app.main`` la registra en la
lista ``AREAS`` y monta su Blueprint.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask.sansio.blueprints import BlueprintSetupState

from zc_suite.areas.alimentacion import config as config_area
from zc_suite.areas.alimentacion.dispositivos import catalogo as dispositivos_catalogo
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.rutas import CLAVE_ALMACEN, ID, rutas

logger = logging.getLogger(__name__)

__all__ = [
    "ALMACEN",
    "ID",
    "NOMBRE",
    "al_arrancar",
    "al_recargar_config",
    "catalogo",
    "defaults",
    "estado_sesion",
    "rutas",
    "valida_config",
]

#: Nombre del area, como lo ve el operario.
NOMBRE = "Alimentacion"

#: La cache del Excel maestro del area.
ALMACEN = AlmacenExcel()


@rutas.record_once
def _registrar_dependencias(estado: BlueprintSetupState) -> None:
    """Registra en la app las dependencias del area.

    El router las lee de ``current_app.config``: no importa singletons.
    """
    estado.app.config[CLAVE_ALMACEN] = ALMACEN


def catalogo(config: dict[str, Any], ruta_config: Path | None = None) -> dict[str, Any]:
    """El catalogo del area: lo que la SPA necesita del backend.

    El nucleo compone el catalogo de cada area en esta funcion, que es la
    unica que conoce el contenido del catalogo: aqui se emite el log del
    area y sus avisos (el nucleo solo registra que area tiene).

    Args:
        config: la seccion del area en el ``config.json``.
        ruta_config: el ``config.json`` en uso, para el aviso cuando el
            catalogo sale vacio.

    Returns:
        Solo datos primitivos: las pestañas por tipo de dispositivo y las
        tarjetas de N_MAX. Vacio si la seccion del config no es valida.
    """
    modelo = _modelo(config)
    if modelo is None:
        catalogo = {"device_tabs": [], "nmax": []}
    else:
        catalogo = {
            "device_tabs": dispositivos_catalogo.construir_pestanas(modelo),
            "nmax": dispositivos_catalogo.construir_n_max(modelo),
        }
    _aviso_de_catalogo(catalogo, ruta_config)
    return catalogo


def _aviso_de_catalogo(catalogo: dict[str, Any], ruta_config: Path | None) -> None:
    """El log del area y sus avisos: el nucleo no conoce las claves.

    Args:
        catalogo: el catalogo del area ya compuesto.
        ruta_config: el ``config.json`` en uso, o ``None`` si no se sabe.
    """
    tipos = len(catalogo.get("device_tabs") or [])
    n_max = len(catalogo.get("nmax") or [])
    logger.info("Area '%s': %d tipos de dispositivo, %d N_MAX", ID, tipos, n_max)
    if ruta_config is None:
        return
    if not tipos:
        logger.warning(
            "El area '%s' no tiene tipos de dispositivo en el catalogo: la "
            "vista de dispositivos saldra vacia. Revisa el config.json en "
            "uso (%s): puede que este vacio o incompleto.",
            ID,
            ruta_config,
        )
    if not n_max:
        logger.warning(
            "El area '%s' no tiene N_MAX en el catalogo: las tarjetas de "
            "N_MAX saldran vacias. Revisa el config.json en uso (%s).",
            ID,
            ruta_config,
        )


def defaults(config: dict[str, Any]) -> dict[str, Any]:
    """Los valores por defecto del area.

    Args:
        config: la seccion del area en el ``config.json``.

    Returns:
        Un dict con los ajustes por defecto del area.
    """
    return {"plantillas_procesos": ""}


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


def al_recargar_config(config: dict[str, Any]) -> None:
    """Aplica una seccion nueva del config sin tocar la sesion.

    Se llama cuando el operario cambia un ajuste desde la web (p. ej. la
    carpeta de plantillas). A diferencia de ``al_arrancar``, NO vacia el
    almacen: el Excel que el operario ya cargo sigue ahi.

    Args:
        config: la seccion del area en el ``config.json`` recargado.
    """
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
