"""Router Flask del endpoint ``POST /api/v1/excel/upload``.

Migrado del use case legacy ``application/use_cases/upload_excel.py``. La logica pura vive en ``helpers/excel/excel_upload.py``;
el FB ``FunctionExcelCargar`` (registrado en el engine como
``subir_excel``) tiene la state machine + tracker; este router solo
orquesta: recibe el archivo, lo escribe a un tempfile, arranca el
FB con ``xlsx_path`` y devuelve el ``result``.

Montado por el shell Flask a traves del hook
``AreaSpec.contributes_routers`` de alimentacion.

Endpoint:
  POST /api/v1/excel/upload     -> multipart/form-data con campo
                                   ``file``. Dispara el FB
                                   ``subir_excel`` y devuelve su
                                   ``result`` cuando termina.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request

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


def _get_fb(name: str):
    return _get_engine().get_fb(name)


@bp.post("/upload")
def upload_excel():
    """Recibe un ``.xlsx`` y dispara el FB ``subir_excel``.

    Bloquea el hilo de Flask hasta que el FB termina (max ~30s,
    ``STEP_TIMEOUT_S`` del FB). Cuando el FB entra en estado
    terminal (``done`` o ``error``), devuelve el ``result``.

    Returns:
        200 con ``{"ok": True, "summary": ..., "total_dispositivos":
        N, "dimensiones": {...}}`` si todo OK.
        400 si falta el archivo, no es .xlsx, o el FB fallo.
        500 si el FB no esta registrado en el engine.
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
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix, prefix="zcupload_"
    ) as tmp:
        file.save(tmp)
        tmp_path = Path(tmp.name)

    logger.info(
        "[area/excel] Recibiendo upload: '%s' (%d bytes)",
        file.filename, tmp_path.stat().st_size,
    )
    # Plan living TRAZABILIDAD_LOGGING §5 (operación 1): 1 web + 1 ok
    # con el resumen completo del Excel. El operario ve en la consola
    # web "Cargando Excel ... -> Excel cargado: N disp + N proc + ...".
    logger.web(
        f"Cargando Excel '{file.filename}' "
        f"({tmp_path.stat().st_size} bytes)..."
    )

    # Cleanup garantizado al final de CUALQUIER camino (normal, FB
    # fallo, timeout, excepcion). ``delete=False`` es necesario porque
    # el archivo se lee fuera del bloque ``with tempfile`` (el FB se
    # ejecuta con el path), pero tenemos que borrarlo manualmente al
    # terminar para no ensuciar el %TEMP% de Windows.
    try:
        # ── 2. Arrancar el FB ──
        fb = _get_fb("subir_excel")
        if fb is None:
            return jsonify({
                "ok": False,
                "error": "FB 'subir_excel' no registrado en el engine",
            }), 500

        started = asyncio.run(fb.start(xlsx_path=str(tmp_path)))
        if not started:
            return jsonify({
                "ok": False,
                "error": "FB 'subir_excel' ya activo o terminal. "
                         "Haz /disconnect y reintenta.",
            }), 409

        # ── 3. Esperar al resultado (poll bloqueante) ──
        # El engine tickea el FB cada 100ms. Esperamos a que entre en
        # estado terminal (done/error), con timeout = STEP_TIMEOUT_S del FB.
        poll_interval_s = 0.05  # 50ms
        import time
        elapsed = 0.0
        fb_step_timeout = getattr(fb, "STEP_TIMEOUT_S", 30.0)
        while not fb.is_terminal() and elapsed < fb_step_timeout:
            time.sleep(poll_interval_s)
            elapsed += poll_interval_s

        # ── 4. Devolver el resultado ──
        if not fb.is_terminal():
            # Timeout: cancelar el FB para no dejarlo colgado.
            fb.cancel("timeout en /api/v1/excel/upload")
            return jsonify({
                "ok": False,
                "error": f"timeout tras {fb_step_timeout:.1f}s sin terminar",
            }), 504

        if fb.nStep == fb.n_error:
            return jsonify({
                "ok": False,
                "error": fb.error_msg or "FB termino en error",
                "nStep": fb.nStep,
            }), 500

        result = fb.result or {"ok": True}
        # OK con resumen completo: dispositivos + software + N_MAX.
        sw = (result.get("software") or {}) if isinstance(result, dict) else {}
        logger.ok(
            f"Excel cargado: {result.get('total_dispositivos', 0)} disp + "
            f"{sw.get('procesos', 0)} proc + "
            f"{sw.get('preal', 0)} preal + "
            f"{sw.get('pint', 0)} pint + "
            f"{sw.get('alarmas', 0)} alm + "
            f"{sw.get('n_max_total', 0)} N_MAX"
        )
        return jsonify(result)
    finally:
        # Cleanup garantizado del tempfile. ``missing_ok=True`` por si
        # ya fue borrado o nunca se llego a crear el archivo fisico.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


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
