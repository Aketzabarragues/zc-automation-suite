"""zc_suite.tia_ops._resolver — resolucion de objetos dentro del portal.

La cadena portal -> proyecto -> PLC -> tabla de tags es siempre la misma, y
la comparten todos los modulos de ``tia_ops``. Aqui vive.

Los nombres son publicos dentro del paquete, pero el modulo es privado: de
fuera de ``tia_ops`` no se usa. Lo que devuelve son objetos .NET, que nunca
salen del paquete: los modulos los convierten antes de responder.
"""
from __future__ import annotations

from typing import Any

from zc_suite.tia import proyecto_activo
from zc_suite.tia_ops import OperacionError


def buscar_plc(portal: Any, nombre: str) -> Any:
    """El PLC con ese nombre dentro del proyecto activo.

    Raises:
        OperacionError: si el nombre esta vacio o no hay ningun PLC con ese
            nombre en el proyecto.
        SinProyectoError: si no hay ningun proyecto abierto.
    """
    if not nombre:
        raise OperacionError("Se requiere el nombre del PLC.")
    proyecto = proyecto_activo(portal)
    for plc in proyecto.get_plcs():
        if nombre_plc(plc) == nombre:
            return plc
    raise OperacionError(
        f"No se encontro ningun PLC con el nombre '{nombre}' en el proyecto activo."
    )


def buscar_tabla_tags(plc: Any, nombre: str) -> Any:
    """La tabla de tags con ese nombre dentro del PLC.

    Raises:
        OperacionError: si el nombre esta vacio o la tabla no existe.
    """
    if not nombre:
        raise OperacionError("Se requiere el nombre de la tabla de tags.")
    for tabla in plc.get_plc_tag_tables():
        if nombre_tabla(tabla) == nombre:
            return tabla
    raise OperacionError(f"Tabla '{nombre}' no encontrada en el PLC.")


def nombre_plc(plc: Any) -> str | None:
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


def nombre_tabla(tabla: Any) -> str | None:
    """Nombre de la tabla de tags, tolerando UnicodeDecodeError y COM."""
    try:
        return tabla.get_name()
    except UnicodeDecodeError:
        return None
    except Exception:
        return None


def nombre_bloque(bloque: Any) -> str | None:
    """Nombre del bloque, tolerando UnicodeDecodeError y COM.

    El wrapper expone ``get_name()``; algunos objetos solo tienen la
    propiedad ``Name``.
    """
    try:
        if hasattr(bloque, "get_name"):
            return bloque.get_name()
        if hasattr(bloque, "Name"):
            return bloque.Name
    except UnicodeDecodeError:
        return None
    except Exception:
        return None
    return None


def buscar_bloque(plc: Any, nombre: str) -> Any:
    """El bloque con ese nombre dentro del PLC.

    Args:
        plc: el PLC.
        nombre: nombre del bloque.

    Returns:
        El bloque nativo. Objeto .NET: uso interno de ``tia_ops``.

    Raises:
        OperacionError: si no hay ningun bloque con ese nombre.
    """
    for bloque in bloques_del_plc(plc):
        if nombre_bloque(bloque) == nombre:
            return bloque
    raise OperacionError(f"No se encontro el bloque '{nombre}' en el PLC.")


def bloques_del_plc(plc: Any) -> list[Any]:
    """Los bloques de programa del PLC.

    El SDK devuelve la lista **plana**: ``get_program_blocks()`` ya incluye
    los bloques que estan dentro de grupos. La jerarquia se lee de
    ``get_path()`` de cada bloque, no del recorrido.
    """
    return list(plc.get_program_blocks() or [])


def tipos_de_datos_del_plc(plc: Any) -> list[Any]:
    """Los tipos de datos de usuario (UDT) del PLC."""
    return list(plc.get_user_data_types() or [])
