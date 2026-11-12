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

El area no se importa desde el nucleo: ``zc_suite.nucleo.app.main`` la registra en la
lista ``AREAS`` y monta su Blueprint.
"""
from __future__ import annotations

from typing import Any

from flask.sansio.blueprints import BlueprintSetupState

from zc_suite.areas.alimentacion.dispositivos import catalogo as dispositivos_catalogo
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.rutas import CLAVE_ALMACEN, ID, rutas

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
        "device_tabs": dispositivos_catalogo.construir_pestanas(config),
        "nmax": dispositivos_catalogo.construir_n_max(config),
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
    """Se llama al montar la app: deja el area lista para la sesion.

    El Excel maestro no se guarda entre arranques: cada sesion empieza sin
    Excel y el almacen queda vacio.

    Args:
        config: la seccion del area en el ``config.json``.
    """
    ALMACEN.config = config
    ALMACEN.vaciar()


def estado_sesion() -> dict[str, Any]:
    """Lo que el area tiene en la sesion.

    La SPA lo pide al hidratarse: aqui vive el Excel maestro que el operario
    subio en esta sesion.

    Returns:
        Un dict con ``excel``: el volcado del Excel y cuando se cargo.
    """
    return {"excel": ALMACEN.estado()}
