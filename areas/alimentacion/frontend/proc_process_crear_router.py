"""Router Flask del feature "Crear proceso completo desde plantilla TIA".

Endpoints:
  POST /api/v1/procesos/crear/preview
        Body JSON:
          ``plantillas_path``       (str)  ruta base de las plantillas.
          ``dir_plantilla_nombre``  (str)  nombre de la subcarpeta
                                            concreta (p. ej. "PROCESO_ESTANDAR").
          ``base_nueva``            (int)  UID base del proceso nuevo.
          ``codigo_nuevo``          (str)  codigo corto (p. ej. "EXP").
          ``nombre_nuevo``          (str)  nombre humano del proceso.
          ``minimos_usuario``       (dict) 4 N_MAX del operario
                                            (claves N_MAX_PREAL,
                                            N_MAX_PINT, N_MAX_ALM,
                                            N_MAX_ALM_HMI).
          ``plc_blocks_cache``      (list[str] | null, opcional) nombres de
                                            bloques que ya existen en el PLC
                                            destino (para detectar colisiones).

        Dispara el FB ``proc_process_crear_preview`` (read-only:
        copytree + regex + lista de archivos previstos + colisiones).
        Devuelve el ``result`` con shape legacy completa.

  POST /api/v1/procesos/crear/aplicar
        Body JSON: igual que ``/preview`` mas:
          ``plc_name``              (str) nombre del PLC destino (oblig).

        Dispara el FB ``proc_process_crear_aplicar`` (5 dispatches al
        worker OT: import tag table + 2 imports de bloques + compile).
        Devuelve el ``result`` con shape legacy completa (incluye
        ``import_result`` y ``compile_result``).

Notas de timing:
  - Preview: copytree + regex sobre ~20 archivos pequenos. Tarda
    tipicamente 5-30s. STEP_TIMEOUT_S=120s en el FB. Cliente: bucket
    MEDIUM (export equivalente a apiGeneratePreview).
  - Apply: 5 dispatches al worker OT (3 imports + 1 compile, mas un
    sleep de consolidacion de 2s). En PLCs grandes el import masivo
    puede tardar 1-3 min, el compile hasta 5 min. STEP_TIMEOUT_S=600s.
    Cliente: bucket SLOW (igual que apiProcesosSyncCommit).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint(
    "area_alimentacion_proc_process_crear",
    __name__,
    url_prefix="/api/v1/procesos/crear",
)


# Campos obligatorios en ambos endpoints. ``plc_name`` se valida solo
# en ``/apply`` (el preview es offline).
_BODY_REQUIRED_PREVIEW: tuple[str, ...] = (
    "plantillas_path",
    "dir_plantilla_nombre",
    "base_nueva",
    "codigo_nuevo",
    "nombre_nuevo",
    "minimos_usuario",
)
_BODY_REQUIRED_APLICAR: tuple[str, ...] = (
    "plantillas_path",
    "dir_plantilla_nombre",
    "base_nueva",
    "codigo_nuevo",
    "nombre_nuevo",
    "minimos_usuario",
    "plc_name",
)


def _get_engine():
    return current_app.config["ENGINE"]


def _get_fb(name: str) -> Any:
    return _get_engine().get_fb(name)


def _validate_common(body: dict) -> tuple[dict | None, str | None]:
    """Valida los campos comunes de /preview y /apply.

    Returns:
        Tupla (validated_body, error_msg). Si error_msg != None,
        el body es invalido y el caller devuelve 400 con ese texto.
    """
    for key in _BODY_REQUIRED_PREVIEW:
        if key not in body:
            return None, f"falta '{key}' en el body"

    if not isinstance(body["plantillas_path"], str):
        return None, "plantillas_path debe ser str"
    if not isinstance(body["dir_plantilla_nombre"], str):
        return None, "dir_plantilla_nombre debe ser str"
    if not isinstance(body["base_nueva"], int):
        return None, "base_nueva debe ser int"
    if not isinstance(body["codigo_nuevo"], str):
        return None, "codigo_nuevo debe ser str"
    if not isinstance(body["nombre_nuevo"], str):
        return None, "nombre_nuevo debe ser str"
    if not isinstance(body["minimos_usuario"], dict) or not body["minimos_usuario"]:
        return None, (
            "minimos_usuario debe ser dict no vacio "
            "(claves N_MAX_PREAL/PINT/ALM/ALM_HMI)"
        )

    validated: dict[str, Any] = {
        "plantillas_path": body["plantillas_path"],
        "dir_plantilla_nombre": body["dir_plantilla_nombre"],
        "base_nueva": int(body["base_nueva"]),
        "codigo_nuevo": str(body["codigo_nuevo"]),
        "nombre_nuevo": str(body["nombre_nuevo"]),
        "minimos_usuario": dict(body["minimos_usuario"]),
    }

    # ``plc_blocks_cache`` es opcional. Si viene, lo pasamos como set.
    pbc_raw = body.get("plc_blocks_cache")
    if pbc_raw is not None:
        if not isinstance(pbc_raw, list):
            return None, "plc_blocks_cache debe ser list[str] o null"
        validated["plc_blocks_cache"] = set(str(x) for x in pbc_raw)

    return validated, None


def _poll_until_terminal(fb: Any, poll_interval_s: float = 0.1) -> bool:
    """Poll bloqueante hasta que el FB entre en estado terminal.

    Returns:
        True si termino OK (en ``n_done`` o ``n_error``). False si
        el timeout del FB se agoto sin transicionar.
    """
    elapsed = 0.0
    fb_step_timeout = getattr(fb, "STEP_TIMEOUT_S", 600.0)
    while not fb.is_terminal() and elapsed < fb_step_timeout:
        time.sleep(poll_interval_s)
        elapsed += poll_interval_s
    if not fb.is_terminal():
        fb.cancel("timeout en /api/v1/procesos/crear")
        return False
    return True


@bp.post("/preview")
def crear_preview():
    """Dispara el FB ``proc_process_crear_preview`` y devuelve su ``result``.

    Body JSON (ver docstring del modulo para detalle):
      ``plantillas_path``, ``dir_plantilla_nombre``, ``base_nueva``,
      ``codigo_nuevo``, ``nombre_nuevo``, ``minimos_usuario`` y,
      opcionalmente, ``plc_blocks_cache``.

    Returns:
        200 con el ``result`` completo del FB (incluye
            ``manifest_plantilla``, ``archivos_previstos``, ``colisiones``,
            ``preview_dir``, ``success``).
        400 si faltan campos obligatorios en el body.
        409 si el FB ya esta activo o terminal (rechazo de start()).
        500 si el FB no esta registrado o termino en error.
        504 si el FB agoto su STEP_TIMEOUT_S sin terminar.
    """
    body = request.get_json(silent=True) or {}
    validated, err = _validate_common(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    fb = _get_fb("proc_process_crear_preview")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'proc_process_crear_preview' no registrado en el engine",
        }), 500

    import asyncio
    logger.web(
        f"Preview: crear proceso {validated['base_nueva']}/"
        f"{validated['codigo_nuevo']} desde plantilla "
        f"{validated['dir_plantilla_nombre']}..."
    )
    started = asyncio.run(fb.start(**validated))
    if not started:
        return jsonify({
            "ok": False,
            "error": (
                "FB 'proc_process_crear_preview' ya activo o terminal. "
                "Espera a que termine y reintenta."
            ),
        }), 409

    if not _poll_until_terminal(fb):
        return jsonify({
            "ok": False,
            "error": (
                f"timeout tras {fb.STEP_TIMEOUT_S:.1f}s sin terminar "
                f"(preview crear proceso)"
            ),
        }), 504

    if fb.nStep == fb.n_error:
        return jsonify({
            "ok": False,
            "error": fb.error_msg or "FB termino en error",
            "nStep": fb.nStep,
        }), 500

    result = fb.result or {"ok": True}
    # Resumen legible para la ConsolaLogs (mismo patron que proc_sync).
    n_prev = (
        len(result.get("archivos_previstos", []))
        if isinstance(result, dict) else 0
    )
    n_col = (
        len(result.get("colisiones", []))
        if isinstance(result, dict) else 0
    )
    logger.ok(
        f"Preview crear proceso {validated['base_nueva']}/"
        f"{validated['codigo_nuevo']}: {n_prev} archivos previstos, "
        f"{n_col} colision(es)."
    )
    return jsonify(result)


@bp.post("/aplicar")
def crear_aplicar():
    """Dispara el FB ``proc_process_crear_aplicar`` y devuelve su ``result``.

    Body JSON: igual que ``/preview`` mas ``plc_name`` (obligatorio).

    Returns:
        200 con el ``result`` completo del FB (incluye
            ``manifest_plantilla``, ``archivos_generados``, ``colisiones``,
            ``modified_dir``, ``success``, ``import_result`` y
            ``compile_result``).
        400 si faltan campos obligatorios en el body.
        409 si el FB ya esta activo o terminal.
        500 si el FB no esta registrado o termino en error.
        504 si timeout.
    """
    body = request.get_json(silent=True) or {}

    # Validacion comun primero.
    validated, err = _validate_common(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    # ``plc_name`` es obligatorio solo en /apply.
    if "plc_name" not in body or not isinstance(body["plc_name"], str):
        return jsonify({
            "ok": False,
            "error": "plc_name (str) es obligatorio en el body",
        }), 400
    validated["plc_name"] = str(body["plc_name"])

    fb = _get_fb("proc_process_crear_aplicar")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'proc_process_crear_aplicar' no registrado en el engine",
        }), 500

    import asyncio
    logger.web(
        f"Aplicar: crear proceso {validated['base_nueva']}/"
        f"{validated['codigo_nuevo']} en PLC '{validated['plc_name']}' "
        f"desde plantilla {validated['dir_plantilla_nombre']}..."
    )
    started = asyncio.run(fb.start(**validated))
    if not started:
        return jsonify({
            "ok": False,
            "error": (
                "FB 'proc_process_crear_aplicar' ya activo o terminal. "
                "Espera a que termine y reintenta."
            ),
        }), 409

    if not _poll_until_terminal(fb):
        return jsonify({
            "ok": False,
            "error": (
                f"timeout tras {fb.STEP_TIMEOUT_S:.1f}s sin terminar "
                f"(aplicar crear proceso)"
            ),
        }), 504

    if fb.nStep == fb.n_error:
        return jsonify({
            "ok": False,
            "error": fb.error_msg or "FB termino en error",
            "nStep": fb.nStep,
        }), 500

    result = fb.result or {"ok": True}
    n_gen = (
        len(result.get("archivos_generados", []))
        if isinstance(result, dict) else 0
    )
    compile_ok = (
        ((result.get("compile_result") or {}).get("ok"))
        if isinstance(result, dict) else False
    )
    logger.ok(
        f"Proceso {validated['base_nueva']}/{validated['codigo_nuevo']} "
        f"creado en '{validated['plc_name']}': {n_gen} archivos generados, "
        f"compile={'OK' if compile_ok else 'FAIL'}."
    )
    return jsonify(result)


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Crear Proceso)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_proc_process_crear' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]