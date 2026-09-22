"""core.infrastructure.tia.tia_cmd_project - comandos de ciclo de vida del proyecto.

Tres comandos para abrir / guardar / cerrar el proyecto TIA Portal activo:

  - open_project:  abre un archivo .apXX desde una ruta.
  - save_project:  guarda los cambios pendientes.
  - close_project: cierra el proyecto activo (¡destruye cambios no guardados!).

Precondición común: portal ya attached (via attach_portal o open_new_portal).
Para cold start (abrir TIA Portal + proyecto), usar open_new_portal.

Cada handler es una FC pura: recibe ``(args: dict, tia_client: SyncTIAClient)``
y devuelve ``dict``. Acceso a portal via ``tia_client.wrapper`` (single-threaded;
lo toca el tia-loop).

Restricciones arquitectónicas:
  - NO hace logging de args (puede contener paths sensibles).
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from core.infrastructure.tia.tia_helpers import _get_active_project

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


def _h_open_project(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Abre un proyecto TIA Portal desde una ruta.

    Precondicion: portal ya attached. Para cold start, usar open_new_portal.
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project_file_path: str = args.get("project_file_path", "")
    if not project_file_path:
        raise ValueError("Se requiere el argumento 'project_file_path'.")
    if not os.path.isfile(project_file_path):
        raise RuntimeError(
            f"El archivo de proyecto no existe: '{project_file_path}'."
        )
    portal.open_project(project_file_path=project_file_path)
    return {"opened": True, "project_file_path": project_file_path}


def _h_save_project(args: dict, tia_client: "SyncTIAClient") -> dict:  # noqa: ARG001
    """Guarda los cambios pendientes del proyecto activo."""
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    project.save()
    return {"saved": True}


def _h_close_project(args: dict, tia_client: "SyncTIAClient") -> dict:  # noqa: ARG001
    """Cierra el proyecto activo.

    OJO: project.close() destruye los cambios no guardados. El caller
    debe haber invocado save() antes si la persistencia era necesaria.
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    project.close()
    return {"closed": True}


# Mapa nombre → handler. El registro central (tia_commands_catalog)
# importará este dict para registrar los 3 comandos en el worker.
COMMANDS: dict[str, Any] = {
    "open_project": _h_open_project,
    "save_project": _h_save_project,
    "close_project": _h_close_project,
}


__all__ = [
    "COMMANDS",
    "_h_open_project",
    "_h_save_project",
    "_h_close_project",
]
