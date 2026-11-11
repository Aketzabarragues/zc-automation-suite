"""Area de alimentacion: dispositivos, procesos y entidades del PLC.

En esta version el area es **de solo consulta**: carga el Excel maestro y lo
ensena. No toca TIA.

Contrato del area:

- ``ID``       identificador estable.
- ``NOMBRE``   nombre legible para el menu.
- ``rutas``    ``Blueprint`` Flask con las rutas del area.
- ``catalogo(config)``  lo que la SPA necesita del backend.
- ``defaults(config)``  valores por defecto que el area aporta a la config.
- ``al_arrancar(config)``  recarga lo que el area tenga guardado.

El area no se importa desde el nucleo: ``zc_suite.main`` la registra en la
lista ``AREAS`` y monta su Blueprint.
"""
from __future__ import annotations

import logging
from typing import Any

from flask.sansio.blueprints import BlueprintSetupState

from zc_suite.areas.alimentacion.dispositivo import disp_catalogo
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
    "rutas",
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
        Solo datos primitivos: los catalogos de columnas, el de N_MAX y el
        de dispositivos.
    """
    return {
        "disp_catalog": config.get("disp_catalog", {}),
        "proc_catalog": config.get("proc_catalog", {}),
        "entidades_catalog": config.get("entidades_catalog", {}),
        "n_max_catalog": config.get("n_max_catalog", []),
        "Dispositivos": config.get("Dispositivos", {}),
        "excel": {"tabla_config": config.get("global_config_table_name", "")},
        "device_tabs": disp_catalogo.construir_pestanas(config),
        "nmax": disp_catalogo.construir_n_max(config),
    }


def defaults(config: dict[str, Any]) -> dict[str, Any]:
    """Los valores por defecto del area.

    Args:
        config: la seccion del area en el ``config.json``.

    Returns:
        Un dict con los ajustes por defecto del area. Vacio de momento: el
        area no tiene ajustes propios todavia.
    """
    return {}


def al_arrancar(config: dict[str, Any]) -> None:
    """Se llama al montar la app: recarga lo que el area tenga guardado.

    Args:
        config: la seccion del area en el ``config.json``.
    """
    ALMACEN.config = config
    try:
        if ALMACEN.recargar():
            logger.info("Excel maestro recargado: %s", ALMACEN.archivo)
    except Exception as exc:
        # El arranque no se cae por un Excel que no se pueda leer.
        logger.warning("No se pudo recargar el Excel del area: %s", exc)
