"""Router Flask del endpoint ``POST /api/v1/entidades/sincronizar``.

El helper vive en ``areas/alimentacion/helpers/entidades/``.
El FB ``FunctionEntidadesSincronizar`` tiene la state machine de 11
etapas + tracker. Este router solo orquesta: encola el trabajo en el
OB1 y devuelve el ``job_id``; el resultado llega al HMI por push (SSE).

Endpoint:
  POST /api/v1/entidades/sincronizar
    Body JSON: ``{plc_name: str}``. ``plc_name`` obligatorio.

    Encola el FB ``entidades_sincronizar`` y devuelve ``202`` con
    ``{"ok": true, "job_id": "<hex>"}``. El resultado del sync (shape
    legacy completa: ``{success, message, operations, n_max_updates,
    post_sync_preview, compile_ok, compile_error, comments_sync}``)
    llega por el evento SSE ``fb_state`` y por los slots del AppCache
    que publica el FB al terminar.

Notas de timing:
  - Operacion PESADA: 11 etapas transaccionales (Tx A NMAX online,
    Tx B constantes, Tx C comentarios) + compile + post preview.
  - TIA V21 puede tardar 1-10 minutos para un PLC con el array ENT[]
    redimensionado.
  - STEP_TIMEOUT_S del FB: 600s (10 min).
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
    "area_alimentacion_entidades_sync",
    __name__,
    url_prefix="/api/v1/entidades",
)


def _get_engine():
    return current_app.config["ENGINE"]


@bp.post("/sincronizar")
def post_entidades_sincronizar():
    """Encola el FB ``entidades_sincronizar`` para el ``plc_name`` del body.

    El request NO bloquea: encola el trabajo en el OB1 y devuelve
    ``202`` con el ``job_id``. El FB se ejecuta en el hilo del OB1 y
    su resultado llega al HMI por el evento SSE ``fb_state`` (con el
    mismo ``job_id``) y por los slots del AppCache que el FB publica
    al terminar.

    Importante: el FB NO hace ``save_project`` (politica del repo).
    El proyecto queda dirty en memoria de TIA Portal; el operario
    pulsa Save manual tras ver el resultado. La SPA muestra el hint
    en el message del result.

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

    if engine.get_fb("entidades_sincronizar") is None:
        return jsonify({
            "ok": False,
            "error": "FB 'entidades_sincronizar' no registrado en el engine",
        }), 500

    logger.web(f"Sincronizando entidades en '{plc_name}'...")
    try:
        job_id = engine.submit("entidades_sincronizar", plc_name=plc_name)
    except FBBusyError as exc:
        return jsonify({
            "ok": False,
            "error": (
                f"FB 'entidades_sincronizar' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        logger.exception("dispatch: no se pudo encolar el sync de entidades")
        return jsonify({
            "ok": False,
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    return jsonify({"ok": True, "job_id": job_id}), 202


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Sync entidades)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_entidades_sync' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]
