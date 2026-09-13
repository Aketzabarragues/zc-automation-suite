"""Flask blueprint para /api/v1/tia/* (subsistema TIA-loop).

Endpoints:
  GET  /api/v1/tia/connection   estado del subsistema TIA + project + plcs
  POST /api/v1/tia/connect      abre portal (attach_portal)
  POST /api/v1/tia/disconnect   cierra portal (detach_portal)

El wrapper .NET vive en el tia-loop (no aqui). Flask solo encola via
submit_and_wait y recibe la respuesta; nunca toca el wrapper directamente.
"""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint("tia_connection", __name__, url_prefix="/api/v1/tia")

# Timeout para abrir/cerrar portal (segundos). Generoso porque TIA Portal
# puede tardar al attach si hay proyecto en red.
ATTACH_TIMEOUT_S = 10.0


@bp.get("/connection")
def get_tia_connection() -> Any:
    """Estado del subsistema TIA: state, project (si conectado), plcs."""
    tia_client = current_app.config["TIA_CLIENT"]
    state = tia_client.state
    portal_alive = tia_client.wrapper is not None

    project: dict | None = None
    plcs: list[str] = []

    if state == "connected" and portal_alive:
        # Best-effort: errores transitorios no tumbar el endpoint.
        try:
            info = tia_client.submit_and_wait("get_project_info", timeout=2.0)
            if info.get("ok") and isinstance(info.get("result"), dict):
                result = info["result"]
                if result.get("name") is not None:
                    project = {
                        "name": result.get("name"),
                        "path": result.get("path"),
                        "version": result.get("version"),
                    }
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_tia_connection: get_project_info fallo: %s", exc)
            project = None
        try:
            plc_resp = tia_client.submit_and_wait("list_plcs", timeout=2.0)
            if plc_resp.get("ok") and isinstance(plc_resp.get("result"), dict):
                plcs_data = plc_resp["result"].get("plcs", [])
                plcs = [p["name"] for p in plcs_data if "name" in p]
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_tia_connection: list_plcs fallo: %s", exc)
            plcs = []

    return jsonify({
        "state": state,
        "project": project,
        "plcs": plcs,
        "last_ping_ok_unix": None,
        "last_error": None,
        "project_changed": False,
        "worker_alive": True,   # mismo proceso
        "pid": None,
    })


@bp.post("/connect")
def post_tia_connect():
    """Attach al portal TIA Portal (persistente)."""
    tia_client = current_app.config["TIA_CLIENT"]
    if tia_client.ts is None:
        return jsonify({
            "ok": False,
            "state": tia_client.state,
            "error": "modulo siemens_tia_scripting no attached",
        }), 503
    try:
        result = tia_client.submit_and_wait(
            "attach_portal", timeout=ATTACH_TIMEOUT_S,
        )
    except TimeoutError as exc:
        return jsonify({
            "ok": False,
            "state": tia_client.state,
            "error": f"timeout: {exc}",
        }), 504
    if result.get("ok"):
        return jsonify({
            "ok": True,
            "state": tia_client.state,
            "pid": None,
            "worker_alive": True,
            "already_attached": result["result"].get("already_attached", False),
        })
    return jsonify({
        "ok": False,
        "state": tia_client.state,
        "error": result.get("error", "unknown"),
        "worker_alive": True,
    }), 500


@bp.post("/disconnect")
def post_tia_disconnect():
    """Detach del portal TIA Portal (lo cierra)."""
    tia_client = current_app.config["TIA_CLIENT"]
    try:
        result = tia_client.submit_and_wait(
            "detach_portal", timeout=ATTACH_TIMEOUT_S,
        )
    except TimeoutError as exc:
        return jsonify({
            "ok": False,
            "state": tia_client.state,
            "error": f"timeout: {exc}",
        }), 504
    return jsonify({
        "ok": result.get("ok", False),
        "state": tia_client.state,
        "worker_alive": True,
    })


__all__ = ["bp"]
