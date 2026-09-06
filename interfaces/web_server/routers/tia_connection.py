"""Router REST para el estado del worker OT persistente.

Tres endpoints:

  GET  /api/v1/tia/connection  -> estado actual del worker.
  POST /api/v1/tia/connect     -> fuerza el attach al portal TIA.
  POST /api/v1/tia/disconnect  -> hace el detach del portal TIA.

Shape del GET::

    {
      "state": "idle" | "connecting" | "connected" | "disconnected" | "error",
      "project": {"name": str, "path": str, "version": str} | null,
      "plcs": [str, ...],
      "last_ping_ok_unix": float | null,
      "last_error": str | null,
      "project_changed": bool,
      "worker_alive": bool,
      "pid": int | null
    }

    ``project_changed`` es un flag one-shot: ``True`` solo en el primer
    poll tras detectar que el operario abrio un proyecto distinto en
    TIA Portal sin pasar por la app. El gateway lo resetea a ``False``
    en el mismo read para que la SPA no re-notifique el mismo cambio
    en cada polling.

    ``worker_alive`` es ortogonal a ``state``: subproceso worker vivo
    aunque el attach a TIA Portal haya fallado.

    ``pid`` es el PID del proceso TIA Portal attached. Solo se expone
    cuando ``state == "connected"`` (fuera de ese estado el portal no
    esta attached y el PID no significa nada). Util para Task Manager
    cuando hay varios TIA abiertos.

Las dependencias se inyectan via ``Depends``; ver
``interfaces/web_server/dependencies.py``.
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
        ``last_ping_ok_unix``, ``last_error``, ``project_changed``,
        ``worker_alive`` y ``pid`` (este ultimo solo si
        ``state == "connected"``).
    """
    # ``_connection_state`` solo existe si el gateway fue construido
    # con ``persistent=True``. En modo 1-shot (MCP, tests legacy)
    # no existe y el default ``"disconnected"`` es la lectura segura.
    state = getattr(gateway, "_connection_state", "disconnected")
    project_path = getattr(gateway, "_project_path", None)
    last_ping_ok = getattr(gateway, "_last_ping_ok", None)
    last_error = getattr(gateway, "_last_error", None)
    # ``project_changed`` (PR 7) es un flag one-shot: ``True`` solo
    # en el primer poll tras detectar que el operario abrio un
    # proyecto distinto en TIA Portal sin pasar por la app. Despues
    # se resetea a ``False`` para no notificar el mismo cambio en
    # cada polling del frontend. ``getattr`` defensivo: si la app
    # corre con un build anterior a PR 7, el atributo no existe y
    # el default ``False`` evita que la SPA reciba un campo
    # ``null`` inesperado.
    project_changed = bool(
        getattr(gateway, "consume_project_changed", lambda: False)()
    )
    # ``worker_alive`` (sept-2026) indica si el subproceso del
    # worker persistente esta vivo, INDEPENDIENTEMENTE de si el
    # attach a TIA Portal tuvo exito. Ortogonal a ``state`` (que
    # refleja el attach). El ``WorkerStatusIndicator`` del topbar
    # lo lee reactivamente. ``getattr`` defensivo: si la app corre
    # con un build anterior, retorna ``False`` y el indicador se
    # queda gris (estado "no podemos saber" — aceptable).
    worker_alive = bool(
        getattr(gateway, "is_worker_alive", lambda: False)()
    )
    # ``pid`` del portal TIA Portal (sept-2026). Solo se expone
    # cuando el gateway esta ``"connected"``; en otros estados el
    # portal attached no existe y el PID careceria de sentido. Lo
    # setea ``gateway.connect()`` tras un ``attach_portal`` exitoso
    # (a partir de la respuesta ``{"pid": <int>}`` del worker OT)
    # y lo limpia ``gateway.disconnect()``. ``getattr`` defensivo:
    # si la app corre con un build anterior, retorna ``None`` y el
    # frontend ve ``pid: null`` (no rompe la SPA, simplemente no
    # muestra el PID).
    pid: int | None = None
    if state == "connected":
        raw_pid = getattr(gateway, "_last_portal_pid", None)
        if isinstance(raw_pid, int):
            pid = raw_pid

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
        "project_changed": project_changed,
        "worker_alive": worker_alive,
        "pid": pid,
    }


@router.post("/connect")
async def post_tia_connect(
    gateway: TIAProcessGateway = Depends(get_gateway),
) -> dict:
    """Envia el attach al portal TIA Portal y transiciona a ``"connected"``.

    Delega en ``gateway.connect()`` (sept-2026, state machine
    refactor). El worker persistente ya esta vivo (estado ``"idle"``
    desde el startup); este endpoint es el equivalente asincrono del
    boton "Conectar" del topbar. La SPA lo invoca cuando el operario
    decide conectar a TIA Portal.

    ``connect()`` es idempotente: si ya estamos connected, retorna
    ``TIAConnectionError`` (el frontend deberia chequear el state
    antes de llamar para evitar errores redundantes). El router NO
    filtra ese caso: la SPA es quien decide cuando llamar.

    Returns:
        ``{"ok": true, "state": "connected", "pid": <int>}`` si el
        attach tuvo exito (el ``pid`` es el PID del proceso TIA
        Portal al que acabamos de attach, util para Task Manager).
        ``{"ok": true, "state": "connected", "pid": null}`` si el
        worker no devolvio PID (build antiguo, error parcial).
        ``{"ok": false, "state": "error", "error": "..."}`` si
        falla (portal cerrado, ya conectado, worker muerto, etc.).
    """
    try:
        await gateway.connect()
    except Exception as exc:
        # ``connect()`` solo aplica a gateway.persistent=True. En
        # modo 1-shot (MCP, tests legacy) lanza ``TIAConnectionError``
        # y el frontend recibe un error legible en vez de un 500.
        return {
            "ok": False,
            "state": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    # Si ``connect()`` tuvo exito, el gateway actualizo su state a
    # ``"connected"`` y cacheo el ``_last_portal_pid`` en el camino.
    # Si la app corre con un build anterior (atributo no existe), el
    # ``getattr`` defensivo retorna ``None`` y el frontend ve
    # ``pid: null`` (no rompe la SPA).
    state = getattr(gateway, "_connection_state", "connected")
    raw_pid = getattr(gateway, "_last_portal_pid", None)
    pid: int | None = raw_pid if isinstance(raw_pid, int) else None
    return {
        "ok": True,
        "state": state,
        "pid": pid,
    }


@router.post("/disconnect")
async def post_tia_disconnect(
    gateway: TIAProcessGateway = Depends(get_gateway),
) -> dict:
    """Envia el detach del portal TIA Portal y transiciona a ``"idle"``.

    Delega en ``gateway.disconnect()`` (sept-2026, state machine
    refactor). A diferencia del round anterior, este metodo NO mata
    el subproceso worker: el worker sigue vivo en estado ``"idle"``,
    listo para un futuro ``connect()`` sin pagar el coste de un nuevo
    subproceso (~200 MB con ``siemens_tia_scripting.pyd`` cargado).

    El equivalente asincrono del boton "Desconectar" del topbar.

    Returns:
        ``{"ok": true, "state": "idle"}`` si el detach tuvo exito.
        ``{"ok": false, "state": "error", "error": "..."}`` si
        falla (e.g. ``disconnect()`` solo aplica a gateway persistente
        y el modo 1-shot lanzaria ``TIAConnectionError``; el frontend
        lo vera como un error legible en vez de un 500).
    """
    try:
        await gateway.disconnect()
    except Exception as exc:
        return {
            "ok": False,
            "state": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    # ``disconnect()`` siempre transiciona a ``"idle"`` al final (incluso
    # si el detach_portal fallo: el estado del gateway refleja "idle"
    # de todos modos). Ver ``gateway.disconnect()`` para el detalle.
    return {"ok": True, "state": "idle"}


__all__ = ["router"]
