"""Router Flask del endpoint ``POST /api/v1/plcs/<name>/preview``.

Migrado del metodo legacy ``DispSyncInstancesUseCase.generar_prevision``
(sept-2026, ahora vive en el FB nuevo ``disp_generar_preview``). El
helper vive en ``areas/alimentacion/helpers/sync/disp_generate_preview.py``;
el FB ``FunctionDispGenerarPreview`` (registrado en el engine como
``disp_generar_preview``) tiene la state machine + tracker; este
router solo orquesta: arranca el FB y devuelve el ``result``.

Endpoint:
  POST /api/v1/plcs/<plc_name>/preview
    Body JSON opcional (no requiere params adicionales; plc_name viene
    del path). Dispara el FB ``disp_generar_preview`` y devuelve su
    ``result`` con shape legacy completa: ``{agregados, eliminados,
    renombrados, todos, nmax, summary}``.

  GET /api/v1/plcs/<plc_name>/preview/status
    Placeholder. Siempre devuelve 200 con ok=True.
"""
from __future__ import annotations

import logging
import time

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint(
    "area_alimentacion_disp_preview",
    __name__,
    url_prefix="/api/v1/sync/preview",
)


def _get_engine():
    return current_app.config["ENGINE"]


def _get_fb(name: str):
    return _get_engine().get_fb(name)


@bp.post("")
def post_disp_preview():
    """Dispara el FB ``disp_generar_preview`` para el ``plc_name`` del body.

    El ``plc_name`` viene en el body JSON (``{plc_name: str}``),
    no en el path. La SPA asi lo manda porque el path se reserva para
    la jerarquia de URLs (procesos usa ``/api/v1/procesos/sync/preview``).

    Bloquea el hilo de Flask hasta que el FB termina (max ~60s,
    ``STEP_TIMEOUT_S`` del FB). Cuando el FB entra en estado terminal
    (``done`` o ``error``), devuelve el ``result``.

    Returns:
        200 con shape legacy completo (agregados, eliminados,
        renombrados, todos, nmax, summary).
        400 si falta ``plc_name`` en el body.
        409 si el FB ya esta activo o terminal.
        500 si el FB no esta registrado o termino en error.
        504 si timeout.
    """
    body = request.get_json(silent=True) or {}
    plc_name = body.get("plc_name")
    if not plc_name:
        return jsonify({
            "ok": False,
            "error": "plc_name (str) es obligatorio en el body",
        }), 400

    fb = _get_fb("disp_generar_preview")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'disp_generar_preview' no registrado en el engine",
        }), 500

    import asyncio
    started = asyncio.run(fb.start(plc_name=plc_name))
    if not started:
        return jsonify({
            "ok": False,
            "error": "FB 'disp_generar_preview' ya activo o terminal. "
                     "Haz /disconnect y reintenta.",
        }), 409

    # ── Poll bloqueante ──
    poll_interval_s = 0.05
    elapsed = 0.0
    fb_step_timeout = getattr(fb, "STEP_TIMEOUT_S", 60.0)
    while not fb.is_terminal() and elapsed < fb_step_timeout:
        time.sleep(poll_interval_s)
        elapsed += poll_interval_s

    # ── Devolver el resultado ──
    if not fb.is_terminal():
        fb.cancel("timeout en /api/v1/sync/preview")
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
def get_disp_preview_status():
    """Placeholder. Devuelve siempre 200 con ok=True."""
    return jsonify({"ok": True})


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Preview)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_disp_preview' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]
