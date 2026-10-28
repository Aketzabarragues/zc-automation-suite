"""Router Flask de los endpoints ``POST /api/v1/procesos/sync/{preview,commit}``.

Orquesta: encola el trabajo correspondiente en el OB1 (dispatcher con
cola) y devuelve el ``job_id``. Los helpers
(``areas/alimentacion/helpers/proc/``) tienen la logica pura; los FBs
(registrados en el engine con esos nombres) tienen la state machine +
tracker.

Endpoints:
  POST /api/v1/procesos/sync/preview
    Body JSON: ``{plc_name: str, proc_uid: int}``. Encola el FB
    ``proc_db_generar_preview`` y devuelve ``202`` con
    ``{"ok": true, "job_id": "<hex>"}``. El resultado del preview (shape
    legacy completa: ``{proc_uid, proc_codigo, precondiciones_ok,
    missing_blocks, db_param_name, db_alm_name, table_name, arrays,
    summary, nmax, warnings}``) llega por el evento SSE ``fb_state`` y
    por el slot ``preview_proc`` del AppCache que publica el FB al
    terminar.

  POST /api/v1/procesos/sync/commit
    Body JSON: ``{plc_name: str, proc_uid: int}``. Encola el FB
    ``proc_db_sincronizar`` y devuelve ``202`` con
    ``{"ok": true, "job_id": "<hex>"}``. El resultado del commit (shape
    legacy completa: ``{proc_uid, plc_name, success, applied,
    operations_executed, details, warnings}``) llega por el evento SSE
    ``fb_state`` y por los slots ``last_proc_commit_summary`` /
    ``preview_proc`` del AppCache que publica el FB al terminar.

Notas de timing:
  - Operacion PESADA: preview exporta 2 DBs + parsea N_MAX;
    commit aplica 2 sub-comandos TIA en 1 sola transaccion.
  - TIA V21 puede tardar 1-3 min en PLCs grandes.
  - STEP_TIMEOUT_S del FB preview: 180s. del FB commit: 300s.
  - El request NO bloquea: el router responde 202 de inmediato y el
    trabajo lo ejecuta el hilo del OB1.
  - Cliente API (frontend): debe usar el bucket
    MEDIUM_TIMEOUT_MS (300s, 5 min) en api.js para no abortar
    antes de tiempo.
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
    "area_alimentacion_proc_sync",
    __name__,
    url_prefix="/api/v1/procesos/sync",
)


def _get_engine():
    return current_app.config["ENGINE"]


def _validate_body(body: dict) -> tuple[str | None, int | None, str | None]:
    """Valida ``plc_name`` (str) + ``proc_uid`` (int) del body.

    Returns:
        Tupla (plc_name, proc_uid, error_msg). Si error_msg != None,
        el body es invalido y devuelve 400 con ese mensaje.
    """
    plc_name = body.get("plc_name")
    if not plc_name:
        return None, None, "plc_name (str) es obligatorio en el body"
    proc_uid = body.get("proc_uid")
    if proc_uid is None or not isinstance(proc_uid, int):
        return None, None, "proc_uid (int) es obligatorio en el body"
    return plc_name, proc_uid, None


@bp.post("/preview")
def post_proc_sync_preview():
    """Encola el FB ``proc_db_generar_preview`` para el proceso del body.

    Body JSON: ``{plc_name: str, proc_uid: int}``.

    El request NO bloquea: encola el trabajo en el OB1 y devuelve
    ``202`` con el ``job_id``. El FB se ejecuta en el hilo del OB1 y
    su resultado llega al HMI por el evento SSE ``fb_state`` (con el
    mismo ``job_id``) y por el slot ``preview_proc`` del AppCache que
    el FB publica al terminar.

    Returns:
        202 con ``{"ok": true, "job_id": "<hex>"}``.
        400 si falta ``plc_name`` o ``proc_uid`` en el body.
        409 si el FB ya tiene un trabajo en curso.
        500 si el FB no esta registrado en el engine.
    """
    body = request.get_json(silent=True) or {}
    plc_name, proc_uid, err = _validate_body(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    engine = _get_engine()
    if engine is None:
        return jsonify({
            "ok": False,
            "error": "Engine no disponible",
        }), 500

    if engine.get_fb("proc_db_generar_preview") is None:
        return jsonify({
            "ok": False,
            "error": "FB 'proc_db_generar_preview' no registrado en el engine",
        }), 500

    # Plan living TRAZABILIDAD_LOGGING §5: 1 web explicito al iniciar.
    logger.web(f"Generando prevision de proceso '{proc_uid}' en '{plc_name}'...")
    try:
        job_id = engine.submit(
            "proc_db_generar_preview", plc_name=plc_name, proc_uid=proc_uid,
        )
    except FBBusyError as exc:
        return jsonify({
            "ok": False,
            "error": (
                f"FB 'proc_db_generar_preview' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        logger.exception("dispatch: no se pudo encolar el preview de proceso")
        return jsonify({
            "ok": False,
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    return jsonify({"ok": True, "job_id": job_id}), 202


@bp.post("/commit")
def post_proc_sync_commit():
    """Encola el FB ``proc_db_sincronizar`` para el proceso del body.

    Body JSON: ``{plc_name: str, proc_uid: int}``.

    El request NO bloquea: encola el trabajo en el OB1 y devuelve
    ``202`` con el ``job_id``. El FB se ejecuta en el hilo del OB1 y
    su resultado llega al HMI por el evento SSE ``fb_state`` (con el
    mismo ``job_id``) y por los slots ``last_proc_commit_summary`` y
    ``preview_proc`` del AppCache que el FB publica al terminar.

    Returns:
        202 con ``{"ok": true, "job_id": "<hex>"}``.
        400 si falta ``plc_name`` o ``proc_uid`` en el body.
        409 si el FB ya tiene un trabajo en curso.
        500 si el FB no esta registrado en el engine.
    """
    body = request.get_json(silent=True) or {}
    plc_name, proc_uid, err = _validate_body(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    engine = _get_engine()
    if engine is None:
        return jsonify({
            "ok": False,
            "error": "Engine no disponible",
        }), 500

    if engine.get_fb("proc_db_sincronizar") is None:
        return jsonify({
            "ok": False,
            "error": "FB 'proc_db_sincronizar' no registrado en el engine",
        }), 500

    # Plan living TRAZABILIDAD_LOGGING §5: 1 web explicito al iniciar.
    logger.web(f"Sincronizando comentarios de proceso '{proc_uid}' en '{plc_name}'...")
    try:
        job_id = engine.submit(
            "proc_db_sincronizar", plc_name=plc_name, proc_uid=proc_uid,
        )
    except FBBusyError as exc:
        return jsonify({
            "ok": False,
            "error": (
                f"FB 'proc_db_sincronizar' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        logger.exception("dispatch: no se pudo encolar el sync de proceso")
        return jsonify({
            "ok": False,
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    return jsonify({"ok": True, "job_id": job_id}), 202


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Procesos Sync)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_proc_sync' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]
