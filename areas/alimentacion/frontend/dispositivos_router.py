"""Router Flask del dominio de alimentacion.

Endpoints que exponen el modelo ``DataExcelCache`` (especifico de esta
area) via HTTP REST. Montado por el shell Flask a traves del hook
``AreaSpec.contributes_routers`` de alimentacion. El shell no sabe
que existe este router; solo lo registra cuando el AreaRegistry lo
descubre.

Endpoints:
  GET /api/v1/state/dispositivos -> vuelca AppState del area:
    - ``dimensiones``     (num_disp_ed, ...)
    - ``dispositivos``    ({canonica: [Dispositivo, ...]})
    - ``procesos``        (DataExcelCache.procesos)
    - ``parametros_int``  (DataExcelCache.parametros_int)
    - ``parametros_real`` (DataExcelCache.parametros_real)
    - ``alarmas``         (DataExcelCache.alarmas)
    - ``software_parsers_implemented`` (bool)

Las dependencias se inyectan via ``current_app.config['_LAZY_*']``
y ``current_app.config['CONFIG_MANAGER']``. Ver
``core/web_server/app_flask.create_app``.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

from flask import Blueprint, current_app, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint(
    "area_alimentacion_dispositivos",
    __name__,
    url_prefix="/api/v1",
)


def _extract_software_from_cache(state: Any) -> dict[str, Any]:
    """Extrae 4 dominios de software + flag + plcs desde ``excel_cache_full``.

    Multi-PLC: la pagina "definicion programacion" recibe el cache
    COMPLETO (sin filtrar), no el cache activo. Asi el operario
    puede analizar todos los PLCs del Excel a la vez.
    """
    empty: dict[str, Any] = {
        "procesos": [],
        "parametros_int": [],
        "parametros_real": [],
        "alarmas": [],
        "plcs": [],
        "software_parsers_implemented": False,
    }
    cache = state.excel_cache_full
    if cache is None:
        return empty
    try:
        return {
            "procesos": [dataclasses.asdict(p) for p in cache.procesos],
            "parametros_int": [dataclasses.asdict(p) for p in cache.parametros_int],
            "parametros_real": [dataclasses.asdict(p) for p in cache.parametros_real],
            "alarmas": [dataclasses.asdict(a) for a in cache.alarmas],
            "plcs": [dataclasses.asdict(p) for p in cache.plcs],
            "software_parsers_implemented": bool(
                getattr(cache, "software_parsers_implemented", False)
            ),
        }
    except Exception as exc:
        logger.debug("Error extrayendo software del cache: %s", exc)
        return empty


def _get_app_state():
    return current_app.config["_LAZY_APP_STATE"]()


def _get_config_manager():
    return current_app.config["CONFIG_MANAGER"]


@bp.get("/state/dispositivos")
def state_dispositivos():
    """Vuelca AppState a JSON para el Inspector IT del area.

    Sept-2026 (multi-PLC): los dispositivos y dimensiones vienen del
    cache COMPLETO (``excel_cache_full``), NO del cache activo. Asi el
    operario ve TODO el Excel en la pagina "definicion programacion",
    independientemente del PLC que tenga seleccionado.
    """
    state = _get_app_state()
    config_manager = _get_config_manager()

    cache_full = state.excel_cache_full
    cache_dispositivos: dict = (
        cache_full.dispositivos if cache_full is not None else {}
    )

    dispositivos_payload: dict[str, list[dict[str, Any]]] = {}
    for hw in config_manager.list_hw_types_active():
        target = config_manager.get_excel_target_for(hw)
        if target is None:
            continue
        canonica = target.get("canonical", "")
        if not canonica:
            continue
        dispositivos_payload[canonica] = [
            dataclasses.asdict(d) for d in cache_dispositivos.get(hw, ())
        ]

    dimensiones_dict: dict = {}
    if cache_full is not None and getattr(cache_full, "n_max", None) is not None:
        dimensiones_dict = cache_full.n_max.to_api_dict()

    return jsonify({
        "ok": True,
        "dimensiones": dimensiones_dict,
        "dispositivos": dispositivos_payload,
        **_extract_software_from_cache(state),
    })


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area.

    Llamado por ``AreaRegistry.for_each("contributes_routers", app=app)``
    desde ``core/web_server/app_flask.create_app``. Registra el blueprint
    de este modulo en la Flask app.
    """
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_dispositivos' registrado."
    )


__all__ = ["bp", "build_routers"]
