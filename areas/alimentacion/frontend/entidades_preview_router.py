"""Router Flask del endpoint ``POST /api/v1/entidades/preview``.

El helper vive en ``areas/alimentacion/helpers/entidades/entidades_generate_preview.py``;
el FB ``FunctionEntidadesGenerarPreview`` (registrado en el engine como
``entidades_generar_preview``) tiene la state machine + tracker; este
router solo orquesta: arranca el FB y devuelve el ``result``.

Endpoint:
  POST /api/v1/entidades/preview
    Body JSON: ``{plc_name: str}``. ``plc_name`` obligatorio.
    Dispara el FB ``entidades_generar_preview`` y devuelve su
    ``result`` con shape completa: ``{precondiciones_ok, missing_blocks,
    db_name, db_array_name, tag_table, config_table, db_present,
    table_present, arrays, constants, nmax, summary, warnings}``.

  GET /api/v1/entidades/preview/status
    Placeholder. Siempre devuelve 200 con ``ok=True``.
"""
from __future__ import annotations

import logging
import time

from flask import Blueprint, current_app, jsonify, request

from core.infrastructure.log.log_web_bridge import install_web_level

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()

bp = Blueprint(
    "area_alimentacion_entidades_preview",
    __name__,
    url_prefix="/api/v1/entidades",
)


def _get_engine():
    return current_app.config["ENGINE"]


def _get_fb(name: str):
    return _get_engine().get_fb(name)


@bp.post("/preview")
def post_entidades_preview():
    """Dispara el FB ``entidades_generar_preview`` para el ``plc_name`` del body.

    Bloquea el hilo de Flask hasta que el FB termina (max ~60s,
    ``STEP_TIMEOUT_S`` del FB). Cuando el FB entra en estado terminal
    (``done`` o ``error``), devuelve el ``result``.

    Returns:
        200 con shape completa (precondiciones_ok, missing_blocks,
        db_name, db_array_name, tag_table, config_table, db_present,
        table_present, arrays, constants, nmax, summary, warnings).
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

    fb = _get_fb("entidades_generar_preview")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'entidades_generar_preview' no registrado en el engine",
        }), 500

    import asyncio
    # Plan living TRAZABILIDAD_LOGGING §5 (operacion 4): 1 web al iniciar.
    logger.web(f"Generando prevision de entidades de '{plc_name}'...")
    started = asyncio.run(fb.start(plc_name=plc_name))
    if not started:
        return jsonify({
            "ok": False,
            "error": "FB 'entidades_generar_preview' ya activo o terminal. "
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
        fb.cancel("timeout en /api/v1/entidades/preview")
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

    result = fb.result or {"ok": True, "plc_name": plc_name}
    # Publica el preview en AppCache (mismo slot preview_disp que
    # disp_preview_router: ambos bounded context operan sobre la misma
    # "prevision de disp").
    from core.runtime.area_preview_cache import area_set_preview_disp
    from core.runtime.app_cache import get_app_cache
    area_set_preview_disp(get_app_cache(), "alimentacion", result)
    # Plan living §5 (operacion 4): OK con resumen del diff.
    s = (result.get("summary") or {}) if isinstance(result, dict) else {}
    logger.ok(
        f"Prevision de entidades de '{plc_name}': "
        f"{s.get('constants_agregados', 0)} const adds, "
        f"{s.get('comments_added', 0)} comments adds, "
        f"{s.get('comments_updated', 0)} comments updates"
    )
    return jsonify(result)


@bp.get("/preview/status")
def get_entidades_preview_status():
    """Placeholder. Devuelve siempre 200 con ok=True."""
    return jsonify({"ok": True})


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Preview entidades)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_entidades_preview' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]