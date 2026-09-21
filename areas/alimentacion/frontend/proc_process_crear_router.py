"""Router Flask del feature "Crear proceso completo desde plantilla TIA".

Endpoints:
  POST /api/v1/procesos/crear/preview
        Body JSON (minimalista — el Excel es la fuente de verdad):
          ``dir_plantilla_nombre``  (str)  nombre de la subcarpeta
                                            concreta (p.ej. "PROCESO_ESTANDAR").
          ``proc_uid``              (int)  UID del proceso del Excel
                                            que el operario quiere crear
                                            en el PLC.
          ``plantillas_path``       (str, opcional) ruta base de plantillas.
                                            Si no viene, se toma del
                                            ConfigManager del backend.
          ``plc_blocks_cache``      (list[str|dict] | null, opcional) bloques
                                            que ya existen en el PLC destino.
                                            Acepta tanto ``list[str]`` (solo
                                            nombres, compat legacy) como
                                            ``list[dict{ nombre, numero }]``
                                            (recomendado — usa match por
                                            nombre OR por numero). Si el
                                            scanner del sidebar emite numeros
                                            (prop ``numero`` del bloque), la
                                            deteccion por numero detecta
                                            cross-type (DB60010 vs FB60010).

        El router extrae del ``AppState.excel_cache.procesos[uid]`` los
        campos que el FB necesita:
          ``base``       = ``proceso.uid``
          ``codigo``     = ``proceso.codigo``
          ``nombre``     = ``proceso.nombre``
          ``minimos``    = ``{N_MAX_PREAL: preal, N_MAX_PINT: pint,
                              N_MAX_ALM: alarmas, N_MAX_ALM_HMI: alm_hmi}``

        Esto es coherente con el resto del feature: el Excel del
        operario ES la fuente de verdad para los datos del nuevo
        proceso. La SPA solo elige plantilla + proceso del Excel y
        el sistema rellena el resto.

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


_BODY_REQUIRED_PREVIEW: tuple[str, ...] = (
    "dir_plantilla_nombre",
    "proc_uid",
)
_BODY_REQUIRED_APLICAR: tuple[str, ...] = (
    "dir_plantilla_nombre",
    "proc_uid",
    "plc_name",
)


def _get_engine():
    return current_app.config["ENGINE"]


def _get_fb(name: str) -> Any:
    return _get_engine().get_fb(name)


def _get_config_manager():
    return current_app.config["CONFIG_MANAGER"]


def _get_app_state():
    return current_app.config["_LAZY_APP_STATE"]()


def _resolve_excel_proc(app_state, proc_uid: int):
    """Busca el proceso del Excel por UID y lo devuelve.

    Lanza ``ValueError`` accionable si no hay excel_cache o si el
    proceso no esta. Mantener el mensaje humano para que la SPA
    sepa que tiene que subir el Excel o seleccionar otro proceso.
    """
    cache = getattr(app_state, "excel_cache", None)
    if cache is None:
        raise ValueError(
            "AppState.excel_cache esta vacio. Cargue primero el Excel "
            "con POST /api/v1/excel/upload."
        )
    for p in cache.procesos:
        if int(p.uid) == int(proc_uid):
            return p
    raise ValueError(
        f"El proceso con UID {proc_uid} no esta en el Excel cargado. "
        f"Selecciona otro proceso o actualiza el Excel."
    )


def _validate_common(body: dict) -> tuple[dict | None, str | None]:
    """Valida el body y devuelve kwargs listos para el FB.

    Returns:
        Tupla (validated_body, error_msg). Si error_msg != None,
        el body es invalido y el caller devuelve 400 con ese texto.

    El validated_body contiene la forma VIEJA que el FB espera:
      plantillas_path, dir_plantilla_nombre, base_nueva, codigo_nuevo,
      nombre_nuevo, minimos_usuario, plc_blocks_cache (set[str] opcional),
      plc_blocks_numeros (set[int] opcional, derivado de los numeros
      de los items dict del body cuando aplica).
    Los campos del proceso (base/codigo/nombre/N_MAX) NO vienen del
    body: los resuelve el router desde el Excel via
    ``_resolve_excel_proc``.
    """
    for key in _BODY_REQUIRED_PREVIEW:
        if key not in body:
            return None, f"falta '{key}' en el body"

    if not isinstance(body["dir_plantilla_nombre"], str):
        return None, "dir_plantilla_nombre debe ser str"
    if not isinstance(body["proc_uid"], int) or isinstance(body["proc_uid"], bool):
        return None, "proc_uid debe ser int"

    # ``plantillas_path`` opcional: si no viene, se toma del ConfigManager.
    config_manager = _get_config_manager()
    plantillas_path = body.get("plantillas_path") or config_manager.get_plantillas_path()
    if not isinstance(plantillas_path, str) or not plantillas_path:
        return None, (
            "plantillas_path no configurado. Pulsa 'Configurar ruta de "
            "plantillas' en la SPA o pasalo en el body."
        )

    # Lookup del proceso del Excel. Aqui es donde el body deja de
    # mentir: si dice proc_uid=300 pero en el Excel no existe, error.
    try:
        app_state = _get_app_state()
        proc = _resolve_excel_proc(app_state, body["proc_uid"])
    except ValueError as exc:
        return None, str(exc)

    validated: dict[str, Any] = {
        "plantillas_path": plantillas_path,
        "dir_plantilla_nombre": body["dir_plantilla_nombre"],
        "base_nueva": int(proc.uid),
        "codigo_nuevo": str(proc.codigo),
        "nombre_nuevo": str(proc.nombre),
        "minimos_usuario": {
            "N_MAX_PREAL": int(proc.preal),
            "N_MAX_PINT": int(proc.pint),
            "N_MAX_ALM": int(proc.alarmas),
            "N_MAX_ALM_HMI": int(proc.alm_hmi),
        },
    }

    # ``plc_blocks_cache`` es opcional. Acepta dos shapes:
    #   - ``list[str]`` (compat legacy): solo nombres, sin numeros.
    #   - ``list[dict{ nombre, numero }]``: nombres + numeros
    #     extraidos del scanner del PLC. El router deriva ambos sets.
    pbc_raw = body.get("plc_blocks_cache")
    if pbc_raw is not None:
        if not isinstance(pbc_raw, list):
            return None, "plc_blocks_cache debe ser list[str|dict] o null"
        nombres: set[str] = set()
        numeros: set[int] = set()
        for item in pbc_raw:
            if isinstance(item, dict):
                nm = item.get("nombre") or item.get("name")
                if nm:
                    nombres.add(str(nm))
                num = item.get("numero") or item.get("number")
                if num is not None:
                    try:
                        numeros.add(int(num))
                    except (TypeError, ValueError):
                        # Numero invalido; lo ignoramos (defensivo).
                        pass
            else:
                # Item es string -> compat legacy: solo nombre.
                nombres.add(str(item))
        if nombres:
            validated["plc_blocks_cache"] = nombres
        if numeros:
            validated["plc_blocks_numeros"] = numeros

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

    Body JSON (ver docstring del modulo):
      ``dir_plantilla_nombre``, ``proc_uid``, opcional ``plc_blocks_cache``.

    Returns:
        200 con el ``result`` completo del FB.
        400 si faltan campos obligatorios o proc_uid no esta en el Excel.
        409 si el FB ya esta activo o terminal.
        500 si el FB no esta registrado o termino en error.
        504 si agoto su STEP_TIMEOUT_S sin terminar.
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

    Body JSON: ``dir_plantilla_nombre``, ``proc_uid``, ``plc_name``
    (obligatorio). Opcional ``plc_blocks_cache``.

    Returns:
        200 con el ``result`` completo del FB.
        400 si faltan campos o proc_uid no esta en el Excel.
        409 si el FB ya esta activo o terminal.
        500 si el FB no esta registrado o termino en error.
        504 si timeout.
    """
    body = request.get_json(silent=True) or {}

    validated, err = _validate_common(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

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
