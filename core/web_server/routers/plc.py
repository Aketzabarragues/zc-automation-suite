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

from core.infrastructure.log_web_bridge import install_web_level

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()

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
# Gap el shell SPA (``plcpanelview.js``) llama a
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

# Poll bloqueante del FB en el handler sync de Flask.
_POLL_INTERVAL_S = 0.05


def _scan_plc_blocks(plc_name: str):
    """Helper comun: dispatch via FB ``scan_plc_blocks`` y normaliza la respuesta.

    Devuelve ``(status_code, body)``. ``body.ok`` es True si el FB
    termino OK; ``body.snapshot`` trae el shape ``{ plc_name,
    blocks, tag_tables, udts, scanned_at }`` reconstruido desde
    ``TIADataBloqueCache``.

    Si el portal no esta attached, devuelve 503 + X-Error-Type
    (mismo contrato que la version pre-FB) para que el SPA distinga
    el caso y resetee el state PLC via ``store.loadAndApplyPlcBlocks``.
    """
    import asyncio
    import time

    from core.infrastructure.tia.tia_bloque_cache import TIADataBloqueCache

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

    fb = engine.get_fb("scan_plc_blocks")
    if fb is None:
        resp = jsonify({
            "ok": False,
            "error": "FB 'scan_plc_blocks' no registrado en el engine",
        })
        return 500, resp

    # force_refresh: leer del body si es POST, default False.
    body = request.get_json(silent=True) or {}
    force_refresh = bool(body.get("force_refresh", False))

    # Plan living TRAZABILIDAD_LOGGING §5 (operacion 3): 1 web al iniciar.
    logger.web(
        f"Leyendo cache del PLC '{plc_name}' "
        f"(force_refresh={force_refresh})..."
    )

    started = asyncio.run(fb.start(
        plc_name=plc_name,
        force_refresh=force_refresh,
    ))
    if not started:
        # El FB esta corriendo. Devolvemos 409 para que el SPA sepa
        # reintentar cuando termine.
        return 409, jsonify({
            "ok": False,
            "error": "FB 'scan_plc_blocks' ya activo o terminal. Haz /disconnect y reintenta.",
        })

    # Poll bloqueante hasta que el FB entre en estado terminal.
    elapsed = 0.0
    while not fb.is_terminal() and elapsed < SCAN_TIMEOUT_S:
        time.sleep(_POLL_INTERVAL_S)
        elapsed += _POLL_INTERVAL_S

    if not fb.is_terminal():
        # Timeout: cancelamos el FB y devolvemos 504.
        try:
            asyncio.run(fb.cancel("timeout en /api/v1/plcs/<name>/blocks"))
        except Exception:
            pass
        resp = jsonify({
            "ok": False,
            "error": f"timeout tras {SCAN_TIMEOUT_S:.1f}s sin terminar",
        })
        resp.headers["X-Error-Type"] = "TIAConnectionError"
        return 504, resp

    if fb.nStep == fb.n_error:
        err = fb.error_msg or "FB termino en error"
        resp = jsonify({"ok": False, "error": err})
        if "no portal" in err.lower() or "no attached" in err.lower():
            resp.headers["X-Error-Type"] = "TIAConnectionError"
        return 500, resp

    # OK: leer la cache IT (que el FB relleno via el helper) y
    # devolver el snapshot con la shape que espera la SPA.
    cache = asyncio.run(TIADataBloqueCache.get(plc_name))
    if cache is None:
        # Caso raro: el FB reporto OK pero la cache esta vacia.
        # Devolvemos un snapshot vacio pero valido.
        return 200, jsonify({
            "ok": True,
            "snapshot": {
                "plc_name": plc_name,
                "blocks": [],
                "tag_tables": [],
                "udts": [],
                "scanned_at": None,
            },
        })
    snapshot = cache.to_dict()
    # Plan living §5 (operacion 3): OK con resumen del cache.
    n_bloques = len(snapshot.get("blocks", []))
    n_tablas = len(snapshot.get("tag_tables", []))
    n_udts = len(snapshot.get("udts", []))
    logger.ok(
        f"PLC '{plc_name}' cache: {n_bloques} bloques, "
        f"{n_tablas} tablas, {n_udts} UDTs"
    )
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
