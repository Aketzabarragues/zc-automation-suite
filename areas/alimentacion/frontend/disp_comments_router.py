"""Router Flask del endpoint ``POST /api/v1/plcs/<name>/disp-comments/apply``.

Migrado del use case legacy ``application/use_cases/disp_sync_comentarios.py``
(sept-2026). La logica vive en
``areas/alimentacion/helpers/sync/disp_comment_sync.py``; el FB
``FunctionSincronizarDispComentarios`` (registrado en el engine como
``sincronizar_disp_comentarios``) tiene la state machine + tracker;
este router solo orquesta: recibe el ``plc_name``, arranca el FB
y devuelve el ``result``.

Endpoint:
  POST /api/v1/plcs/<plc_name>/disp-comments/apply
    Body JSON opcional (actualmente solo usa ``plc_name`` del path).
    Dispara el FB ``sincronizar_disp_comentarios`` y devuelve su
    ``result`` cuando termina: shape legacy con ``{plc_name, success,
    applied, operations_executed, summary, details, warnings}``.

  GET /api/v1/plcs/<plc_name>/disp-comments/status
    Stub de estado (placeholder). Por ahora siempre devuelve 200 con
    ``{ok: True}``.

La operacion es pesada (export bulk + copytree + 6 dispatches al
worker OT, puede tardar 1-3 min). El poll del router respeta el
timeout del FB (``STEP_TIMEOUT_S = 300s``). Si excede, devuelve 504.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from flask import Blueprint, current_app, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint(
    "area_alimentacion_disp_comments",
    __name__,
    url_prefix="/api/v1/plcs/<string:plc_name>/disp-comments",
)


def _get_engine():
    return current_app.config["ENGINE"]


def _get_fb(name: str):
    return _get_engine().get_fb(name)


@bp.post("/apply")
def post_disp_comments_apply(plc_name: str):
    """Dispara el FB ``sincronizar_disp_comentarios`` para ``plc_name``.

    Bloquea el hilo de Flask hasta que el FB termina (max ~300s,
    ``STEP_TIMEOUT_S`` del FB). Cuando el FB entra en estado
    terminal (``done`` o ``error``), devuelve el ``result``.

    Returns:
        200 con el shape legacy completo (success, applied,
        operations_executed, summary, details, warnings).
        409 si el FB ya esta activo o terminal.
        500 si el FB no esta registrado en el engine o termino en error.
        504 si el FB excedio el timeout.
    """
    # ── Arrancar el FB ──
    fb = _get_fb("sincronizar_disp_comentarios")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'sincronizar_disp_comentarios' no registrado "
                     "en el engine",
        }), 500

    import asyncio
    started = asyncio.run(fb.start(plc_name=plc_name))
    if not started:
        return jsonify({
            "ok": False,
            "error": "FB 'sincronizar_disp_comentarios' ya activo o "
                     "terminal. Haz /disconnect y reintenta.",
        }), 409

    # ── Esperar al resultado (poll bloqueante) ──
    # La operacion es pesada (1-3 min). STEP_TIMEOUT_S=300s; el
    # cliente debe esperar MAS (timeout del bucket SLOW en api.js
    # es 600s).
    poll_interval_s = 0.1  # 100ms (operacion larga, no hace falta
                           # poll agresivo)
    elapsed = 0.0
    fb_step_timeout = getattr(fb, "STEP_TIMEOUT_S", 300.0)
    while not fb.is_terminal() and elapsed < fb_step_timeout:
        time.sleep(poll_interval_s)
        elapsed += poll_interval_s

    # ── Devolver el resultado ──
    if not fb.is_terminal():
        # Timeout: cancelar el FB para no dejarlo colgado.
        fb.cancel("timeout en /api/v1/plcs/<name>/disp-comments/apply")
        return jsonify({
            "ok": False,
            "error": f"timeout tras {fb_step_timeout:.1f}s sin terminar",
        }), 504

    if fb.nStep == fb.n_error:
        return jsonify({
            "ok": False,
            "error": fb.error_msg or "FB termino en error",
            "nStep": fb.nStep,
        }), 500

    return jsonify(fb.result or {"ok": True, "plc_name": plc_name})


@bp.get("/status")
def get_disp_comments_status(plc_name: str):
    """Placeholder. Devuelve siempre 200 con ok=True.

    Pensado para futuras ampliaciones (progreso live via SSE,
    cancelacion explicita, preview sin tocar TIA, etc.). Por ahora
    el FB se ejecuta de forma sincrona en el POST y no hay estado
    persistente que reportar entre llamadas.
    """
    return jsonify({"ok": True, "plc_name": plc_name})


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de DispComments).

    Llamado por el ``_build_all_routers`` central del area desde
    ``__init__.py``. Registra el blueprint de este modulo en la
    Flask app.
    """
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_disp_comments' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]
