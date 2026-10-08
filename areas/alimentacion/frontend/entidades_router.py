"""Router Flask del feature ENTIDADES: sync contra TIA Portal (D).

El endpoint de preview ``/api/v1/entidades/preview`` vive en
``entidades_preview_router.py`` (commit C).

Este router implementa el commit transaccional de entidades contra
TIA Portal. El FB ``FunctionEntidadesSincronizar`` (registrado en el
engine como ``entidades_sincronizar``) tiene la state machine de 11
etapas; este router solo orquesta: arranca el FB y devuelve el
``result`` con shape legacy-compatible con Disp.

Endpoint:
  POST /api/v1/entidades/sincronizar
    Body JSON: ``{plc_name: str}``. ``plc_name`` obligatorio.

    Dispara el FB ``entidades_sincronizar`` (11 etapas transaccionales:
    Tx A NMAX online + wait + re-export + edit XMLs + Tx B constantes +
    compile + Tx C comentarios + post preview). Bloquea el hilo de Flask
    hasta que el FB termina (``STEP_TIMEOUT_S=600s``). Cuando entra en
    estado terminal (``done`` o ``error``), devuelve el ``result`` con
    shape ``{success, message, operations, n_max_updates,
    post_sync_preview, compile_ok, compile_error, comments_sync}``.

    Returns:
      200 con shape completa (success=True + summary).
      400 si falta ``plc_name`` en el body.
      409 si el FB ya esta activo o terminal.
      500 si el FB no esta registrado o termino en error.
      504 si timeout.
"""
from __future__ import annotations

import logging
import time

from flask import Blueprint, current_app, jsonify, request

from core.infrastructure.log.log_web_bridge import install_web_level

logger = logging.getLogger(__name__)
# Asegura ``Logger.web/ok`` en tests/scripts (idempotente).
install_web_level()


bp = Blueprint(
    "area_alimentacion_entidades_sync",
    __name__,
    url_prefix="/api/v1/entidades",
)


def _get_engine():
    return current_app.config["ENGINE"]


def _get_fb(name: str):
    return _get_engine().get_fb(name)


@bp.post("/sincronizar")
def post_entidades_sincronizar():
    """Dispara el FB ``entidades_sincronizar`` para el ``plc_name`` del body.

    Bloquea el hilo de Flask hasta que el FB termina (max ~600s,
    ``STEP_TIMEOUT_S`` del FB). Cuando el FB entra en estado terminal
    (``done`` o ``error``), devuelve el ``result``.

    Importante: el FB NO hace ``save_project`` (politica del repo).
    El proyecto queda dirty en memoria de TIA Portal; el operario
    pulsa Save manual tras ver el resultado. La SPA muestra el hint
    en el message del result.
    """
    body = request.get_json(silent=True) or {}
    plc_name = body.get("plc_name")
    if not plc_name:
        return jsonify({
            "ok": False,
            "error": "plc_name (str) es obligatorio en el body",
        }), 400

    fb = _get_fb("entidades_sincronizar")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'entidades_sincronizar' no registrado en el engine",
        }), 500

    import asyncio
    logger.web(f"Sincronizando entidades de '{plc_name}' (11 etapas)...")
    started = asyncio.run(fb.start(plc_name=plc_name))
    if not started:
        return jsonify({
            "ok": False,
            "error": "FB 'entidades_sincronizar' ya activo o terminal. "
                     "Haz /disconnect y reintenta.",
        }), 409

    # ── Poll bloqueante ──
    poll_interval_s = 0.05
    elapsed = 0.0
    fb_step_timeout = getattr(fb, "STEP_TIMEOUT_S", 600.0)
    while not fb.is_terminal() and elapsed < fb_step_timeout:
        time.sleep(poll_interval_s)
        elapsed += poll_interval_s

    # ── Devolver el resultado ──
    if not fb.is_terminal():
        fb.cancel("timeout en /api/v1/entidades/sincronizar")
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

    result = fb.result or {
        "success": False,
        "message": "FB termino sin result",
        "plc_name": plc_name,
    }
    s = (result.get("operations") or 0) if isinstance(result, dict) else 0
    nmax_u = (result.get("n_max_updates") or 0) if isinstance(result, dict) else 0
    compile_ok = result.get("compile_ok") if isinstance(result, dict) else None
    logger.ok(
        f"Sincronizacion de entidades de '{plc_name}': "
        f"{s} ops, {nmax_u} NMAX updates, compile_ok={compile_ok}. "
        f"Recordar Save manual en TIA Portal."
    )
    return jsonify(result)


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Sync entidades)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_entidades_sync' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]