"""Router Flask para gestionar las plantillas TIA del area procesos.

Endpoints:
  GET  /api/v1/procesos/plantillas
        Lista las subcarpetas de ``plantillas_path`` (leido del
        ``ConfigManager`` del departamento activo) que tengan un
        ``manifest.json`` valido. Devuelve ``{ok, plantillas, warning?}``.

        Si ``plantillas_path`` esta vacio o la ruta no existe, devuelve
        ``{ok: True, plantillas: [], warning: "..."}`` con 200 (NO 404):
        el frontend puede mostrar un CTA "configura la ruta" sin tratar
        el caso como error.

  PUT  /api/v1/procesos/plantillas
        Body: ``{plantillas_path: str}``. Persiste el valor en el
        ``config.json`` del usuario (mismo archivo del que ``ConfigManager``
        leyo ``_full_config``) y reemplaza el singleton en
        ``current_app.config["CONFIG_MANAGER"]`` por uno nuevo para que
        el siguiente ``GET`` (y los FBs que leen ``plantillas_path``)
        vean el valor actualizado sin reiniciar el .exe.

        Es unico punto de escritura del campo: el frontend nunca edita
        ``config.json`` directamente.

Notas de timing:
  - GET: lectura pura del filesystem (subcarpetas + manifest.json).
    Tipicamente <100ms. Cliente: bucket FAST.
  - PUT: escritura atomica (write a .tmp + rename) + recarga de
    ConfigManager. Tipicamente <50ms. Cliente: bucket FAST.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint(
    "area_alimentacion_proc_plantillas",
    __name__,
    url_prefix="/api/v1/procesos/plantillas",
)


def _get_config_manager():
    """Devuelve el ``ConfigManager`` de la app (lazy singleton por proceso)."""
    return current_app.config["CONFIG_MANAGER"]


@bp.get("")
def listar_plantillas():
    """Lista las plantillas TIA disponibles en ``plantillas_path``.

    Returns:
        200 con ``{ok: True, plantillas: [...], warning?: str}``.
          ``plantillas`` es lista vacia si no hay ruta configurada o si
          el directorio no existe (en esos casos, ``warning`` explica
          por que).
        500 si falla la lectura del config (caso degenerado).
    """
    config_manager = _get_config_manager()
    plantillas_path = config_manager.get_plantillas_path()

    if not plantillas_path:
        return jsonify({
            "ok": True,
            "plantillas": [],
            "warning": "plantillas_path no configurado en config.json",
        }), 200

    root = Path(plantillas_path)
    if not root.is_dir():
        return jsonify({
            "ok": True,
            "plantillas": [],
            "warning": f"Directorio no existe: {root}",
        }), 200

    plantillas: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            # manifest corrupto: lo loggeamos y seguimos con los demas.
            # El operario vera esta plantilla "rota" en los logs pero
            # las validas seguiran apareciendo.
            logger.warning(
                "plantillas: manifest invalido en %s (%s: %s)",
                manifest_path, type(exc).__name__, exc,
            )
            continue
        if not isinstance(data, dict):
            logger.warning(
                "plantillas: manifest en %s no es un dict (es %s)",
                manifest_path, type(data).__name__,
            )
            continue
        plantillas.append({
            "carpeta": entry.name,
            "base": data.get("base", 0),
            "codigo": data.get("codigo", ""),
            "nombre": data.get("nombre", ""),
            "minimos": data.get("minimos", {}),
        })

    logger.info(
        "plantillas: %d plantilla(s) listada(s) en %s",
        len(plantillas), root,
    )
    return jsonify({"ok": True, "plantillas": plantillas}), 200


@bp.put("")
def actualizar_plantillas_path():
    """Actualiza ``plantillas_path`` en ``config.json`` y recarga el
    ``ConfigManager`` en memoria.

    Body: ``{plantillas_path: str}``. Cadena vacia es valida (equivale
    a "sin configurar") — el operario puede revertir el setting.

    Returns:
        200 con ``{ok: True, plantillas_path: str}`` si la actualizacion
            fue exitosa.
        400 si ``plantillas_path`` no es un str o el JSON del body es
            invalido.
        500 si falla la escritura del config (permisos, disco lleno, etc.)
            o la recarga del ConfigManager.
    """
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        return jsonify({
            "ok": False,
            "error": "body JSON invalido o ausente",
        }), 400

    raw = body.get("plantillas_path", None)
    # ``plantillas_path`` puede ser "" (reset), pero debe ser str.
    if not isinstance(raw, str):
        return jsonify({
            "ok": False,
            "error": "plantillas_path debe ser str (use '' para resetear)",
        }), 400
    new_path = raw

    config_manager = _get_config_manager()
    config_path: Path = config_manager.path
    department = config_manager.department

    # 1. Leer config actual del disco (NO usar ``config_manager._full_config``
    #    porque es lo que queremos refrescar).
    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.error(
            "actualizar_plantillas_path: no se pudo leer config en %s (%s)",
            config_path, exc,
        )
        return jsonify({
            "ok": False,
            "error": f"No se pudo leer config.json: {exc}",
        }), 500

    departments = raw_config.get("departments")
    if not isinstance(departments, dict):
        return jsonify({
            "ok": False,
            "error": "config.json no tiene bloque 'departments' valido",
        }), 500

    if department not in departments:
        return jsonify({
            "ok": False,
            "error": (
                f"departamento activo '{department}' no esta en config.json; "
                f"no se puede actualizar plantillas_path"
            ),
        }), 500

    # 2. Actualizar el campo del departamento activo.
    departments[department]["plantillas_path"] = new_path

    # 3. Escribir de forma atomica: write a .tmp en la misma carpeta
    #    y rename. Asi, si el proceso muere a mitad, no queda un JSON
    #    corrupto. Mismo estilo que el archivo bundleado (indent=2,
    #    ensure_ascii=False).
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="") as fh:
            json.dump(raw_config, fh, indent=2, ensure_ascii=False)
        tmp_path.replace(config_path)
    except OSError as exc:
        logger.exception(
            "actualizar_plantillas_path: fallo escribiendo %s",
            config_path,
        )
        # Limpiar tmp si quedo a medias.
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return jsonify({
            "ok": False,
            "error": f"No se pudo escribir config.json: {exc}",
        }), 500

    # 4. Recargar el ConfigManager en memoria. El nuevo instance usa la
    #    misma ruta (config_manager.path==config_path) y relee el archivo
    #    que acabamos de escribir, asi que ``get_plantillas_path()``
    #    refleja el nuevo valor en el siguiente request.
    try:
        from core.infrastructure.config.config_manager import ConfigManager
        new_config_manager = ConfigManager(config_path=config_path)
        current_app.config["CONFIG_MANAGER"] = new_config_manager
    except Exception as exc:
        logger.exception(
            "actualizar_plantillas_path: fallo recargando ConfigManager"
        )
        # El archivo ya esta bien escrito. Devolvemos 200 con warning
        # porque la siguiente lectura del filesystem vera el valor
        # nuevo (re-arranque del .exe / re-attach del proceso).
        return jsonify({
            "ok": True,
            "plantillas_path": new_path,
            "warning": (
                f"config.json actualizado, pero no se pudo recargar el "
                f"ConfigManager en memoria: {exc}. El nuevo valor se vera "
                f"tras reiniciar la app."
            ),
        }), 200

    logger.info(
        "actualizar_plantillas_path: %s -> %r (dept=%s)",
        department, new_path, config_path,
    )
    return jsonify({
        "ok": True,
        "plantillas_path": new_path,
    }), 200


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de plantillas)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_proc_plantillas' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]