"""Flask blueprint para el editor de propiedades de bloques TIA.

Endpoints:
  POST /api/v1/blocks/edit/prepare -> arranca FB ``block_edit_prepare``.
  POST /api/v1/blocks/edit/apply    -> placeholder 501.
  GET  /api/v1/blocks/edit/<name>/status -> estado actual del FB.

Engine se lee de ``current_app.config['ENGINE']`` (inyectado por
create_app). FB ``block_edit_prepare`` registrado en
``core.composition.register_core_fbs.register()``.

Equivalente sync de los endpoints FastAPI del plan FASE 2 (v3.1).
"""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from core.infrastructure.log.log_web_bridge import install_web_level

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()

bp = Blueprint("blocks_edit", __name__, url_prefix="/api/v1/blocks/edit")


# Timeout backend para el ``block_edit_prepare``: el FB exporta N bloques
# a SD y parsea el ``.s7dcl``. En S7-1500 con 30+ bloques seleccionados
# el lote puede tardar 60-90s. 120s cubre holgadamente.
PREPARE_TIMEOUT_S = 120.0

# Timeout backend para el ``block_edit_apply``: el batch transaccional
# ejecuta ``update_block_property`` por bloque dentro de una sola
# transaccion atomica. ~5-15s por bloque; 600s cubre holgadamente N~50.
APPLY_TIMEOUT_S = 600.0

# Poll bloqueante del FB en el handler sync de Flask.
_POLL_INTERVAL_S = 0.05


def _engine():
    return current_app.config["ENGINE"]


@bp.post("/prepare")
def prepare_edit():
    """Arranca el FB ``block_edit_prepare`` y devuelve el resultado.

    Body JSON esperado::

        {
            "plc_name": "PLC_1",
            "selected_block_paths": ["2000_Dispositivos/DB2000_ED", ...]
        }

    Returns:
        - 200 + ``{"ok": True, "result": ..., "nStep": ...}`` si OK.
        - 400 si faltan ``plc_name`` o ``selected_block_paths``.
        - 409 si el FB ya esta corriendo (o terminal reciente).
        - 500 si el FB no esta registrado.
        - 504 si timeout.
        - 500 si el FB termina en error.
    """
    import asyncio
    import time

    engine = _engine()
    fb = engine.get_fb("block_edit_prepare")
    if fb is None:
        return jsonify({
            "error": "FB 'block_edit_prepare' no registrado en el engine",
        }), 500

    body = request.get_json(silent=True) or {}
    plc_name = body.get("plc_name")
    selected = body.get("selected_block_paths") or []
    if not plc_name or not selected:
        return jsonify({
            "error": "plc_name y selected_block_paths son obligatorios",
        }), 400

    logger.web(
        f"Preparando {len(selected)} bloques en PLC '{plc_name}' "
        f"(exporta SD + parsea SCL + cachea DTOs)..."
    )
    started = asyncio.run(fb.start(
        plc_name=plc_name,
        selected_block_paths=selected,
    ))
    if not started:
        return jsonify({
            "error": "FB 'block_edit_prepare' ya activo o terminal. "
                     "Haz /disconnect y reintenta.",
        }), 409

    # Poll bloqueante hasta que el FB entre en estado terminal.
    elapsed = 0.0
    while not fb.is_terminal() and elapsed < PREPARE_TIMEOUT_S:
        time.sleep(_POLL_INTERVAL_S)
        elapsed += _POLL_INTERVAL_S

    if not fb.is_terminal():
        try:
            asyncio.run(fb.cancel(f"timeout en /prepare ({PREPARE_TIMEOUT_S:.0f}s)"))
        except Exception:
            pass
        return jsonify({
            "error": f"timeout tras {PREPARE_TIMEOUT_S:.0f}s sin terminar",
        }), 504

    if fb.nStep == fb.n_error:
        return jsonify({
            "error": fb.error_msg or "FB termino en error",
        }), 500

    result = fb.result or {}
    n_blocks = result.get("n_blocks", 0)
    n_with_title = result.get("n_with_title", 0)
    n_with_comment = result.get("n_with_comment", 0)
    logger.ok(
        f"Bloques preparados en PLC '{plc_name}': {n_blocks} bloques "
        f"(con title: {n_with_title}, con comment: {n_with_comment})"
    )
    return jsonify({
        "ok": True,
        "result": fb.result,
        "nStep": fb.nStep,
    })


@bp.post("/apply")
def apply_edit():
    """Aplica los cambios de Name/Number via FB ``block_edit_apply``.

    Body JSON esperado::

        {
            "plc_name": str,
            "edits": {"<path>": {"name"?: str, "number"?: int}, ...}
        }

    ``<path>`` es la clave de fila que ``POST /prepare`` devolvio (la
    jerarquia de grupos mas el nombre del bloque, separados por ``"/"``).

    Returns:
        - 200 + ``{"ok": True, "result": ..., "nStep": ...}`` si OK.
        - 400 si faltan ``plc_name`` o ``edits``.
        - 400 si ``start()`` raise ``ValueError`` (whitelist de keys).
        - 409 si el FB ya esta corriendo (o terminal reciente).
        - 500 si el FB no esta registrado o ``start`` raise inesperado.
        - 504 si timeout.
        - 500 si el FB termina en error.
    """
    import asyncio
    import time

    engine = _engine()
    fb = engine.get_fb("block_edit_apply")
    if fb is None:
        return jsonify({
            "error": "FB 'block_edit_apply' no registrado en el engine",
        }), 500

    body = request.get_json(silent=True) or {}
    plc_name = body.get("plc_name")
    edits = body.get("edits") or {}
    if not plc_name or not edits:
        return jsonify({
            "error": "plc_name y edits son obligatorios",
        }), 400

    logger.web(
        f"Aplicando {len(edits)} ediciones en PLC '{plc_name}' "
        f"(transaccion atomica contra TIA Portal)..."
    )
    try:
        started = asyncio.run(fb.start(plc_name=plc_name, edits=edits))
    except ValueError as exc:
        return jsonify({"error": f"args invalidos: {exc}"}), 400
    except Exception as exc:
        return jsonify({
            "error": f"start fallo: {type(exc).__name__}: {exc}",
        }), 500
    if not started:
        return jsonify({
            "error": "FB 'block_edit_apply' ya activo o terminal. "
                     "Haz /disconnect y reintenta.",
        }), 409

    # Poll bloqueante hasta que el FB entre en estado terminal.
    elapsed = 0.0
    while not fb.is_terminal() and elapsed < APPLY_TIMEOUT_S:
        time.sleep(_POLL_INTERVAL_S)
        elapsed += _POLL_INTERVAL_S

    if not fb.is_terminal():
        try:
            asyncio.run(fb.cancel(f"timeout en /apply ({APPLY_TIMEOUT_S:.0f}s)"))
        except Exception:
            pass
        return jsonify({
            "error": f"timeout tras {APPLY_TIMEOUT_S:.0f}s sin terminar",
        }), 504

    if fb.nStep == fb.n_error:
        return jsonify({
            "error": fb.error_msg or "FB termino en error",
        }), 500

    result = fb.result or {}
    n_ops = result.get("n_ops", 0)
    operations_executed = result.get("operations_executed", 0)
    no_op = result.get("no_op", False)
    if no_op:
        logger.ok(
            f"Aplicacion sin cambios en PLC '{plc_name}': "
            f"cache == edits (0 ops ejecutadas)"
        )
    else:
        logger.ok(
            f"Aplicacion OK en PLC '{plc_name}': "
            f"{operations_executed}/{n_ops} ops ejecutadas"
        )
    return jsonify({
        "ok": True,
        "result": fb.result,
        "nStep": fb.nStep,
    })


@bp.get("/<plc_name>/prepared")
def get_prepared_blocks(plc_name: str):
    """Devuelve el cache de bloques preparados para ``plc_name``.

    Lee de ``app_cache.block_edit_prepared[plc_name]`` (slot que el
    FB ``block_edit_prepare`` rellena con ``DataBloquePLC`` keyed
    por path con separador ``/``). Cada bloque expone los 10 campos
    del DTO via ``DataBloquePLC.to_dict()``.

    La SPA usa este endpoint justo despues de ``POST /prepare``
    para pintar la tabla con los 10 campos y permitir editar
    inline Name/Number. Devuelve ``ok: True`` aunque no haya
    cache todavia (caso ``prepared: {}``).
    """
    app_cache = current_app.config.get("APP_CACHE")
    if app_cache is None:
        return jsonify({
            "ok": False,
            "error": "app_cache no inicializado",
        }), 503
    raw = app_cache.get_block_edit_prepared(plc_name)
    serialized = {}
    for path, dto in raw.items():
        try:
            serialized[path] = dto.to_dict()
        except AttributeError:
            serialized[path] = {
                "nombre": dto.nombre,
                "numero": dto.numero,
                "tipo": dto.tipo,
                "ruta": dto.ruta,
                "title": dto.title,
                "comment": dto.comment,
                "author": dto.author,
                "version": dto.version,
                "programming_language": dto.programming_language,
                "memory_layout": dto.memory_layout,
            }
    return jsonify({
        "ok": True,
        "prepared": serialized,
        "plc_name": plc_name,
    })


@bp.get("/<name>/status")
def get_fb_status(name: str):
    """Estado actual del FB (nStep, is_terminal, error_msg, result)."""
    engine = _engine()
    fb = engine.get_fb(name)
    if fb is None:
        return jsonify({
            "error": f"FB '{name}' no registrado en el engine",
        }), 404
    return jsonify({
        "name": name,
        "nStep": fb.nStep,
        "is_terminal": fb.is_terminal(),
        "error_msg": fb.error_msg,
        "result": fb.result,
    })


__all__ = ["bp"]
