"""Router Flask del endpoint ``POST /api/v1/plcs/<name>/sync/commit``.

Migrado del metodo legacy ``DispSyncInstancesUseCase.ejecutar_transaccion``
(sept-2026, ahora vive en el FB nuevo ``disp_sincronizar``). El helper
vive en ``areas/alimentacion/helpers/sync/disp_sync.py``; el FB
``FunctionDispSincronizarDispositivos`` (registrado en el engine como
``disp_sincronizar``) tiene la state machine + tracker; este router
solo orquesta: arranca el FB y devuelve el ``result``.

Endpoint:
  POST /api/v1/plcs/<plc_name>/sync/commit
    Body JSON opcional (plc_name viene del path). Dispara el FB
    ``disp_sincronizar`` y devuelve su ``result`` con shape legacy
    completa: ``{success, message, operations, n_max_updates,
    post_sync_preview, compile_ok, compile_error, comments_sync}``.

  GET /api/v1/plcs/<plc_name>/sync/commit/status
    Placeholder. Siempre devuelve 200 con ok=True.

Notas de timing:
  - Operacion PESADA: export bulk + 2 tx TIA (Tx A: N_MAX renames,
    Tx B: devices offline) + compile_blocks (6 DBs) + apply
    comentarios (6 dispatches) + post_preview.
  - TIA V21 puede tardar 1-10 minutos para un PLC con 200+ bloques
    y 6 DBs de dispositivos redimensionados.
  - STEP_TIMEOUT_S del FB: 600s (10 min).
  - Cliente API (frontend): debe usar el bucket SLOW_TIMEOUT_MS
    (600s, 10 min) en api.js para no abortar antes de tiempo.
"""
from __future__ import annotations

import logging
import time

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint(
    "area_alimentacion_disp_sync",
    __name__,
    url_prefix="/api/v1/sync/commit",
)


def _get_engine():
    return current_app.config["ENGINE"]


def _get_fb(name: str):
    return _get_engine().get_fb(name)


@bp.post("")
def post_disp_sync_commit():
    """Dispara el FB ``disp_sincronizar`` para el ``plc_name`` del body.

    El ``plc_name`` viene en el body JSON (``{plc_name: str,
    prevision: dict}``), no en el path. La SPA asi lo manda porque
    el path se reserva para la jerarquia de URLs (procesos usa
    ``/api/v1/procesos/sync/commit``).

    Bloquea el hilo de Flask hasta que el FB termina (max ~600s,
    ``STEP_TIMEOUT_S`` del FB). Cuando el FB entra en estado
    terminal (``done`` o ``error``), devuelve el ``result``.

    Returns:
        200 con shape legacy completo.
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

    fb = _get_fb("disp_sincronizar")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'disp_sincronizar' no registrado en el engine",
        }), 500

    import asyncio
    started = asyncio.run(fb.start(plc_name=plc_name))
    if not started:
        return jsonify({
            "ok": False,
            "error": "FB 'disp_sincronizar' ya activo o terminal. "
                     "Haz /disconnect y reintenta.",
        }), 409

    # ── Poll bloqueante ──
    # Operacion larga, no hace falta poll agresivo (100ms).
    poll_interval_s = 0.1
    elapsed = 0.0
    fb_step_timeout = getattr(fb, "STEP_TIMEOUT_S", 600.0)
    while not fb.is_terminal() and elapsed < fb_step_timeout:
        time.sleep(poll_interval_s)
        elapsed += poll_interval_s

    # ── Devolver el resultado ──
    if not fb.is_terminal():
        fb.cancel("timeout en /api/v1/sync/commit")
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
def get_disp_sync_status():
    """Placeholder. Devuelve siempre 200 con ok=True."""
    return jsonify({"ok": True})


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de SyncCommit)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_disp_sync' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]
