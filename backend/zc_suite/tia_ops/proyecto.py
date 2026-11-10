"""zc_suite.tia_ops.proyecto — abrir el proyecto de TIA Portal.

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

from zc_suite.tia_ops import OperacionError


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
