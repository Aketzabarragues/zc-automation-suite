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
from typing import Any

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


def _validate_body(body: dict) -> tuple[str | None, list[int] | None, str | None]:
    """Valida ``plc_name`` (str) + lista de ``proc_uids`` (list[int]).

    Back-compat: si el body trae ``proc_uid`` (singular, int legado), se
    convierte a ``[proc_uid]``. Si trae ``proc_uids`` (list[int]),
    se valida que sea lista de enteros positivos.

    Returns:
        Tupla (plc_name, proc_uids, error_msg). Si error_msg != None,
        el body es invalido y devuelve 400 con ese mensaje.
    """
    plc_name = body.get("plc_name")
    if not plc_name:
        return None, None, "plc_name (str) es obligatorio en el body"

    # Back-compat: ``proc_uid`` (singular) -> ``proc_uids`` (lista).
    proc_uids_raw = body.get("proc_uids")
    if proc_uids_raw is None:
        legacy_uid = body.get("proc_uid")
        if legacy_uid is None:
            return None, None, (
                "proc_uids (list[int]) o proc_uid (int, legacy) "
                "obligatorio en el body"
            )
        proc_uids_raw = [legacy_uid]

    if not isinstance(proc_uids_raw, list):
        return None, None, "proc_uids debe ser list[int]"
    proc_uids_clean: list[int] = []
    for u in proc_uids_raw:
        if not isinstance(u, int) or u <= 0:
            return None, None, f"proc_uids contiene valor invalido: {u!r}"
        proc_uids_clean.append(u)
    if not proc_uids_clean:
        return None, None, "proc_uids no puede estar vacio"

    return plc_name, proc_uids_clean, None


def _run_proc_fb(
    fb_name: str,
    plc_name: str,
    proc_uids: list[int],
) -> tuple[dict[str, Any] | None, dict[str, int | str] | None]:
    """Ejecuta el FB indicado para cada ``proc_uid`` y agrega resultados.

    Returns:
        ``(results_per_uid, errors_per_uid)``. Si algun FB falla, el
        resto se sigue ejecutando. ``results_per_uid`` mapea
        ``proc_uid -> result_dict`` (omitidos los fallidos).
    """
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    import asyncio
    for uid in proc_uids:
        fb = _get_fb(fb_name)
        if fb is None:
            errors[str(uid)] = f"FB '{fb_name}' no registrado en el engine"
            continue
        logger.web(
            f"{fb_name}: procesando proceso '{uid}' en '{plc_name}'..."
        )
        # Reusa el FB registrado: cada start() espera a que termine
        # el anterior. Si el FB ya esta activo, devuelve False.
        started = asyncio.run(fb.start(plc_name=plc_name, proc_uid=uid))
        if not started:
            errors[str(uid)] = (
                f"FB '{fb_name}' ya activo o terminal. "
                "Haz /disconnect y reintenta."
            )
            continue
        if not _poll_until_terminal(fb):
            errors[str(uid)] = "timeout sin terminar"
            continue
        if fb.nStep == fb.n_error:
            errors[str(uid)] = fb.error_msg or "FB termino en error"
            continue
        results[str(uid)] = fb.result or {"ok": True, "proc_uid": uid}
    return (results if results else None), errors


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
    """Dispara el FB ``proc_generar_preview`` para 1 o N ``proc_uids``.

    Body JSON: ``{plc_name: str, proc_uids: list[int]}``.
    Back-compat: ``proc_uid`` (singular, legacy) sigue funcionando.

    Returns:
        200 con ``{"ok": True, "results": {uid: result, ...},
        "errors": {uid: msg, ...}}``. ``errors`` solo aparece si
        algun FB fallo.
        400 si el body es invalido.
        500 si el FB no esta registrado.
        504 si timeout global.
    """
    body = request.get_json(silent=True) or {}
    plc_name, proc_uids, err = _validate_body(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    logger.web(
        f"Generando prevision de {len(proc_uids)} proceso(s) "
        f"({', '.join(str(u) for u in proc_uids)}) en '{plc_name}'..."
    )
    results, errors = _run_proc_fb(
        "proc_generar_preview", plc_name, proc_uids,
    )
    if not results:
        return jsonify({
            "ok": False,
            "error": "ningun proceso pudo generar preview",
            "errors": errors,
        }), 500

    logger.ok(
        f"Prevision generada para {len(results)}/{len(proc_uids)} "
        f"proceso(s) en '{plc_name}'"
        + (f" (errores: {len(errors)})" if errors else "")
    )
    return jsonify({
        "ok": True,
        "plc_name": plc_name,
        "results": results,
        **({"errors": errors} if errors else {}),
    })


@bp.post("/commit")
def post_proc_sync_commit():
    """Dispara el FB ``proc_sincronizar`` para 1 o N ``proc_uids``.

    Body JSON: ``{plc_name: str, proc_uids: list[int]}``.
    Back-compat: ``proc_uid`` (singular, legacy) sigue funcionando.

    Mismo shape de respuesta que ``/preview``.
    """
    body = request.get_json(silent=True) or {}
    plc_name, proc_uids, err = _validate_body(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    logger.web(
        f"Sincronizando comentarios de {len(proc_uids)} proceso(s) "
        f"({', '.join(str(u) for u in proc_uids)}) en '{plc_name}'..."
    )
    results, errors = _run_proc_fb(
        "proc_sincronizar", plc_name, proc_uids,
    )
    if not results:
        return jsonify({
            "ok": False,
            "error": "ningun proceso pudo sincronizarse",
            "errors": errors,
        }), 500

    logger.ok(
        f"Sincronizacion aplicada a {len(results)}/{len(proc_uids)} "
        f"proceso(s) en '{plc_name}'"
        + (f" (errores: {len(errors)})" if errors else "")
    )
    return jsonify({
        "ok": True,
        "plc_name": plc_name,
        "results": results,
        **({"errors": errors} if errors else {}),
    })


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Procesos Sync)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_proc_sync' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]
