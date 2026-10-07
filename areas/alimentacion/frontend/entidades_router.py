"""Router Flask del feature ENTIDADES: solo el stub de sync (commit D).

El endpoint de preview ``/api/v1/entidades/preview`` vive ahora en
``entidades_preview_router.py`` (commit C, FB Preview real).

Endpoint:
  POST /api/v1/entidades/sincronizar
        Body JSON: ``{plc_name: str}``. ``plc_name`` obligatorio.

        Stub (commit B.0): devuelve "sincronizar_stub". La implementacion
        real (commit D) lanza el FB ``function_entidades_sincronizar`` y
        aplica los cambios en TIA.

Convencion de respuesta:
  - ``200: {"ok": True, "status": "sincronizar_stub", ...}``
  - ``400: {"ok": False, "error": "<motivo>"}`` (body invalido).
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request


logger = logging.getLogger(__name__)


bp = Blueprint(
    "area_alimentacion_entidades_sync",
    __name__,
    url_prefix="/api/v1/entidades",
)


_BODY_REQUIRED = ("plc_name",)


def _validate_body(body: dict) -> tuple[dict | None, str | None]:
    """Valida el body y devuelve (kwargs_limpios, error_msg)."""
    for key in _BODY_REQUIRED:
        if key not in body:
            return None, f"falta '{key}' en el body"
    if not isinstance(body["plc_name"], str):
        return None, "plc_name debe ser str"
    return {"plc_name": str(body["plc_name"])}, None


@bp.post("/sincronizar")
def sincronizar():
    """Stub (commit B.0): valida el body y devuelve marcador.

    En commit D se sustituye por la llamada al FB
    ``function_entidades_sincronizar``.
    """
    body = request.get_json(silent=True) or {}
    validated, err = _validate_body(body)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    logger.web(
        "Entidades/sincronizar (stub): plc_name=%s "
        "TODO commit D: implementar sync contra TIA",
        validated["plc_name"],
    )
    return jsonify({
        "ok": True,
        "status": "sincronizar_stub",
        "plc_name": validated["plc_name"],
        "note": "Stub commit B.0. Implementar en commit D (FB Sync entidades).",
    })


def build_routers(app) -> None:
    """Hook ``contributes_routers`` del area (router de Sync entidades)."""
    app.register_blueprint(bp)
    logger.info(
        "area_alimentacion: router 'area_alimentacion_entidades_sync' "
        "registrado."
    )


__all__ = ["bp", "build_routers"]