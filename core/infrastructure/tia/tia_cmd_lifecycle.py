"""core.infrastructure.tia.tia_cmd_lifecycle - comandos de ciclo de vida del portal.

Tres comandos que controlan la conexión del worker OT con TIA Portal:

  - attach_portal: attach a un portal TIA Portal ya abierto (persistente).
  - detach_portal: cierra el portal attached (best-effort, idempotente).
  - open_new_portal: cold start. Abre TIA Portal y un proyecto en un solo paso.

Cada handler es una FC pura: recibe ``(args: dict, tia_client: SyncTIAClient)``
y devuelve ``dict``. Acceso a portal/ts via ``tia_client.wrapper`` /
``tia_client.ts`` (single-threaded; lo toca el tia-loop).

Restricciones arquitectónicas:
  - NO abre archivos. NO toca filesystem. Solo el wrapper .NET.
  - NO hace logging de args (puede contener info sensible del operario).
"""
from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


def _h_attach_portal(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Attach a un portal TIA Portal ya abierto (persistente).

    ``args["mode"]`` puede ser ``"WithGraphicalUserInterface"`` o
    ``"WithoutGraphicalUserInterface"``. Default: con GUI.
    Acepta también ``args["portal_mode"]`` por compat con callers previos.

    Idempotente: si ya hay portal attached, devuelve su PID actual
    (o fuerza detach + re-attach si ``get_process_id()`` falla).
    """
    ts = tia_client.ts
    if ts is None:
        return {"error": "Modulo siemens_tia_scripting no attached."}
    if tia_client.wrapper is not None:
        try:
            pid = int(tia_client.wrapper.get_process_id())
            return {"pid": pid, "state": "connected", "portal_mode": "attached"}
        except Exception:
            # Portal vivo pero get_process_id falla (TIA cerrada
            # mid-session). Forzamos detach y seguimos con attach fresh.
            try:
                tia_client.wrapper.detach()
            except Exception:
                pass
            tia_client.attach_wrapper(None)
    mode_name = (args or {}).get("mode") or (args or {}).get(
        "portal_mode", "WithGraphicalUserInterface",
    )
    try:
        portal_mode = getattr(ts.Enums.PortalMode, mode_name)
    except AttributeError:
        return {
            "error": (
                f"PortalMode invalido: {mode_name!r}. "
                "Use 'WithGraphicalUserInterface' o "
                "'WithoutGraphicalUserInterface'."
            ),
        }
    attach_start = time.monotonic()
    try:
        new_portal = ts.attach_portal(portal_mode=portal_mode)
    except Exception as exc:
        attach_ms = round((time.monotonic() - attach_start) * 1000)
        logger.warning(
            "attach_failed (%.0fms): %s: %s",
            attach_ms, type(exc).__name__, exc,
        )
        return {"error": f"{type(exc).__name__}: {exc}"}
    if new_portal is None:
        attach_ms = round((time.monotonic() - attach_start) * 1000)
        logger.warning("attach_failed (%.0fms): attach_portal retorno None.", attach_ms)
        return {
            "error": (
                "attach_portal retorno None. ¿Esta TIA Portal abierto? "
                "¿El usuario pertenece al grupo Openness?"
            ),
        }
    tia_client.attach_wrapper(new_portal)
    try:
        pid = int(new_portal.get_process_id())
    except Exception:
        pid = None
    attach_ms = round((time.monotonic() - attach_start) * 1000)
    logger.info(
        "attach OK (%.0fms, pid=%s, mode=%s)",
        attach_ms, pid, mode_name,
    )
    return {
        "pid": pid,
        "state": "connected",
        "portal_mode": mode_name,
    }


def _h_detach_portal(args: dict, tia_client: "SyncTIAClient") -> dict:  # noqa: ARG001
    """Cierra el portal attached (best-effort).

    Si ``portal.detach()`` falla (TIA ya cerrado o RCW stale) se loggea
    como warning pero no se propaga: idempotente.
    """
    if tia_client.wrapper is None:
        return {"detached": False}
    detach_start = time.monotonic()
    detach_error: Exception | None = None
    try:
        tia_client.wrapper.detach()
    except Exception as exc:
        logger.warning(
            "detach_portal best-effort fallo: %s: %s",
            type(exc).__name__, exc,
        )
        detach_error = exc
    tia_client.attach_wrapper(None)
    detach_ms = round((time.monotonic() - detach_start) * 1000)
    if detach_error is None:
        logger.info("detach OK (%.0fms).", detach_ms)
        return {"detached": True}
    return {"detached": True, "warning": f"{type(detach_error).__name__}: {detach_error}"}


def _h_open_new_portal(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Cold start: abre TIA Portal y un proyecto en un solo paso.

    Args:
        args: ``project_file_path`` (str) — ruta absoluta al .apXX.
    """
    ts = tia_client.ts
    if ts is None:
        raise RuntimeError("Modulo siemens_tia_scripting no attached.")
    project_file_path: str = args.get("project_file_path", "")
    if not project_file_path:
        raise ValueError(
            "open_new_portal requiere el argumento 'project_file_path'."
        )
    if not os.path.isfile(project_file_path):
        raise RuntimeError(
            f"El archivo de proyecto no existe: '{project_file_path}'."
        )
    # Si ya hay portal attached, lo usamos; si no, abrimos uno nuevo.
    portal = tia_client.wrapper
    if portal is None:
        portal = ts.open_portal(portal_mode=ts.Enums.PortalMode.AnyUserInterface)
        if portal is None:
            raise RuntimeError("Fallo critico: open_portal retorno None.")
        tia_client.attach_wrapper(portal)
    portal.open_project(project_file_path=project_file_path)
    return {
        "opened": True,
        "project_file_path": project_file_path,
        "state": "connected",
    }


# Mapa nombre → handler. El registro central (tia_commands_catalog)
# importará este dict para registrar los 3 comandos en el worker.
COMMANDS: dict[str, Any] = {
    "attach_portal": _h_attach_portal,
    "detach_portal": _h_detach_portal,
    "open_new_portal": _h_open_new_portal,
}


__all__ = [
    "COMMANDS",
    "_h_attach_portal",
    "_h_detach_portal",
    "_h_open_new_portal",
]
