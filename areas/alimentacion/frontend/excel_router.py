"""Router Flask del endpoint ``POST /api/v1/excel/upload``.

Orquesta: recibe el archivo, lo escribe a un tempfile y encola el
trabajo en el OB1 para el FB ``subir_excel``
(``FunctionExcelCargar``). Los helpers
(``helpers/excel/excel_upload.py``) tienen la logica pura; el FB tiene
la state machine + tracker.

Montado por el shell Flask a traves del hook
``AreaSpec.contributes_routers`` de alimentacion.

Endpoint:
  POST /api/v1/excel/upload     -> multipart/form-data con campo
                                   ``file``. Encola el FB
                                   ``subir_excel`` y devuelve ``202``
                                   con ``{"ok": true, "job_id":
                                   "<hex>"}``. El resultado del parseo
                                   llega al HMI por push (SSE
                                   ``fb_state``, con el mismo
                                   ``job_id``) y el Excel ya parseado se
                                   publica en el slot ``excel_full``
                                   del AppCache que reescribe el FB.

Notas de timing:
  - El request NO bloquea: el router responde 202 de inmediato y el
    trabajo lo ejecuta el hilo del OB1.
  - El temporal que escribe el router lo borra el FB (es quien lo
    lee): el router solo lo borra si NO ha conseguido encolar el
    trabajo, caso en el que el FB nunca lo va a leer.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from core.composition.plc_engine import FBBusyError
from core.infrastructure.log.log_web_bridge import install_web_level

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()

bp = Blueprint(
    "area_alimentacion_excel",
    __name__,
    url_prefix="/api/v1/excel",
)


def _get_engine():
    return current_app.config["ENGINE"]


def _borrar_temporal(path: Path) -> None:
    """Borra el tempfile del upload. No revienta si ya no esta."""
    try:
        os.unlink(path)
    except OSError:
        pass


@bp.post("/upload")
def upload_excel():
    """Recibe un ``.xlsx`` y encola el FB ``subir_excel``.

    Escribe el archivo a un tempfile y encola el trabajo en el OB1.
    El request NO bloquea: devuelve ``202`` con el ``job_id`` y el
    FB se ejecuta despues, en el hilo del OB1. El resultado del
    parseo llega al HMI por el evento SSE ``fb_state`` (con el mismo
    ``job_id``) y por el slot ``excel_full`` del AppCache que
    publica el FB al terminar.

    El temporal lo borra el FB (es quien lo lee). Este router solo lo
    borra si el trabajo NO llega a encolarse, porque en ese caso el
    FB nunca lo va a leer.

    Returns:
        202 con ``{"ok": True, "job_id": "<hex>"}``.
        400 si falta el archivo o no es ``.xlsx``/``.xlsm``.
        409 si el FB ya tiene un trabajo en curso.
        500 si no hay engine o el FB no esta registrado en el engine.
    """
    if "file" not in request.files:
        return jsonify({
            "ok": False,
            "error": "campo 'file' obligatorio en multipart/form-data",
        }), 400

    file = request.files["file"]
    suffix = Path(file.filename or "upload.xlsx").suffix or ".xlsx"
    if suffix.lower() not in (".xlsx", ".xlsm"):
        return jsonify({
            "ok": False,
            "error": f"solo se aceptan .xlsx o .xlsm (recibido: {suffix})",
        }), 400

    # ── 1. Escribir el archivo a un tempfile ──
    # ``delete=False`` es necesario porque el archivo se lee FUERA del
    # bloque ``with`` (el FB lo abre con el path que le pasamos). El
    # borrado lo hace el FB al terminar: si el trabajo llega a
    # encolarse, el FB es el dueno del fichero.
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix, prefix="zcupload_"
    ) as tmp:
        file.save(tmp)
        tmp_path = Path(tmp.name)

    logger.info(
        "[area/excel] Recibiendo upload: '%s' (%d bytes)",
        file.filename, tmp_path.stat().st_size,
    )
    # 1 web + 1 ok con el resumen completo del Excel. El operario ve en
    # la consola web "Cargando Excel ... -> Excel cargado: N disp + N
    # proc + ...". El "ok" lo emite el FB al terminar: el router ya ha
    # respondido antes de que el Excel este cargado.
    logger.web(
        f"Cargando Excel '{file.filename}' "
        f"({tmp_path.stat().st_size} bytes)..."
    )

    # ── 2. Encolar el trabajo en el OB1 ──
    # ``encolado`` decide el destino del temporal: si el trabajo llega
    # a la cola, lo borra el FB; si no, lo borramos aqui (el FB nunca
    # lo va a leer).
    encolado = False
    try:
        engine = _get_engine()
        if engine is None:
            return jsonify({
                "ok": False,
                "error": "Engine no disponible",
            }), 500

        if engine.get_fb("subir_excel") is None:
            return jsonify({
                "ok": False,
                "error": "FB 'subir_excel' no registrado en el engine",
            }), 500

        try:
            job_id = engine.submit("subir_excel", xlsx_path=str(tmp_path))
        except FBBusyError as exc:
            return jsonify({
                "ok": False,
                "error": (
                    f"FB 'subir_excel' ya tiene un trabajo en curso. "
                    f"Espera a que termine y reintenta. ({exc})"
                ),
            }), 409
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "dispatch: no se pudo encolar la carga del Excel"
            )
            return jsonify({
                "ok": False,
                "error": f"no se pudo encolar el trabajo: {exc}",
            }), 500

        encolado = True
        return jsonify({"ok": True, "job_id": job_id}), 202
    finally:
        # Cleanup del tempfile SOLO si el trabajo no llego a encolarse.
        if not encolado:
            _borrar_temporal(tmp_path)


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Excel).

    Llamado por el ``build_routers`` central del area desde
    ``__init__.py``. Registra el blueprint de este modulo en la
    Flask app.
    """
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_excel' registrado."
    )


__all__ = ["bp", "build_routers"]
