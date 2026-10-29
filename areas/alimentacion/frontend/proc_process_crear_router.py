"""Router Flask del feature "Crear proceso completo desde plantilla TIA".

Orquesta: encola el trabajo en el OB1 (dispatcher con cola) y devuelve
el ``job_id``. Los FBs tienen la state machine + tracker; los helpers
(``areas/alimentacion/helpers/proc/``) tienen la logica pura.

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

        El router extrae del ``app_cache.area("alimentacion").excel_full.procesos[uid]``
        los campos que el FB necesita:
          ``base``       = ``proceso.uid``
          ``codigo``     = ``proceso.codigo``
          ``nombre``     = ``proceso.nombre``
          ``minimos``    = ``{N_MAX_PREAL: preal, N_MAX_PINT: pint,
                              N_MAX_ALM: alarmas, N_MAX_ALM_HMI: alm_hmi}``

        Esto es coherente con el resto del feature: el Excel del
        operario ES la fuente de verdad para los datos del nuevo
        proceso. La SPA solo elige plantilla + proceso del Excel y
        el sistema rellena el resto.

        Encola el FB ``proc_process_crear_preview`` (read-only:
        copytree + regex + lista de archivos previstos + colisiones) y
        devuelve ``202`` con ``{"ok": true, "job_id": "<hex>"}``. El
        resultado del preview (shape legacy completa) llega al HMI por
        el evento SSE ``fb_state``.

  POST /api/v1/procesos/crear/aplicar
        Body JSON: igual que ``/preview`` mas:
          ``plc_name``              (str) nombre del PLC destino (oblig).

        Encola el FB ``proc_process_crear_aplicar`` (5 dispatches al
        worker OT: import tag table + 2 imports de bloques + compile) y
        devuelve ``202`` con ``{"ok": true, "job_id": "<hex>"}``. El
        resultado (shape legacy completa, incluye ``import_result`` y
        ``compile_result``) llega al HMI por el evento SSE ``fb_state``.

Notas de timing:
  - Preview: copytree + regex sobre ~20 archivos pequenos. Tarda
    tipicamente 5-30s. STEP_TIMEOUT_S=120s en el FB.
  - Apply: 5 dispatches al worker OT (3 imports + 1 compile, mas un
    sleep de consolidacion de 2s). En PLCs grandes el import masivo
    puede tardar 1-3 min, el compile hasta 5 min. STEP_TIMEOUT_S=600s.
  - El request NO bloquea: el router responde 202 de inmediato y el
    trabajo lo ejecuta el hilo del OB1.
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from core.composition.plc_engine import FBBusyError
from core.helpers.tia.with_plc import with_plc
from core.helpers.tia.validate_plc_in_excel import validate_plc_in_excel
from core.infrastructure.log.log_web_bridge import install_web_level
from core.runtime.excel_cache import excel_get_full
from areas.alimentacion._area_id import AREA_ID

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()

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


def _get_config_manager():
    return current_app.config["CONFIG_MANAGER"]


def _get_app_cache():
    return current_app.config["APP_CACHE"]


def _resolve_excel_proc(app_cache, proc_uid: int):
    """Busca el proceso del Excel por UID y lo devuelve.

    Lee del cache completo del Excel (area ``"alimentacion"``): el
    router es pre-validacion PLC-especifica; ``validate_plc_in_excel``
    luego confirma que el plc_name del body esta entre los PLCs del
    Excel.

    Lanza ``ValueError`` accionable si no hay excel_cache_full o si
    el proceso no esta. Mantener el mensaje humano para que la SPA
    sepa que tiene que subir el Excel o seleccionar otro proceso.
    """
    cache = excel_get_full(app_cache, "alimentacion")
    if cache is None:
        raise ValueError(
            "Excel no cargado en el area. Cargue primero el archivo con "
            "POST /api/v1/excel/upload."
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
      nombre_nuevo, minimos_usuario,
      plc_blocks_cache (set[str] opcional, solo match por nombre).
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
        app_cache = _get_app_cache()
        proc = _resolve_excel_proc(app_cache, body["proc_uid"])
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
    #   - ``list[str]``: solo nombres completos de bloques que ya
    #     existen en el PLC destino (legacy).
    #   - ``list[dict{ nombre, numero }]`` (recomendado): cada item
    #     lleva ``nombre`` (campo ``"name"`` compat) y opcionalmente
    #     ``numero`` (int). Esto permite que el helper cruce por
    #     nombre O por numero contra los bloques post-rename. Si el
    #     scanner del sidebar emite ``numero``, el match detecta
    #     cross-type (DB60010 vs FB60010).
    # El router normaliza TODO a ``list[dict{nombre, numero}]``: los
    # ``str`` legacy se envuelven en ``{nombre, numero: None}``, los
    # dicts sin nombre se descartan (defensivo). El campo ``numero``
    # se coerce a ``int`` si llega como string numerico.
    pbc_raw = body.get("plc_blocks_cache")
    if pbc_raw is not None:
        if not isinstance(pbc_raw, list):
            return None, "plc_blocks_cache debe ser list[str|dict] o null"
        bloques_list: list[dict[str, Any]] = []
        for item in pbc_raw:
            if isinstance(item, dict):
                nombre = item.get("nombre") or item.get("name") or ""
                if not nombre:
                    # Item sin nombre util -> descartar defensivo.
                    continue
                numero_raw = item.get("numero")
                numero: int | None = None
                if isinstance(numero_raw, bool):  # bool es subclass de int
                    numero = None
                elif isinstance(numero_raw, int):
                    numero = numero_raw
                elif isinstance(numero_raw, str) and numero_raw.isdigit():
                    numero = int(numero_raw)
                bloques_list.append({
                    "nombre": str(nombre),
                    "numero": numero,
                })
            elif isinstance(item, str) and item:
                bloques_list.append({"nombre": item, "numero": None})
        if bloques_list:
            validated["plc_blocks_cache"] = bloques_list

    return validated, None


@bp.post("/preview")
def crear_preview():
    """Encola el FB ``proc_process_crear_preview`` para el proceso del body.

    Body JSON (ver docstring del modulo):
      ``dir_plantilla_nombre``, ``proc_uid``, opcional ``plc_blocks_cache``.

    El request NO bloquea: encola el trabajo en el OB1 y devuelve
    ``202`` con el ``job_id``. El FB se ejecuta en el hilo del OB1 y
    su resultado llega al HMI por el evento SSE ``fb_state`` (con el
    mismo ``job_id``).

    Returns:
        202 con ``{"ok": true, "job_id": "<hex>"}``.
        400 si faltan campos obligatorios o proc_uid no esta en el Excel.
        409 si el FB ya tiene un trabajo en curso.
        500 si el FB no esta registrado en el engine.
    """
    body = request.get_json(silent=True) or {}
    validated, err = _validate_common(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    engine = _get_engine()
    if engine is None:
        return jsonify({
            "ok": False,
            "error": "Engine no disponible",
        }), 500

    fb = engine.get_fb("proc_process_crear_preview")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'proc_process_crear_preview' no registrado en el engine",
        }), 500

    logger.web(
        f"Preview: crear proceso {validated['base_nueva']}/"
        f"{validated['codigo_nuevo']} desde plantilla "
        f"{validated['dir_plantilla_nombre']}..."
    )
    try:
        job_id = engine.submit("proc_process_crear_preview", **validated)
    except FBBusyError as exc:
        return jsonify({
            "ok": False,
            "error": (
                f"FB 'proc_process_crear_preview' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        logger.exception("dispatch: no se pudo encolar el trabajo")
        return jsonify({
            "ok": False,
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    # El log de cierre lo emite el FB al terminar el trabajo: el router
    # responde 202 antes de que el FB haya ejecutado, asi que aqui no
    # hay ningun resultado real que resumir.
    return jsonify({"ok": True, "job_id": job_id}), 202


@bp.post("/aplicar")
def crear_aplicar():
    """Encola el FB ``proc_process_crear_aplicar`` para el proceso del body.

    Body JSON: ``dir_plantilla_nombre``, ``proc_uid``, ``plc_name``
    (obligatorio). Opcional ``plc_blocks_cache``.

    El request NO bloquea: encola el trabajo en el OB1 y devuelve
    ``202`` con el ``job_id``. El FB se ejecuta en el hilo del OB1 y
    su resultado llega al HMI por el evento SSE ``fb_state`` (con el
    mismo ``job_id``).

    Returns:
        202 con ``{"ok": true, "job_id": "<hex>"}``.
        400 si faltan campos, si proc_uid no esta en el Excel o si el
        plc_name no esta entre los PLCs del Excel.
        409 si el FB ya tiene un trabajo en curso.
        500 si el FB no esta registrado en el engine.
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

    engine = _get_engine()
    if engine is None:
        return jsonify({
            "ok": False,
            "error": "Engine no disponible",
        }), 500

    fb = engine.get_fb("proc_process_crear_aplicar")
    if fb is None:
        return jsonify({
            "ok": False,
            "error": "FB 'proc_process_crear_aplicar' no registrado en el engine",
        }), 500

    # Sincronizar app_cache.selected_plc con el plc_name del body
    # antes de encolar el FB (D6 stateless: el FB
    # ``function_proc_crear_sincronizar`` no recibe ``app_cache`` por
    # constructor, asi que el endpoint es responsable de propagarlo).
    with_plc(_get_app_cache(), validated["plc_name"], AREA_ID)

    # Validar contra el Excel cargado (multi-PLC). El FB no lo hace
    # porque no tiene acceso al AppCache. Fail-fast aqui permite que
    # el operario reciba 400 inmediato en lugar de esperar al
    # progress tracker. Es validacion de entrada (el PLC no existe en
    # el Excel), no un fallo del servidor: el mensaje lo da
    # ``validate_plc_in_excel`` e incluye los PLCs disponibles.
    try:
        validate_plc_in_excel(_get_app_cache(), validated["plc_name"], AREA_ID)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    logger.web(
        f"Aplicar: crear proceso {validated['base_nueva']}/"
        f"{validated['codigo_nuevo']} en PLC '{validated['plc_name']}' "
        f"desde plantilla {validated['dir_plantilla_nombre']}..."
    )
    try:
        job_id = engine.submit("proc_process_crear_aplicar", **validated)
    except FBBusyError as exc:
        return jsonify({
            "ok": False,
            "error": (
                f"FB 'proc_process_crear_aplicar' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        logger.exception("dispatch: no se pudo encolar el trabajo")
        return jsonify({
            "ok": False,
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    # El log de cierre lo emite el FB al terminar el trabajo: el router
    # responde 202 antes de que el FB haya ejecutado, asi que aqui no
    # hay ningun resultado real que resumir.
    return jsonify({"ok": True, "job_id": job_id}), 202


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Crear Proceso)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_proc_process_crear' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]
