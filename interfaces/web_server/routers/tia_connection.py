"""Flask blueprint para /api/v1/tia/* (Fase 4 / paso 4.4.2).

Equivalente sync del router FastAPI ``tia_connection.py``. En el
modelo OB1 (sin subproceso worker), la semantica cambia:

  - state == "connected"   <=> tia_client.wrapper is not None.
  - state == "disconnected" <=> tia_client.wrapper is None.
  - No hay pid / worker_alive (mismo proceso, no subproceso).
  - project y plcs se leen directamente via tia_client.dispatch
    (sync) si wrapper esta attached.

Migrar los otros 6 routers sigue el mismo patron: ver
4.4.2 commit message y AGENTS.md §"Como anadir un blueprint".
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint("tia_connection", __name__, url_prefix="/api/v1/tia")


@bp.get("/connection")
def get_tia_connection():
    """Estado del cliente TIA en OB1 (sin subproceso worker)."""
    tia_client = current_app.config["TIA_CLIENT"]
    portal = tia_client.wrapper
    state = "connected" if portal is not None else "disconnected"

    project: dict | None = None
    plcs: list[str] = []
    if state == "connected":
        # Best-effort: errores transitorios de TIA Portal no tumbar el endpoint.
        try:
            info = tia_client.dispatch("get_project_info")
            if info.get("ok") and isinstance(info.get("result"), dict):
                result = info["result"]
                # Si el handler reporta name=None (property fallo), tratamos
                # como sin info: la SPA distingue "no hay info" vs
                # "info parcial" (todos None).
                if result.get("name") is not None:
                    project = {
                        "name": result.get("name"),
                        "path": result.get("path"),
                        "version": result.get("version"),
                    }
        except Exception:
            logger.warning("get_tia_connection: get_project_info fallo", exc_info=True)
            project = None
        try:
            plc_resp = tia_client.dispatch("list_plcs")
            if plc_resp.get("ok") and isinstance(plc_resp.get("result"), dict):
                plcs_data = plc_resp["result"].get("plcs", [])
                plcs = [p["name"] for p in plcs_data if "name" in p]
        except Exception:
            logger.warning("get_tia_connection: list_plcs fallo", exc_info=True)
            plcs = []

    return jsonify({
        "state": state,
        "project": project,
        "plcs": plcs,
        # En OB1 no hay subproceso; estos campos son siempre None/False.
        "last_ping_ok_unix": None,
        "last_error": None,
        "project_changed": False,
        "worker_alive": True,  # mismo proceso, siempre vivo
        "pid": None,
    })


@bp.post("/connect")
def post_tia_connect():
    """Attach al portal TIA Portal (persistente).

    Llama al command ``attach_portal``: abre un portal via
    ``ts.open_portal(...)`` y lo attach al tia_client. El portal queda
    vivo hasta ``disconnect`` (o hasta que se cambie de proyecto).

    Los siguientes comandos (sync disp, scan blocks, compile PLC, etc.)
    usan el mismo portal — sin reconectar por comando.
    """
    tia_client = current_app.config["TIA_CLIENT"]
    if tia_client.ts is None:
        return jsonify({
            "ok": False,
            "state": "disconnected",
            "error": "Modulo siemens_tia_scripting no attached.",
        }), 503
    result = tia_client.dispatch("attach_portal")
    if result.get("ok"):
        return jsonify({
            "ok": True,
            "state": "connected",
            "pid": None,
            "worker_alive": True,
            "already_attached": result["result"].get("already_attached", False),
        })
    return jsonify({
        "ok": False,
        "state": "disconnected",
        "error": result.get("error", "unknown"),
        "worker_alive": True,
    }), 500


@bp.post("/disconnect")
def post_tia_disconnect():
    """Detach del portal TIA Portal (lo cierra)."""
    tia_client = current_app.config["TIA_CLIENT"]
    result = tia_client.dispatch("detach_portal")
    return jsonify({
        "ok": result.get("ok", False),
        "state": "disconnected" if result.get("ok") else "connected",
        "worker_alive": True,
    })


__all__ = ["bp"]
