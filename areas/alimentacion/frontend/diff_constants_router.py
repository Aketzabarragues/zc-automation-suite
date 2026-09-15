"""Router Flask del endpoint ``POST /api/v1/plcs/<name>/diff-constants``.

Migrado del use case legacy ``application/use_cases/disp_diff_constants.py``
(sept-2026). La logica pura vive en
``areas/alimentacion/helpers/sync/diff_constants.py``; el FB
``FunctionDiffConstants`` (registrado en el engine como
``diff_constants``) tiene la state machine + tracker; este router solo
orquesta: recibe los 6 params, arranca el FB y devuelve el ``result``.

Endpoint:
  POST /api/v1/plcs/<plc_name>/diff-constants
    Body JSON:
      {
        "config_table_name":     str,
        "current_nmax_state":    {nombre: valor_int},
        "desired_nmax_state":    {nombre: valor_int},
        "current_device_state":  {valor_int_str: nombre},
        "desired_device_state":  {nombre: valor_int}
      }
    Dispara el FB ``diff_constants`` y devuelve su ``result`` cuando
    termina: ``{nmax_ops, rename_ops, summary}``.

  GET /api/v1/plcs/<plc_name>/diff-constants/status
    Stub de estado (placeholder para futuras ampliaciones, p. ej.
    progreso live via SSE). Por ahora siempre devuelve 200 con
    ``{ok: True}``.

Como el helper es CPU puro, el FB termina casi inmediatamente
(2 ticks del engine a 50ms = ~100ms). El poll del router respeta
el timeout del FB (``STEP_TIMEOUT_S = 30s``) por si el engine esta
cargado con otros FBs.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint(
    "area_alimentacion_diff_constants",
    __name__,
    url_prefix="/api/v1/plcs/<string:plc_name>/diff-constants",
)


def _get_engine():
    return current_app.config["ENGINE"]


def _get_fb(name: str):
    return _get_engine().get_fb(name)


@bp.post("")
def post_diff_constants(plc_name: str):
    """Recibe los 4 estados y dispara el FB ``diff_constants``.

    Bloquea el hilo de Flask hasta que el FB termina (max ~30s,
    ``STEP_TIMEOUT_S`` del FB). Cuando el FB entra en estado
    terminal (``done`` o ``error``), devuelve el ``result``.

    Returns:
        200 con ``{"ok": True, "nmax_ops": [...], "rename_ops": [...],
        "summary": {...}}`` si todo OK.
        400 si falta algun param obligatorio o el body no es JSON valido.
        409 si el FB ya esta activo o terminal.
        500 si el FB no esta registrado en el engine o termino en error.
        504 si el FB excedio el timeout.
    """
    body = request.get_json(silent=True) or {}

    # Validacion de params (mismas reglas que el FB en ``on_start``).
    config_table_name = body.get("config_table_name")
    if not config_table_name:
        return jsonify({
            "ok": False,
            "error": "config_table_name (str) es obligatorio",
        }), 400
    for key in (
        "current_nmax_state",
        "desired_nmax_state",
        "current_device_state",
        "desired_device_state",
    ):
        if not isinstance(body.get(key), dict):
            return jsonify({
                "ok": False,
                "error": f"{key} (dict) es obligatorio",
            }), 400

    # ── Arrancar el FB ──
    fb = _get_fb("diff_constants")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'diff_constants' no registrado en el engine",
        }), 500

    import asyncio
    started = asyncio.run(fb.start(
        plc_name=plc_name,
        config_table_name=config_table_name,
        current_nmax_state=body["current_nmax_state"],
        desired_nmax_state=body["desired_nmax_state"],
        current_device_state=body["current_device_state"],
        desired_device_state=body["desired_device_state"],
    ))
    if not started:
        return jsonify({
            "ok": False,
            "error": "FB 'diff_constants' ya activo o terminal. "
                     "Haz /disconnect y reintenta.",
        }), 409

    # ── Esperar al resultado (poll bloqueante) ──
    poll_interval_s = 0.05  # 50ms
    elapsed = 0.0
    fb_step_timeout = getattr(fb, "STEP_TIMEOUT_S", 30.0)
    while not fb.is_terminal() and elapsed < fb_step_timeout:
        time.sleep(poll_interval_s)
        elapsed += poll_interval_s

    # ── Devolver el resultado ──
    if not fb.is_terminal():
        # Timeout: cancelar el FB para no dejarlo colgado.
        fb.cancel("timeout en /api/v1/plcs/<name>/diff-constants")
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

    return jsonify(fb.result or {"ok": True})


@bp.get("/status")
def get_diff_constants_status(plc_name: str):
    """Placeholder. Devuelve siempre 200 con ok=True.

    Pensado para futuras ampliaciones (progreso live via SSE,
    cancelacion explicita, etc.). Por ahora el FB se ejecuta
    de forma sincrona en el POST y no hay estado persistente
    que reportar entre llamadas.
    """
    return jsonify({"ok": True, "plc_name": plc_name})


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de DiffConstants).

    Llamado por el ``_build_all_routers`` central del area desde
    ``__init__.py``. Registra el blueprint de este modulo en la
    Flask app.
    """
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_diff_constants' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]
