"""Router Flask del endpoint ``POST /api/v1/sync/preview``.

Orquesta: encola el FB ``disp_generar_preview`` en el OB1 y devuelve su
``job_id``. El helper vive en
``areas/alimentacion/helpers/disp/disp_generate_preview.py``; el FB
tiene la state machine + tracker. Este router solo orquesta: encola
el trabajo y devuelve el ``job_id``; el resultado llega al HMI por push
(SSE).

Endpoint:
  POST /api/v1/sync/preview
    Body JSON con ``plc_name`` (obligatorio). Encola el FB
    ``disp_generar_preview`` y devuelve ``202``
    con ``{"ok": true, "job_id": "<hex>"}``. El resultado del preview
    (shape legacy completa: ``{agregados, eliminados, renombrados,
    todos, nmax, summary}``) llega por el evento SSE ``fb_state`` y por
    el slot ``preview_disp`` del AppCache que publica el FB al
    terminar.

  GET /api/v1/sync/preview/status
    Placeholder. Siempre devuelve 200 con ok=True.

Notas de timing:
  - Operacion PESADA: export de las 7 tablas del PLC (2 dispatchs) +
    diff de dispositivos + diff de N_MAX.
  - STEP_TIMEOUT_S del FB: 60s.
  - El request NO bloquea: el router responde 202 de inmediato y el
    trabajo lo ejecuta el hilo del OB1.
"""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from core.composition.plc_engine import FBBusyError
from core.infrastructure.log.log_web_bridge import install_web_level

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()

bp = Blueprint(
    "area_alimentacion_disp_preview",
    __name__,
    url_prefix="/api/v1/sync/preview",
)


def _get_engine():
    return current_app.config["ENGINE"]


@bp.post("")
def post_disp_preview():
    """Encola el FB ``disp_generar_preview`` para el ``plc_name`` del body.

    El ``plc_name`` viene en el body JSON (``{plc_name: str}``),
    no en el path. La SPA asi lo manda porque el path se reserva para
    la jerarquia de URLs (procesos usa ``/api/v1/procesos/sync/preview``).

    El request NO bloquea: encola el trabajo en el OB1 y devuelve
    ``202`` con el ``job_id``. El FB se ejecuta en el hilo del OB1 y
    su resultado llega al HMI por el evento SSE ``fb_state`` (con el
    mismo ``job_id``) y por el slot ``preview_disp`` del AppCache que
    el FB publica al terminar.

    Returns:
        202 con ``{"ok": true, "job_id": "<hex>"}``.
        400 si falta ``plc_name`` en el body.
        409 si el FB ya tiene un trabajo en curso.
        500 si el FB no esta registrado en el engine.
    """
    body = request.get_json(silent=True) or {}
    plc_name = body.get("plc_name")
    if not plc_name:
        return jsonify({
            "ok": False,
            "error": "plc_name (str) es obligatorio en el body",
        }), 400

    engine = _get_engine()
    if engine is None:
        return jsonify({
            "ok": False,
            "error": "Engine no disponible",
        }), 500

    if engine.get_fb("disp_generar_preview") is None:
        return jsonify({
            "ok": False,
            "error": "FB 'disp_generar_preview' no registrado en el engine",
        }), 500

    # 1 web al iniciar: el operario ve que arranca el preview.
    logger.web(f"Generando preview de dispositivos en '{plc_name}'...")
    try:
        job_id = engine.submit("disp_generar_preview", plc_name=plc_name)
    except FBBusyError as exc:
        return jsonify({
            "ok": False,
            "error": (
                f"FB 'disp_generar_preview' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        logger.exception("dispatch: no se pudo encolar el preview de dispositivos")
        return jsonify({
            "ok": False,
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    return jsonify({"ok": True, "job_id": job_id}), 202


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
