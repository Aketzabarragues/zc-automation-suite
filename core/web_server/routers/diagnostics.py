"""Flask blueprint para endpoints de diagnostics.

Endpoints:
  GET  /api/v1/state/dispositivos -> vuelca AppState.
  GET  /api/v1/logs              -> snapshot de LogBuffer.
  POST /api/v1/logs              -> push log desde frontend.
  POST /api/v1/logs/clear        -> vacia LogBuffer.
  GET  /api/v1/progress/current  -> snapshot de ProgressTracker.
  POST /api/v1/progress/clear    -> resetea ProgressTracker.

Las dependencias se inyectan via ``current_app.config['_LAZY_*']``
(lazy resolvers). Ver ``core/web_server/app_flask.create_app``.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("diagnostics", __name__, url_prefix="/api/v1")


def _extract_software_from_cache(state: Any) -> dict[str, Any]:
    """Extrae 4 dominios de software + flag desde el ExcelCache del AppState."""
    empty: dict[str, Any] = {
        "procesos": [],
        "parametros_int": [],
        "parametros_real": [],
        "alarmas": [],
        "software_parsers_implemented": False,
    }
    cache = getattr(state, "excel_cache", None)
    if cache is None:
        return empty
    try:
        return {
            "procesos": [dataclasses.asdict(p) for p in cache.procesos],
            "parametros_int": [dataclasses.asdict(p) for p in cache.parametros_int],
            "parametros_real": [dataclasses.asdict(p) for p in cache.parametros_real],
            "alarmas": [dataclasses.asdict(a) for a in cache.alarmas],
            "software_parsers_implemented": bool(
                getattr(cache, "software_parsers_implemented", False)
            ),
        }
    except Exception as exc:
        logger.warning("Error extrayendo software del cache: %s", exc)
        return empty


def _get_app_state():
    return current_app.config["_LAZY_APP_STATE"]()


def _get_config_manager():
    return current_app.config["CONFIG_MANAGER"]


def _get_log_buffer():
    return current_app.config["_LAZY_LOG_BUFFER"]()


def _get_progress_tracker():
    return current_app.config["_LAZY_PROGRESS_TRACKER"]()


@bp.get("/state/dispositivos")
def state_dispositivos():
    """Vuelca AppState a JSON para el Inspector IT."""
    state = _get_app_state()
    config_manager = _get_config_manager()

    dispositivos_payload: dict[str, list[dict[str, Any]]] = {}
    for hw in config_manager.list_hw_types_active():
        target = config_manager.get_excel_target_for(hw)
        if target is None:
            continue
        canonica = target.get("canonical", "")
        if not canonica:
            continue
        dispositivos_payload[canonica] = [
            dataclasses.asdict(d) for d in state.get_devices(hw)
        ]

    return jsonify({
        "ok": True,
        "dimensiones": (
            state.dimensiones.to_api_dict()
            if state.dimensiones is not None
            else {}
        ),
        "dispositivos": dispositivos_payload,
        **_extract_software_from_cache(state),
    })


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
