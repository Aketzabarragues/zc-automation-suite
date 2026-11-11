"""zc_suite.tia_ops.proyecto — el proyecto de TIA Portal y sus PLCs.

Portado de ``core/infrastructure/tia/tia_cmd_project.py`` de la version
anterior. Peculiaridad conservada: el fichero del proyecto tiene que existir
en disco, o la operacion falla.

No se porta ``save_project``: la politica del repo es que el operario guarda
a mano en TIA Portal. Tampoco ``close_project``: no tiene ningun llamador.

La resolucion del proyecto, del PLC y de sus tablas vive en
``zc_suite.tia_ops._resolver``.
"""
from __future__ import annotations

import os
from typing import Any

from zc_suite.tia import proyecto_activo
from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops._resolver import nombre_plc


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


def listar_plcs(portal: Any) -> list[dict[str, Any]]:
    """Los PLCs del proyecto abierto.

    Args:
        portal: el portal de TIA.

    Returns:
        Lista de ``{"nombre", "designacion"}``. La designacion es la
        ``ShortDesignation`` de TIA (la CPU): vacia si TIA no la da.

    Raises:
        SinProyectoError: si no hay ningun proyecto abierto.
    """
    proyecto = proyecto_activo(portal)
    plcs: list[dict[str, Any]] = []
    for plc in proyecto.get_plcs():
        nombre = nombre_plc(plc)
        if not nombre:
            continue
        plcs.append({"nombre": nombre, "designacion": _designacion(plc)})
    return plcs


def info_proyecto(portal: Any) -> dict[str, Any]:
    """Nombre y ruta del proyecto abierto.

    Args:
        portal: el portal de TIA.

    Returns:
        ``{"nombre": str, "ruta": str}``. La ruta es la del fichero ``.apXX``
        que TIA tiene abierto.

    Raises:
        SinProyectoError: si no hay ningun proyecto abierto.
    """
    proyecto = proyecto_activo(portal)
    return {
        "nombre": _texto(_propiedad(proyecto, "Name")),
        "ruta": _texto(_propiedad(proyecto, "Path")),
    }


# ── helpers ────────────────────────────────────────────────────────────────


def _propiedad(objeto: Any, nombre: str) -> Any:
    """El valor de una propiedad del objeto, o ``None`` si no se puede leer."""
    getter = getattr(objeto, "get_property", None)
    if getter is None:
        return None
    try:
        return getter(name=nombre)
    except Exception:
        return None


def _texto(valor: Any) -> str:
    """El valor como texto. Cadena vacia si no hay valor."""
    if valor is None:
        return ""
    return str(valor).strip()


def _designacion(plc: Any) -> str:
    """La designacion corta de la CPU. Vacia si TIA no la da."""
    valor = _propiedad(plc, "ShortDesignation")
    if valor is None:
        return ""
    texto = str(valor).strip()
    if texto.casefold() == "no value":
        return ""
    return texto

