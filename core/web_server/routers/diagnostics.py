"""Flask blueprint para endpoints de diagnostics.

Endpoints:
  GET  /api/v1/logs              -> snapshot de LogBuffer.
  POST /api/v1/logs              -> push log desde frontend.
  POST /api/v1/logs/clear        -> vacia LogBuffer.
  GET  /api/v1/progress/current  -> snapshot de ProgressTracker.
  POST /api/v1/progress/clear    -> resetea ProgressTracker.

El endpoint ``/api/v1/state/dispositivos`` (vuelco del DataExcelCache
del AppState) era de este modulo, pero es especifico del area de
alimentacion. Se movio a
``areas/alimentacion/frontend/dispositivos_router.py`` y se monta
via ``AreaSpec.contributes_routers``.

Las dependencias se inyectan via ``current_app.config['_LAZY_*']``
(lazy resolvers). Ver ``core/web_server/app_flask.create_app``.
"""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("diagnostics", __name__, url_prefix="/api/v1")


def _get_log_buffer():
    return current_app.config["_LAZY_LOG_BUFFER"]()


def _get_progress_tracker():
    return current_app.config["_LAZY_PROGRESS_TRACKER"]()


@bp.get("/logs")
def get_logs():
    """Snapshot del LogBuffer para que la SPA lo pinte."""
    log_buffer = _get_log_buffer()
    return jsonify({"logs": log_buffer.snapshot()})


@bp.post("/logs/clear")
def clear_logs():
    """Vacia el LogBuffer (boton 'Limpiar consola')."""
    log_buffer = _get_log_buffer()
    log_buffer.clear()
    return jsonify({"cleared": True})


@bp.post("/logs")
def post_log():
    """Push de log desde el frontend al LogBuffer visible en ConsolaLogs."""
    log_buffer = _get_log_buffer()
    body = request.get_json(silent=True) or {}
    message = str(body.get("message", "")).strip()
    level = str(body.get("level", "info"))

    if not message:
        return jsonify({"ok": False, "error": "message requerido"}), 400
    if len(message) > 2000:
        return jsonify({"ok": False, "error": "message > 2000 chars"}), 400
    if level not in ("info", "success", "warning", "error"):
        return jsonify({"ok": False, "error": f"level invalido: {level}"}), 400

    if level == "success":
        log_buffer.success(message)
    elif level == "warning":
        log_buffer.warning(message)
    elif level == "error":
        log_buffer.error(message)
    else:
        log_buffer.info(message)
    return jsonify({"ok": True, "level": level, "message": message}), 201


@bp.get("/progress/current")
def get_progress():
    """Snapshot del ProgressTracker Singleton."""
    progress_tracker = _get_progress_tracker()
    snap = progress_tracker.snapshot()
    return jsonify({"ok": True, "progress": snap.to_dict()})


@bp.post("/progress/clear")
def clear_progress():
    """Resetea el ProgressTracker al estado vacio."""
    progress_tracker = _get_progress_tracker()
    progress_tracker.clear()
    return jsonify({"cleared": True})


__all__ = ["bp"]
