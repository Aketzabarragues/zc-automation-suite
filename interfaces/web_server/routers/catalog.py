"""Flask blueprint para catalog (Fase 4 / paso 4.4.5).

GET /api/v1/catalog -> catalogo de presentacion (device_tabs, nmax, ...).

Fusiona los hooks ``AreaSpec.contributes_catalog`` de cada area
registrada. Shell no conoce areas concretas.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify

from core.application.area_registry import AreaRegistry

bp = Blueprint("catalog", __name__, url_prefix="/api/v1")


@bp.get("/catalog")
def get_catalog():
    """Catalogo de presentacion fusionado de las areas."""
    config_manager = current_app.config["CONFIG_MANAGER"]

    merged: dict[str, Any] = {}
    for spec in AreaRegistry.discover().all():
        if spec.contributes_catalog is None:
            continue
        partial = spec.contributes_catalog(config_manager)
        if isinstance(partial, dict):
            merged.update(partial)
    return jsonify({"ok": True, "catalog": merged})


__all__ = ["bp"]
