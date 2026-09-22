"""Router Flask de los endpoints ``POST /api/v1/procesos/sync/{preview,commit}``.

Migrado del use case legacy ``proc_sync_comentarios``. Los helpers viven en
``areas/alimentacion/helpers/proc/``; los FBs
(registrados en el engine con esos nombres) tienen la state machine
+ tracker; este router solo orquesta: arranca el FB y devuelve el
``result``.

Endpoints:
  POST /api/v1/procesos/sync/preview
    Body JSON: ``{plc_name: str, proc_uid: int}``. Dispara el FB
    ``proc_generar_preview`` y devuelve su ``result`` con shape
    legacy completa: ``{proc_uid, proc_codigo, precondiciones_ok,
    missing_blocks, db_param_name, db_alm_name, table_name,
    arrays, summary, nmax, warnings}``.

  POST /api/v1/procesos/sync/commit
    Body JSON: ``{plc_name: str, proc_uid: int}``. Dispara el FB
    ``proc_sincronizar`` y devuelve su ``result`` con shape
    legacy completa: ``{proc_uid, plc_name, success, applied,
    operations_executed, details, warnings}``.

Notas de timing:
  - Operacion PESADA: preview exporta 2 DBs + parsea N_MAX;
    commit aplica 2 sub-comandos TIA en 1 sola transaccion.
  - TIA V21 puede tardar 1-3 min en PLCs grandes.
  - STEP_TIMEOUT_S del FB preview: 180s. del FB commit: 300s.
  - Cliente API (frontend): debe usar el bucket
    MEDIUM_TIMEOUT_MS (300s, 5 min) en api.js para no abortar
    antes de tiempo.
"""
from __future__ import annotations

import logging
import time

from flask import Blueprint, current_app, jsonify, request

from core.infrastructure.log_web_bridge import install_web_level

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


def _get_fb(name: str):
    return _get_engine().get_fb(name)


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


def _poll_until_terminal(fb: Any, poll_interval_s: float = 0.1) -> bool:
    """Poll bloqueante hasta que el FB entre en estado terminal.

    Returns:
        True si termino OK, False si timeout.
    """
    elapsed = 0.0
    fb_step_timeout = getattr(fb, "STEP_TIMEOUT_S", 600.0)
    while not fb.is_terminal() and elapsed < fb_step_timeout:
        time.sleep(poll_interval_s)
        elapsed += poll_interval_s
    if not fb.is_terminal():
        fb.cancel("timeout en /api/v1/procesos/sync")
        return False
    return True


@bp.post("/preview")
def post_proc_sync_preview():
    """Dispara el FB ``proc_generar_preview`` y devuelve su ``result``.

    Body JSON: ``{plc_name: str, proc_uid: int}``.

    Returns:
        200 con shape legacy completo.
        400 si falta ``plc_name`` o ``proc_uid`` en el body.
        409 si el FB ya esta activo o terminal.
        500 si el FB no esta registrado o termino en error.
        504 si timeout.
    """
    body = request.get_json(silent=True) or {}
    plc_name, proc_uid, err = _validate_body(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    fb = _get_fb("proc_db_generar_preview")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'proc_generar_preview' no registrado en el engine",
        }), 500

    import asyncio
    # Plan living TRAZABILIDAD_LOGGING §5: 1 web explicito al iniciar.
    logger.web(f"Generando prevision de proceso '{proc_uid}' en '{plc_name}'...")
    started = asyncio.run(fb.start(plc_name=plc_name, proc_uid=proc_uid))
    if not started:
        return jsonify({
            "ok": False,
            "error": "FB 'proc_generar_preview' ya activo o terminal. "
                     "Haz /disconnect y reintenta.",
        }), 409

    if not _poll_until_terminal(fb):
        return jsonify({
            "ok": False,
            "error": f"timeout tras {fb.STEP_TIMEOUT_S:.1f}s sin terminar",
        }), 504

    if fb.nStep == fb.n_error:
        return jsonify({
            "ok": False,
            "error": fb.error_msg or "FB termino en error",
            "nStep": fb.nStep,
        }), 500

    result = fb.result or {"ok": True, "plc_name": plc_name, "proc_uid": proc_uid}
    # Plan living §5: OK con resumen del preview.
    s = (result.get("summary") or {}) if isinstance(result, dict) else {}
    nmax = (
        (result.get("nmax") or {}).get("summary") or {}
        if isinstance(result, dict) else {}
    )
    logger.ok(
        f"Prevision de proceso '{proc_uid}' en '{plc_name}': "
        f"{s.get('agregados', 0)} adds, {s.get('renombrados', 0)} renames, "
        f"{s.get('eliminados', 0)} removes, "
        f"{nmax.get('actualizar', 0)} N_MAX"
    )
    return jsonify(result)


@bp.post("/commit")
def post_proc_sync_commit():
    """Dispara el FB ``proc_sincronizar`` y devuelve su ``result``.

    Body JSON: ``{plc_name: str, proc_uid: int}``.

    Returns:
        200 con shape legacy completo (success, applied,
        operations_executed, details, warnings).
        400 si falta ``plc_name`` o ``proc_uid`` en el body.
        409 si el FB ya esta activo o terminal.
        500 si el FB no esta registrado o termino en error.
        504 si timeout.
    """
    body = request.get_json(silent=True) or {}
    plc_name, proc_uid, err = _validate_body(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    fb = _get_fb("proc_sincronizar")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'proc_sincronizar' no registrado en el engine",
        }), 500

    import asyncio
    # Plan living TRAZABILIDAD_LOGGING §5: 1 web explicito al iniciar.
    logger.web(f"Sincronizando comentarios de proceso '{proc_uid}' en '{plc_name}'...")
    started = asyncio.run(fb.start(plc_name=plc_name, proc_uid=proc_uid))
    if not started:
        return jsonify({
            "ok": False,
            "error": "FB 'proc_sincronizar' ya activo o terminal. "
                     "Haz /disconnect y reintenta.",
        }), 409

    if not _poll_until_terminal(fb):
        return jsonify({
            "ok": False,
            "error": f"timeout tras {fb.STEP_TIMEOUT_S:.1f}s sin terminar",
        }), 504

    if fb.nStep == fb.n_error:
        return jsonify({
            "ok": False,
            "error": fb.error_msg or "FB termino en error",
            "nStep": fb.nStep,
        }), 500

    result = fb.result or {"ok": True, "plc_name": plc_name, "proc_uid": proc_uid}
    # Plan living §5: OK con resumen del sync.
    ops = result.get("operations_executed", 0) if isinstance(result, dict) else 0
    logger.ok(
        f"Sincronizacion de proceso '{proc_uid}' en '{plc_name}': "
        f"{ops} ops aplicadas"
    )
    return jsonify(result)


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Procesos Sync)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_proc_sync' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]
