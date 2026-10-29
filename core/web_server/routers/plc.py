"""Flask blueprint para PLC FBs.

Blueprint Flask de los Function Blocks de PLC. Endpoints:
  POST /api/v1/plc/fb/<name>/start       -> encola el trabajo del FB.
  POST /api/v1/plc/fb/<name>/disconnect -> desregistra FB del engine.
  GET  /api/v1/plc/fb/<name>/status     -> estado actual del FB.

Engine se lee de ``current_app.config['ENGINE']`` (inyectado por
create_app). FBs se registran en el composition root.

Los POST no bloquean: encolan el trabajo en el OB1 con
``engine.submit()`` y devuelven 202 con el ``job_id``. El resultado
llega al HMI por el evento SSE ``fb_state``.

Los endpoints de cache de bloques del PLC
(GET /api/v1/plcs/<name>/blocks y POST /api/v1/plcs/<name>/blocks/refresh)
viven en el blueprint hermano ``plc_blocks`` de este mismo archivo.
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from core.composition.plc_engine import FBBusyError
from core.infrastructure.log.log_web_bridge import install_web_level

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()

bp = Blueprint("plc_fbs", __name__, url_prefix="/api/v1/plc/fb")


def _engine():
    return current_app.config["ENGINE"]


@bp.post("/<name>/start")
def start_fb(name: str):
    """Encola el FB registrado bajo ``name``.

    El request NO bloquea: el trabajo lo ejecuta el hilo del OB1 y el
    resultado llega al HMI por SSE (``fb_state``).

    Returns:
        - 202 + ``{"ok": True, "job_id": "<hex>"}`` si se encolo.
        - 404 si el FB no esta registrado en el engine.
        - 409 si el FB ya tiene un trabajo en curso.
        - 500 si no se pudo encolar.
    """
    engine = _engine()
    if engine.get_fb(name) is None:
        return jsonify({
            "error": f"FB '{name}' no registrado en el engine",
        }), 404

    body = request.get_json(silent=True) or {}
    params: dict[str, Any] = body.get("params") or {}

    try:
        job_id = engine.submit(name, **params)
    except FBBusyError as exc:
        return jsonify({
            "error": (
                f"FB '{name}' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    return jsonify({"ok": True, "job_id": job_id}), 202


@bp.post("/<name>/disconnect")
def disconnect_fb(name: str):
    """Desregistra el FB del engine. 204 si ok, 404 si no estaba."""
    engine = _engine()
    # Implementacion minimalista: pop del dict interno (engine no expone
    # unregister_fb publico).
    removed = engine._fbs.pop(name, None) is not None  # noqa: SLF001
    if not removed:
        return jsonify({
            "error": f"FB '{name}' no registrado en el engine",
        }), 404
    return "", 204


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


# ---------------------------------------------------------------------------
# Blueprint hermano: endpoints de cache de bloques del PLC.
#
# El shell SPA (``plcpanelview.js``) llama a
# ``loadAndApplyPlcBlocks`` con ``force=false`` (lee) o ``force=true``
# (refrescar) apuntando a ``/api/v1/plcs/<name>/blocks``. Este blueprint
# sirve esos endpoints delegando en el comando ``scan_blocks`` del
# worker TIA (``core.infrastructure.tia.tia_cmd_inspect._h_scan_blocks``).
#
# El backend OB1 no tiene cache servidor del PLC: cada llamada escanea
# TIA Portal directamente. La diferencia entre GET y POST es solo
# semantica para el operario (el boton ↻ del sidebar dispara la
# variante POST).
#
# Ninguno de los 2 devuelve el snapshot: el scan no bloquea, se encola
# en el OB1 y responde 202 con el job_id. El snapshot llega por SSE
# (``cache_changed``), que es como la SPA lo consume: ``
# loadAndApplyPlcBlocks`` dispara el refresh y no lee el body.
# ---------------------------------------------------------------------------

# El timeout del scan vive en el FB (``STEP_TIMEOUT_S``): el router no
# espera al resultado, solo encola el trabajo.


def _scan_plc_blocks(plc_name: str):
    """Helper comun: encola el FB ``scan_plc_blocks``.

    Devuelve ``(status_code, body)``.

    El scan NO bloquea: el trabajo lo ejecuta el hilo del OB1. El
    snapshot no viaja en el body porque la SPA no lo consume ahi: el
    FB lo escribe en ``AppCache.plc_blocks[<plc>]`` y el delta llega
    por SSE (``cache_changed``).

    Si el portal no esta attached, devuelve 503 + X-Error-Type
    (mismo contrato que el resto de endpoints del shell) para que el SPA
    distinga el caso y resetee el state PLC via ``store.loadAndApplyPlcBlocks``.
    """
    tia_client = current_app.config.get("TIA_CLIENT")
    if tia_client is None or tia_client.ts is None or tia_client.wrapper is None:
        # No hay portal attached.
        resp = jsonify({
            "ok": False,
            "error": "TIA Portal no conectado. Pulse Conectar primero.",
        })
        resp.headers["X-Error-Type"] = "TIAConnectionError"
        return 503, resp

    engine = current_app.config.get("ENGINE")
    if engine is None:
        resp = jsonify({
            "ok": False,
            "error": "engine no inicializado",
        })
        return 500, resp

    if engine.get_fb("scan_plc_blocks") is None:
        resp = jsonify({
            "ok": False,
            "error": "FB 'scan_plc_blocks' no registrado en el engine",
        })
        return 500, resp

    # force_refresh: leer del body si es POST, default False.
    body = request.get_json(silent=True) or {}
    force_refresh = bool(body.get("force_refresh", False))

    # 1 web al iniciar.
    logger.web(
        f"Leyendo cache del PLC '{plc_name}' "
        f"(force_refresh={force_refresh})..."
    )

    try:
        job_id = engine.submit(
            "scan_plc_blocks",
            plc_name=plc_name,
            force_refresh=force_refresh,
        )
    except FBBusyError as exc:
        # El FB esta corriendo. Devolvemos 409 para que el SPA sepa
        # reintentar cuando termine.
        return 409, jsonify({
            "ok": False,
            "error": (
                f"FB 'scan_plc_blocks' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        })
    except Exception as exc:  # noqa: BLE001
        resp = jsonify({
            "ok": False,
            "error": f"no se pudo encolar el trabajo: {exc}",
        })
        return 500, resp

    return 202, jsonify({"ok": True, "job_id": job_id})


# Blueprint separado del de FBs para que el ``url_prefix`` pueda ser
# ``/api/v1/plcs`` (sin el ``/fb``). Mismo modulo para no fragmentar
# el codigo de scan en dos archivos.
bp_blocks = Blueprint("plc_blocks", __name__, url_prefix="/api/v1/plcs")


@bp_blocks.get("/<plc_name>/blocks")
def get_plc_blocks(plc_name: str):
    """Encola el scan de bloques+tag_tables+UDTs del PLC.

    No bloquea: responde 202 con el ``job_id`` del trabajo. El snapshot
    llega por SSE (``cache_changed``) y la SPA mantiene el ultimo en
    ``store.plcBlocksCache``. Si el operario sospecha que los datos
    son stale (>5 min), pulsa el boton ↻ para forzar un re-scan via
    ``POST /<plc_name>/blocks/refresh``.
    """
    status, body = _scan_plc_blocks(plc_name)
    return body, status


@bp_blocks.post("/<plc_name>/blocks/refresh")
def post_plc_blocks_refresh(plc_name: str):
    """Fuerza un re-scan del PLC (mismo handler que GET, semantica manual).

    Equivalente a GET — la diferencia es solo el verbo HTTP para que
    el operario vea en el log de Flask "POST /refresh" cuando pulso
    el boton ↻. Si en el futuro anadimos cache servidor con TTL,
    este endpoint sera el que la invalide.
    """
    status, body = _scan_plc_blocks(plc_name)
    return body, status


__all__ = ["bp", "bp_blocks"]
