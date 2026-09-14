"""Flask blueprint para PLC FBs.

Equivalente sync de ``plc.py`` (FastAPI). Endpoints:
  POST /api/v1/plc/fb/<name>/start       -> arranca FB.
  POST /api/v1/plc/fb/<name>/disconnect -> desregistra FB del engine.
  GET  /api/v1/plc/fb/<name>/status     -> estado actual del FB.

Engine se lee de ``current_app.config['ENGINE']`` (inyectado por
create_app). FBs se registran en ``composition root`` (4.5.1+).

Los endpoints de cache de bloques del PLC
(GET /api/v1/plcs/<name>/blocks y POST /api/v1/plcs/<name>/blocks/refresh)
viven en el blueprint hermano ``plc_blocks`` de este mismo archivo.
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("plc_fbs", __name__, url_prefix="/api/v1/plc/fb")


def _engine():
    return current_app.config["ENGINE"]


@bp.post("/<name>/start")
def start_fb(name: str):
    """Arranca el FB registrado bajo ``name``."""
    engine = _engine()
    fb = engine.get_fb(name)
    if fb is None:
        return jsonify({
            "error": f"FB '{name}' no registrado en el engine",
        }), 404

    body = request.get_json(silent=True) or {}
    params: dict[str, Any] = body.get("params") or {}

    # fb.start() es async; lo corremos via asyncio.run.
    import asyncio

    started = asyncio.run(fb.start(**params))
    return jsonify({"started": started, "nStep": fb.nStep})


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
# Gap sept-2026: el shell SPA (``plcpanelview.js``) llama a
# ``loadAndApplyPlcBlocks`` con ``force=false`` (lee) o ``force=true``
# (refrescar) apuntando a ``/api/v1/plcs/<name>/blocks``. Esos endpoints
# no existian en routers tras la migracion del worker — los anadimos
# aqui delegando en el comando ``scan_blocks`` del worker TIA
# (``core.infrastructure.tia.tia_handlers._h_scan_blocks``).
#
# El backend OB1 no tiene cache servidor del PLC: cada llamada escanea
# TIA Portal directamente. La diferencia entre GET y POST es solo
# semantica para el operario (el boton ↻ del sidebar dispara la
# variante POST). Devolvemos ``{ ok, snapshot }`` para que
# ``store._applyBlocksSnapshot`` parsee limpio sin distinguir entre
# "snapshot envuelto" y "snapshot directo".
# ---------------------------------------------------------------------------

# Timeout backend para el scan: el comando ``scan_blocks`` recorre
# todos los bloques, tag tables y UDTs del PLC. En S7-1500 con 200+
# bloques tarda 30-60s. 120s cubre holgadamente.
SCAN_TIMEOUT_S = 120.0


def _scan_plc_blocks(plc_name: str):
    """Helper comun: dispatch ``scan_blocks`` y normaliza la respuesta.

    Devuelve ``(status_code, body)``. ``body.ok`` es True si TIA
    respondio OK; ``body.snapshot`` trae el shape ``{ plc_name,
    blocks, tag_tables, udts, scanned_at }``.
    """
    tia_client = current_app.config["TIA_CLIENT"]
    if tia_client.ts is None or tia_client.wrapper is None:
        # No hay portal attached. Distinguible en el cliente por el
        # ``X-Error-Type`` para que ``store.loadAndApplyPlcBlocks``
        # sepa resetear el state PLC.
        resp = jsonify({
            "ok": False,
            "error": "TIA Portal no conectado. Pulse Conectar primero.",
        })
        resp.headers["X-Error-Type"] = "TIAConnectionError"
        return 503, resp

    try:
        result = tia_client.submit_and_wait(
            "scan_blocks",
            {"plc_name": plc_name},
            timeout=SCAN_TIMEOUT_S,
        )
    except TimeoutError as exc:
        resp = jsonify({
            "ok": False,
            "error": f"timeout: {exc}",
        })
        resp.headers["X-Error-Type"] = "TIAConnectionError"
        return 504, resp
    except Exception as exc:  # noqa: BLE001
        logger.exception("scan_blocks '%s' fallo: %s", plc_name, exc)
        resp = jsonify({
            "ok": False,
            "error": f"error inesperado: {exc}",
        })
        resp.headers["X-Error-Type"] = "TIAConnectionError"
        return 500, resp

    if not result.get("ok"):
        # El handler ya valido el argumento ``plc_name``. Si llega
        # aqui es por un error de TIA Portal (proyecto cerrado,
        # PLC renombrado, etc.). El operario ve el mensaje en la
        # ConsolaLogs del sidebar.
        error_msg = result.get("error", "scan_blocks devolvio error")
        resp = jsonify({"ok": False, "error": error_msg})
        if "no portal" in error_msg.lower() or "no attached" in error_msg.lower():
            resp.headers["X-Error-Type"] = "TIAConnectionError"
        return 500, resp

    snapshot = result.get("result") or {}
    return 200, jsonify({"ok": True, "snapshot": snapshot})


# Blueprint separado del de FBs para que el ``url_prefix`` pueda ser
# ``/api/v1/plcs`` (sin el ``/fb``). Mismo modulo para no fragmentar
# el codigo de scan en dos archivos.
bp_blocks = Blueprint("plc_blocks", __name__, url_prefix="/api/v1/plcs")


@bp_blocks.get("/<plc_name>/blocks")
def get_plc_blocks(plc_name: str):
    """Escanea bloques+tag_tables+UDTs del PLC y devuelve el snapshot.

    Lectura con cache cliente (la SPA mantiene el ultimo snapshot en
    ``store.plcBlocksCache``). Si el operario sospecha que los datos
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
