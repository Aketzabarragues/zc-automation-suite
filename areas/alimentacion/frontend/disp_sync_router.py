"""Router Flask del endpoint ``POST /api/v1/sync/commit``.

El helper vive en ``areas/alimentacion/helpers/disp/disp_Sincronizar.py``.
El FB ``FunctionDispSincronizar`` tiene la state machine
+ tracker. Este router solo orquesta: encola el trabajo en el OB1 y
devuelve el ``job_id``; el resultado llega al HMI por push (SSE).

Endpoint:
  POST /api/v1/sync/commit
    Body JSON con ``plc_name`` (obligatorio). Encola el FB
    ``disp_sincronizar`` y devuelve ``202`` con ``{"ok": true,
    "job_id": "<hex>"}``. El resultado del sync (shape legacy completa:
    ``{success, message, operations, n_max_updates, post_sync_preview,
    compile_ok, compile_error, comments_sync}``) llega por el evento SSE
    ``fb_state`` y por el slot del AppCache que publica el FB al
    terminar.

  GET /api/v1/sync/commit/status
    Placeholder. Siempre devuelve 200 con ok=True.

Notas de timing:
  - Operacion PESADA: export bulk + 2 tx TIA (Tx A: N_MAX renames,
    Tx B: devices offline) + compile_blocks (6 DBs) + apply
    comentarios (6 dispatches) + post_preview.
  - TIA V21 puede tardar 1-10 minutos para un PLC con 200+ bloques
    y 6 DBs de dispositivos redimensionados.
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
    "area_alimentacion_disp_Sincronizar",
    __name__,
    url_prefix="/api/v1/sync/commit",
)


def _get_engine():
    return current_app.config["ENGINE"]


@bp.post("")
def post_disp_sync_commit():
    """Encola el FB ``disp_sincronizar`` para el ``plc_name`` del body.

    El ``plc_name`` viene en el body JSON (``{plc_name: str,
    prevision: dict}``), no en el path. La SPA asi lo manda porque
    el path se reserva para la jerarquia de URLs (procesos usa
    ``/api/v1/procesos/sync/commit``).

    El request NO bloquea: encola el trabajo en el OB1 y devuelve
    ``202`` con el ``job_id``. El FB se ejecuta en el hilo del OB1 y
    su resultado llega al HMI por el evento SSE ``fb_state`` (con el
    mismo ``job_id``) y por los slots del AppCache que el FB publica
    al terminar.

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

    if engine.get_fb("disp_sincronizar") is None:
        return jsonify({
            "ok": False,
            "error": "FB 'disp_sincronizar' no registrado en el engine",
        }), 500

    # 1 web al iniciar: el operario ve que arranca el sync.
    logger.web(f"Sincronizando dispositivos en '{plc_name}'...")
    try:
        job_id = engine.submit("disp_sincronizar", plc_name=plc_name)
    except FBBusyError as exc:
        return jsonify({
            "ok": False,
            "error": (
                f"FB 'disp_sincronizar' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        logger.exception("dispatch: no se pudo encolar el sync de dispositivos")
        return jsonify({
            "ok": False,
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    return jsonify({"ok": True, "job_id": job_id}), 202


@bp.get("/status")
def get_disp_sync_status():
    """Placeholder. Devuelve siempre 200 con ok=True."""
    return jsonify({"ok": True})


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de SyncCommit)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_disp_Sincronizar' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]
