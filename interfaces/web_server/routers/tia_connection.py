"""Router REST para el estado del worker OT persistente.

Tres endpoints:

  GET  /api/v1/tia/connection  -> estado actual del worker persistente.
  POST /api/v1/tia/connect     -> fuerza reconexion (PR 6 implementa la logica).
  POST /api/v1/tia/disconnect  -> desconecta (PR 6 implementa la logica).

Shape del GET (ver design doc ``_plan/12_worker_persistent_design.md`` §4.1)::

    {
      "state": "connected" | "connecting" | "disconnected" | "error",
      "project": {"name": str, "path": str, "version": str} | null,
      "plcs": [str, ...],
      "last_ping_ok_unix": float | null,
      "last_error": str | null
    }

Las dependencias se inyectan via ``Depends`` (Clean Architecture en
routers; ver ``interfaces/web_server/dependencies.py``). NO se
importan globales: el gateway llega por ``get_gateway`` y se recupera
de ``request.app.state.gateway``.

PR 5a del refactor del worker OT persistente. Plan:
``_plan/13_persistent_worker_impl.md``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.dependencies import get_gateway


router = APIRouter(prefix="/api/v1/tia", tags=["tia-connection"])


@router.get("/connection")
async def get_tia_connection(
    gateway: TIAProcessGateway = Depends(get_gateway),
) -> dict:
    """Devuelve el estado actual del worker OT persistente.

    El endpoint es **best-effort**: si el gateway está conectado pero
    ``get_project_info()`` o ``list_plcs()`` fallan (TIA cerrado entre
    el attach y la consulta, error COM/RPC, etc.), el ``state`` se
    preserva como la verdad sobre la conexión y ``project`` / ``plcs``
    vuelven vacíos. Esto evita que un error transitorio tire la SPA
    y permite al frontend reintentar en el siguiente polling.

    Returns:
        ``dict`` con ``state``, ``project``, ``plcs``,
        ``last_ping_ok_unix`` y ``last_error``.
    """
    # ``_connection_state`` solo existe si el gateway fue construido
    # con ``persistent=True``. En modo 1-shot (MCP, tests legacy)
    # no existe y el default ``"disconnected"`` es la lectura segura.
    state = getattr(gateway, "_connection_state", "disconnected")
    project_path = getattr(gateway, "_project_path", None)
    last_ping_ok = getattr(gateway, "_last_ping_ok", None)
    last_error = getattr(gateway, "_last_error", None)

    # Solo si estamos "connected" intentamos enriquecer con proyecto
    # y PLCs. En otros estados la cache del gateway puede estar stale
    # y forzar la lectura empeoraría la experiencia (latencia + 500).
    project: dict | None = None
    plcs: list[str] = []
    if state == "connected" and project_path:
        try:
            info = await gateway.get_project_info()
            if isinstance(info, dict):
                project = {
                    "name": info.get("name"),
                    "path": info.get("path"),
                    "version": info.get("version"),
                }
        except Exception:
            # best-effort: el state ya es la verdad; dejamos project=None
            project = None
        try:
            plc_list = await gateway.get_plcs()
            plcs = plc_list if isinstance(plc_list, list) else []
        except Exception:
            # best-effort idem
            plcs = []

    return {
        "state": state,
        "project": project,
        "plcs": plcs,
        "last_ping_ok_unix": last_ping_ok,
        "last_error": last_error,
    }


@router.post("/connect")
async def post_tia_connect(
    gateway: TIAProcessGateway = Depends(get_gateway),
) -> dict:
    """Fuerza reconexion del worker OT persistente.

    Delega en ``gateway.reconnect()`` (PR 6 implementa la logica).
    Mientras tanto, si el metodo no existe todavia o lanza
    ``NotImplementedError``, devolvemos un error claro al frontend
    en vez de propagar la excepcion (que daria un HTTP 500 inutil).

    Returns:
        ``{"ok": true, "state": <state>}`` si reconnect fue OK.
        ``{"ok": false, "state": ..., "error": "..."}`` en caso
        contrario.
    """
    try:
        await gateway.reconnect()
    except NotImplementedError:
        # PR 6 anade ``reconnect()``; mientras tanto el frontend recibe
        # un error legible en vez de un 500.
        return {
            "ok": False,
            "state": "disconnected",
            "error": "reconnect() pendiente (PR 6)",
        }
    except Exception as exc:
        return {
            "ok": False,
            "state": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    # Si reconnect() tuvo exito, el gateway actualiza su state.
    # Si no existe (gateway 1-shot), cae al default ``"connected"``.
    return {
        "ok": True,
        "state": getattr(gateway, "_connection_state", "connected"),
    }


@router.post("/disconnect")
async def post_tia_disconnect(
    gateway: TIAProcessGateway = Depends(get_gateway),
) -> dict:
    """Desconecta explicitamente el worker OT persistente.

    Delega en ``gateway.disconnect()`` (PR 6 implementa la logica).
    Misma politica de errores que ``/connect``: ``NotImplementedError``
    se traduce a una respuesta legible en vez de un 500.

    Returns:
        ``{"ok": true, "state": "disconnected"}`` si disconnect fue OK.
        ``{"ok": false, "state": ..., "error": "..."}`` en caso
        contrario.
    """
    try:
        await gateway.disconnect()
    except NotImplementedError:
        return {
            "ok": False,
            "state": "disconnected",
            "error": "disconnect() pendiente (PR 6)",
        }
    except Exception as exc:
        return {
            "ok": False,
            "state": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"ok": True, "state": "disconnected"}


__all__ = ["router"]
