"""Flask blueprint para PLC FBs (Fase 4 / paso 4.4.7).

Equivalente sync de ``plc.py`` (FastAPI). Endpoints:
  POST /api/v1/plc/fb/<name>/start       -> arranca FB.
  POST /api/v1/plc/fb/<name>/disconnect -> desregistra FB del engine.
  GET  /api/v1/plc/fb/<name>/status     -> estado actual del FB.

Engine se lee de ``current_app.config['ENGINE']`` (inyectado por
create_app). FBs se registran en ``composition root`` (4.5.1+).
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("plc_fbs", __name__, url_prefix="/api/v1/plc/fb")


def _engine():
    return current_app.config["ENGINE"]


@bp.post("/<name>/start")
def start_fb(name: str):
    """Arranca el FB registrado bajo ``name``."""
    engine = _engine()
    fb = engine.get_fb(name)
    if fb is None:
        return jsonify({
            "error": f"FB '{name}' no registrado en el engine",
        }), 404

    body = request.get_json(silent=True) or {}
    params: dict[str, Any] = body.get("params") or {}

    # fb.start() es async; lo corremos via asyncio.run.
    import asyncio

    started = asyncio.run(fb.start(**params))
    return jsonify({"started": started, "nStep": fb.nStep})


@bp.post("/<name>/disconnect")
def disconnect_fb(name: str):
    """Desregistra el FB del engine. 204 si ok, 404 si no estaba."""
    engine = _engine()
    # Implementacion minimalista: pop del dict interno (engine no expone
    # unregister_fb publico).
    removed = engine._fbs.pop(name, None) is not None  # noqa: SLF001
    if not removed:
        return jsonify({
            "error": f"FB '{name}' no registrado en el engine",
        }), 404
    return "", 204


@bp.get("/<name>/status")
def get_fb_status(name: str):
    """Estado actual del FB (nStep, is_terminal, error_msg, result)."""
    engine = _engine()
    fb = engine.get_fb(name)
    if fb is None:
        return jsonify({
            "error": f"FB '{name}' no registrado en el engine",
        }), 404
    return jsonify({
        "name": name,
        "nStep": fb.nStep,
        "is_terminal": fb.is_terminal(),
        "error_msg": fb.error_msg,
        "result": fb.result,
    })


__all__ = ["bp"]
