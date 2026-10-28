"""Router Flask del endpoint ``POST /api/v1/entidades/preview``.

El helper vive en ``areas/alimentacion/helpers/entidades/entidades_generate_preview.py``;
el FB ``FunctionEntidadesGenerarPreview`` (registrado en el engine como
``entidades_generar_preview``) tiene la state machine + tracker; este
router solo orquesta: encola el trabajo en el OB1 y devuelve el
``job_id``; el resultado llega al HMI por push (SSE).

Endpoint:
  POST /api/v1/entidades/preview
    Body JSON: ``{plc_name: str}``. ``plc_name`` obligatorio.
    Encola el FB ``entidades_generar_preview`` y devuelve ``202`` con
    ``{"ok": true, "job_id": "<hex>"}``. El resultado del preview (shape
    completa: ``{precondiciones_ok, missing_blocks, db_name,
    db_array_name, tag_table, config_table, db_present, table_present,
    arrays, constants, nmax, summary, warnings}``) llega por el evento
    SSE ``fb_state`` y por el slot ``preview_disp`` del AppCache que
    publica el FB al terminar.

  GET /api/v1/entidades/preview/status
    Placeholder. Siempre devuelve 200 con ``ok=True``.

Notas de timing:
  - Operacion media: export de 2 tablas + 1 DB (entidades) + calculo
    de los diffs (N_MAX_ENTIDAD, constantes, comentarios).
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
    "area_alimentacion_entidades_preview",
    __name__,
    url_prefix="/api/v1/entidades",
)


def _get_engine():
    return current_app.config["ENGINE"]


@bp.post("/preview")
def post_entidades_preview():
    """Encola el FB ``entidades_generar_preview`` para el ``plc_name`` del body.

    El ``plc_name`` viene en el body JSON (``{plc_name: str}``).

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

    if engine.get_fb("entidades_generar_preview") is None:
        return jsonify({
            "ok": False,
            "error": "FB 'entidades_generar_preview' no registrado en el engine",
        }), 500

    logger.web(f"Generando preview de entidades en '{plc_name}'...")
    try:
        job_id = engine.submit("entidades_generar_preview", plc_name=plc_name)
    except FBBusyError as exc:
        return jsonify({
            "ok": False,
            "error": (
                f"FB 'entidades_generar_preview' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        logger.exception("dispatch: no se pudo encolar el preview de entidades")
        return jsonify({
            "ok": False,
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    return jsonify({"ok": True, "job_id": job_id}), 202


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
