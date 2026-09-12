"""Flask blueprint para manifests frontend de areas (Fase 4 / paso 4.4.4).

Equivalente sync de ``area_manifests.py`` (FastAPI). Endpoint unico:

  GET /api/v1/areas/<area_id>/manifest -> AreaManifest JSON

Itera ``AreaRegistry``, busca el ``AreaSpec`` y, si tiene
``contributes_frontend_manifest``, invoca el callable y devuelve el dict.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from core.application.area_registry import AreaRegistry

bp = Blueprint("area_manifests", __name__, url_prefix="/api/v1/areas")


@bp.get("/<area_id>/manifest")
def get_area_manifest(area_id: str):
    """Manifest frontend del area ``area_id``. 404 si no existe."""
    spec = AreaRegistry.discover().get(area_id)
    if spec is None or spec.contributes_frontend_manifest is None:
        return jsonify({
            "error": (
                f"Area '{area_id}' no encontrada o sin manifest frontend."
            )
        }), 404
    return jsonify(spec.contributes_frontend_manifest())


__all__ = ["bp"]
