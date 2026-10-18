"""Flask blueprint para el editor de propiedades de bloques TIA.

Endpoints:
  POST /api/v1/blocks/edit/prepare -> arranca FB ``block_edit_prepare``.
  POST /api/v1/blocks/edit/apply    -> placeholder 501 (commit 7).
  GET  /api/v1/blocks/edit/<name>/status -> estado actual del FB.

Engine se lee de ``current_app.config['ENGINE']`` (inyectado por
create_app). FB ``block_edit_prepare`` registrado en
``core.composition.register_core_fbs.register()``.

Equivalente sync de los endpoints FastAPI del plan FASE 2 (v3.1).
"""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from core.infrastructure.log.log_web_bridge import install_web_level

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()

bp = Blueprint("blocks_edit", __name__, url_prefix="/api/v1/blocks/edit")


# Timeout backend para el ``block_edit_prepare``: el FB exporta N bloques
# a SD y parsea el ``.s7dcl``. En S7-1500 con 30+ bloques seleccionados
# el lote puede tardar 60-90s. 120s cubre holgadamente.
PREPARE_TIMEOUT_S = 120.0

# Poll bloqueante del FB en el handler sync de Flask.
_POLL_INTERVAL_S = 0.05


def _engine():
    return current_app.config["ENGINE"]


@bp.post("/prepare")
def prepare_edit():
    """Arranca el FB ``block_edit_prepare`` y devuelve el resultado.

    Body JSON esperado::

        {
            "plc_name": "PLC_1",
            "selected_block_paths": ["2000_Dispositivos/DB2000_ED", ...]
        }

    Returns:
        - 200 + ``{"ok": True, "result": ..., "nStep": ...}`` si OK.
        - 400 si faltan ``plc_name`` o ``selected_block_paths``.
        - 409 si el FB ya esta corriendo (o terminal reciente).
        - 500 si el FB no esta registrado.
        - 504 si timeout.
        - 500 si el FB termina en error.
    """
    import asyncio
    import time

    engine = _engine()
    fb = engine.get_fb("block_edit_prepare")
    if fb is None:
        return jsonify({
            "error": "FB 'block_edit_prepare' no registrado en el engine",
        }), 500

    body = request.get_json(silent=True) or {}
    plc_name = body.get("plc_name")
    selected = body.get("selected_block_paths") or []
    if not plc_name or not selected:
        return jsonify({
            "error": "plc_name y selected_block_paths son obligatorios",
        }), 400

    started = asyncio.run(fb.start(
        plc_name=plc_name,
        selected_block_paths=selected,
    ))
    if not started:
        return jsonify({
            "error": "FB 'block_edit_prepare' ya activo o terminal. "
                     "Haz /disconnect y reintenta.",
        }), 409

    # Poll bloqueante hasta que el FB entre en estado terminal.
    elapsed = 0.0
    while not fb.is_terminal() and elapsed < PREPARE_TIMEOUT_S:
        time.sleep(_POLL_INTERVAL_S)
        elapsed += _POLL_INTERVAL_S

    if not fb.is_terminal():
        try:
            asyncio.run(fb.cancel(f"timeout en /prepare ({PREPARE_TIMEOUT_S:.0f}s)"))
        except Exception:
            pass
        return jsonify({
            "error": f"timeout tras {PREPARE_TIMEOUT_S:.0f}s sin terminar",
        }), 504

    if fb.nStep == fb.n_error:
        return jsonify({
            "error": fb.error_msg or "FB termino en error",
        }), 500

    return jsonify({
        "ok": True,
        "result": fb.result,
        "nStep": fb.nStep,
    })


@bp.post("/apply")
def apply_edit():
    """Placeholder 501: el endpoint ``/apply`` se entregara en commit 7."""
    return jsonify({
        "error": "endpoint pendiente commit 7",
    }), 501


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
