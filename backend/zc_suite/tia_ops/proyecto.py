"""zc_suite.tia_ops.proyecto — abrir y guardar el proyecto de TIA Portal.

Portado de ``core/infrastructure/tia/tia_cmd_project.py`` de la version
anterior. Peculiaridades conservadas:

- Abrir un proyecto exige que el fichero exista en disco.
- El proyecto se resuelve con ``portal.get_project()``. Si no hay ninguno
  es un fallo, no un ``None`` que se propague al que llama.
- Los nombres se leen de forma tolerante: un PLC cuyo nombre no se puede
  decodificar no tumba la busqueda, simplemente no encaja.

Este modulo es tambien el que resuelve el PLC y sus tablas de tags: la
cadena portal -> proyecto -> PLC -> tabla es siempre la misma.

Lo publico devuelve solo primitivos. Los helpers que resuelven objetos
.NET son privados y no salen de ``tia_ops``.
"""
from __future__ import annotations

import os
from typing import Any

from zc_suite.tia_ops import OperacionError

# ── proyecto ───────────────────────────────────────────────────────────────


def abrir_proyecto(portal: Any, ruta: str) -> dict[str, Any]:
    """Abre un proyecto de TIA Portal.

    Args:
        portal: el portal de TIA.
        ruta: ruta completa del fichero ``.apXX``.

    Returns:
        ``{"abierto": True, "ruta": ruta}``.

    Raises:
        OperacionError: si la ruta esta vacia o el fichero no existe.
    """
    if not ruta:
        raise OperacionError("Se requiere la ruta del proyecto.")
    if not os.path.isfile(ruta):
        raise OperacionError(f"El archivo de proyecto no existe: '{ruta}'.")
    portal.open_project(project_file_path=ruta)
    return {"abierto": True, "ruta": ruta}


def guardar_proyecto(portal: Any) -> dict[str, Any]:
    """Guarda los cambios pendientes del proyecto activo.

    Returns:
        ``{"guardado": True}``.

    Raises:
        OperacionError: si no hay ningun proyecto abierto.
    """
    _proyecto_activo(portal).save()
    return {"guardado": True}


# ── resolucion dentro del portal ───────────────────────────────────────────
# Todo lo que sigue devuelve objetos .NET: uso interno de tia_ops.


def _proyecto_activo(portal: Any) -> Any:
    """El proyecto abierto del portal.

    Raises:
        OperacionError: si no hay ningun proyecto abierto.
    """
    proyecto = portal.get_project()
    if not proyecto:
        raise OperacionError(
            "No hay ningun proyecto abierto en TIA Portal. Abre el proyecto y repite."
        )
    return proyecto


def _buscar_plc(portal: Any, nombre: str) -> Any:
    """El PLC con ese nombre dentro del proyecto activo.

    Raises:
        OperacionError: si el nombre esta vacio o no hay ningun PLC con ese
            nombre en el proyecto.
    """
    if not nombre:
        raise OperacionError("Se requiere el nombre del PLC.")
    proyecto = _proyecto_activo(portal)
    for plc in proyecto.get_plcs():
        if _nombre_plc(plc) == nombre:
            return plc
    raise OperacionError(
        f"No se encontro ningun PLC con el nombre '{nombre}' en el proyecto activo."
    )


def _buscar_tabla_tags(plc: Any, nombre: str) -> Any:
    """La tabla de tags con ese nombre dentro del PLC.

    Raises:
        OperacionError: si el nombre esta vacio o la tabla no existe.
    """
    if not nombre:
        raise OperacionError("Se requiere el nombre de la tabla de tags.")
    for tabla in plc.get_plc_tag_tables():
        if _nombre_tabla(tabla) == nombre:
            return tabla
    raise OperacionError(f"Tabla '{nombre}' no encontrada en el PLC.")


def _nombre_plc(plc: Any) -> str | None:
    """Nombre del PLC, tolerando UnicodeDecodeError y COM.

    Un PLC con un nombre ilegible no es un error: simplemente no encaja en
    ninguna busqueda por nombre.
    """
    try:
        return plc.get_name()
    except UnicodeDecodeError:
        return None
    except Exception:
        return None


def _nombre_tabla(tabla: Any) -> str | None:
    """Nombre de la tabla de tags, tolerando UnicodeDecodeError y COM."""
    try:
        return tabla.get_name()
    except UnicodeDecodeError:
        return None
    except Exception:
        return None
