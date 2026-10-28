"""Flask blueprint para el editor de propiedades de bloques TIA.

Endpoints:
  POST /api/v1/blocks/edit/prepare -> encola FB ``block_edit_prepare``.
  POST /api/v1/blocks/edit/apply    -> encola FB ``block_edit_apply``.
  GET  /api/v1/blocks/edit/<plc_name>/prepared -> cache de preparados.
  GET  /api/v1/blocks/edit/<name>/status -> estado actual del FB.

Engine se lee de ``current_app.config['ENGINE']`` (inyectado por
create_app). FB ``block_edit_prepare`` registrado en
``core.composition.register_core_fbs.register()``.

Los 2 POST no bloquean: encolan el trabajo en el OB1 y devuelven
``202`` con el ``job_id``. El resultado llega al HMI por el evento SSE
``fb_state`` y por los slots del AppCache que publica el FB al
terminar (``block_edit_prepared`` para el prepare).
"""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from core.composition.plc_engine import FBBusyError
from core.infrastructure.log.log_web_bridge import install_web_level

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()

bp = Blueprint("blocks_edit", __name__, url_prefix="/api/v1/blocks/edit")


# El timeout de cada trabajo vive en el FB (``STEP_TIMEOUT_S``): el
# router ya no espera al resultado, solo encola el trabajo.


def _engine():
    return current_app.config["ENGINE"]


@bp.post("/prepare")
def prepare_edit():
    """Encola el FB ``block_edit_prepare``.

    Body JSON esperado::

        {
            "plc_name": "PLC_1",
            "selected_block_paths": ["2000_Dispositivos/DB2000_ED", ...]
        }

    El request NO bloquea: el trabajo lo ejecuta el hilo del OB1 y el
    resultado llega al HMI por SSE (``fb_state``) y por el slot
    ``block_edit_prepared`` del AppCache, que es el que lee
    ``GET /<plc_name>/prepared``.

    Returns:
        - 202 + ``{"ok": True, "job_id": "<hex>"}`` si se encolo.
        - 400 si faltan ``plc_name`` o ``selected_block_paths``.
        - 409 si el FB ya tiene un trabajo en curso.
        - 500 si el FB no esta registrado o no se pudo encolar.
    """
    engine = _engine()
    if engine.get_fb("block_edit_prepare") is None:
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
    try:
        job_id = engine.submit(
            "block_edit_prepare",
            plc_name=plc_name,
            selected_block_paths=selected,
        )
    except FBBusyError as exc:
        return jsonify({
            "error": (
                f"FB 'block_edit_prepare' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    return jsonify({"ok": True, "job_id": job_id}), 202


@bp.post("/apply")
def apply_edit():
    """Encola el FB ``block_edit_apply``.

    Body JSON esperado::

        {
            "plc_name": str,
            "edits": {"<path>": {"name"?: str, "number"?: int}, ...}
        }

    ``<path>`` es la clave de fila que ``POST /prepare`` devolvio (la
    jerarquia de grupos mas el nombre del bloque, separados por ``"/"``).

    El request NO bloquea: el trabajo lo ejecuta el hilo del OB1 y el
    resultado llega al HMI por SSE (``fb_state``).

    Returns:
        - 202 + ``{"ok": True, "job_id": "<hex>"}`` si se encolo.
        - 400 si faltan ``plc_name`` o ``edits``.
        - 409 si el FB ya tiene un trabajo en curso.
        - 500 si el FB no esta registrado o no se pudo encolar.
    """
    engine = _engine()
    if engine.get_fb("block_edit_apply") is None:
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
        job_id = engine.submit(
            "block_edit_apply", plc_name=plc_name, edits=edits,
        )
    except FBBusyError as exc:
        return jsonify({
            "error": (
                f"FB 'block_edit_apply' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except ValueError as exc:
        return jsonify({"error": f"args invalidos: {exc}"}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    # El resumen de la aplicacion (ops ejecutadas, no-op) lo emite el
    # FB al terminar: el router ya respondio cuando aun no habia
    # ningun resultado.
    return jsonify({"ok": True, "job_id": job_id}), 202


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
