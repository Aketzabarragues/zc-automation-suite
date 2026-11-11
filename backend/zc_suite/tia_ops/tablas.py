"""zc_suite.tia_ops.tablas — las tablas de tags del PLC.

Una tabla de tags es donde TIA guarda las variables del PLC. Su nombre en la
interfaz es "Variables", pero en el idioma de TIA es una tabla de tags.

Solo lectura: las variables se cambian desde el libro maestro del area, no
desde aqui.
"""
from __future__ import annotations

from typing import Any

from zc_suite.tia_ops._resolver import buscar_plc, nombre_tabla


def escanear_tablas_tags(portal: Any, plc: str) -> list[dict[str, Any]]:
    """Las tablas de tags del PLC.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.

    Returns:
        Lista de ``{"nombre", "ruta"}``. La ruta es la jerarquia de carpetas
        de TIA; vacia para una tabla en la raiz del PLC.

    Raises:
        OperacionError: si el PLC no existe.
    """
    objetivo = buscar_plc(portal, plc)
    tablas: list[dict[str, Any]] = []
    for tabla in objetivo.get_plc_tag_tables() or []:
        nombre = nombre_tabla(tabla)
        if not nombre:
            continue
        tablas.append({"nombre": str(nombre), "ruta": _ruta(tabla)})
    return tablas


def _ruta(tabla: Any) -> str:
    """La jerarquia de carpetas de la tabla. Vacia si no se puede leer."""
    try:
        if hasattr(tabla, "get_path"):
            return str(tabla.get_path())
        if hasattr(tabla, "Path"):
            return str(tabla.Path)
    except Exception:
        return ""
    return ""
