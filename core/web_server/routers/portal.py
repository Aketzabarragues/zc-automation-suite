"""Flask blueprint para portal/plcs/project.

Endpoints:
  POST /api/v1/portal/attach     -> hot-attach a TIA Portal abierto.
  POST /api/v1/portal/open-new  -> cold start (abre .apxx).
  GET  /api/v1/plcs              -> lista PLCs del proyecto activo.
  GET  /api/v1/portal/project-info -> info del proyecto.

Todos delegan en tia_client.submit_and_wait() (sync, mismo proceso).
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("portal", __name__, url_prefix="/api/v1")


def _tia():
    return current_app.config["TIA_CLIENT"]


def _log():
    return current_app.config["_LAZY_LOG_BUFFER"]()


@bp.post("/portal/attach")
def portal_attach():
    """HOT-Attach a TIA Portal ya abierto."""
    tia = _tia()
    log = _log()
    log.info("[portal/attach] Adjuntando a TIA Portal (OB1).")
    out = tia.dispatch("attach_portal")
    if not out.get("ok"):
        log.error(
            f"[portal/attach] Fallo: {out.get('error', '?')}"
        )
        return jsonify({"ok": False, "error": out.get("error", "?")}), 500
    log.success("[portal/attach] Adjuntado OK.")
    return jsonify({"ok": True, "result": out.get("result")})


@bp.post("/portal/open-new")
def portal_open_new():
    """Cold start: abre un .apxx y carga el proyecto."""
    tia = _tia()
    log = _log()
    body = request.get_json(silent=True) or {}
    project_file_path = str(body.get("project_file_path", "")).strip()
    if not project_file_path:
        return jsonify({
            "ok": False,
            "error": "project_file_path requerido",
        }), 400

    log.info(f"[portal/open] Abriendo proyecto {project_file_path} (OB1).")
    out = tia.dispatch(
        "open_new_portal", {"project_file_path": project_file_path}
    )
    if not out.get("ok"):
        log.error(f"[portal/open] Fallo: {out.get('error', '?')}")
        return jsonify({"ok": False, "error": out.get("error", "?")}), 500
    log.success(f"[portal/open] Proyecto abierto: {project_file_path}.")
    return jsonify({"ok": True, "result": out.get("result")})


@bp.get("/plcs")
def listar_plcs():
    """Lista PLCs del TIA Portal conectado (best-effort: no tumba el server)."""
    tia = _tia()
    log = _log()
    log.info("[portal/plcs] Listando PLCs (OB1).")
    out = tia.dispatch("list_plcs")
    if not out.get("ok"):
        log.error(f"[portal/plcs] Fallo: {out.get('error', '?')}")
        return jsonify({
            "ok": False,
            "error": (
                "TIA Portal no conectado. "
                "Haga Attach u Open New primero."
            ),
            "detail": out.get("error", "?"),
        })
    plcs = out.get("result", {}).get("plcs", [])
    log.success(f"[portal/plcs] Listados {len(plcs)} PLCs.")
    return jsonify({"ok": True, "plcs": plcs})


@bp.get("/portal/project-info")
def get_project_info():
    """Nombre y propiedades basicas del proyecto TIA activo."""
    tia = _tia()
    log = _log()
    log.info("[portal/project] Consultando informacion del proyecto (OB1).")
    out = tia.dispatch("get_project_info")
    if not out.get("ok"):
        log.error(f"[portal/project] Fallo: {out.get('error', '?')}")
        return jsonify({
            "ok": False,
            "error": (
                "TIA Portal no conectado. "
                "Haga Attach u Open New primero."
            ),
            "detail": out.get("error", "?"),
        })
    info = out.get("result", {})
    log.success(f"[portal/project] Proyecto: {info.get('name', '(sin nombre)')}.")
    return jsonify({"ok": True, "project_info": info})


__all__ = ["bp"]
