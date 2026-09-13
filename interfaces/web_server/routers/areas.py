"""Flask blueprint para areas (Fase 4 / paso 4.4.8).

Equivalente sync de ``areas.py`` (FastAPI). Endpoint unico:
  GET /api/v1/areas -> lista de areas configuradas.

Delega en ``ListAreasUseCase`` (legacy) para mantener la logica de
descubrimiento intacta.

NOTA: ``ListAreasUseCase`` se resuelve en tiempo de ejecucion via
``import_module(...).ListAreasUseCase`` (no en import time), para que
los tests puedan monkey-patch el simbolo a nivel de modulo sin que
el blueprint siga referenciando la clase original.
"""
from __future__ import annotations

from dataclasses import asdict
from importlib import import_module

from flask import Blueprint, current_app, jsonify

bp = Blueprint("areas", __name__, url_prefix="/api/v1")


@bp.get("/areas")
def list_areas():
    """Lista las areas configuradas."""
    config_manager = current_app.config["CONFIG_MANAGER"]
    # Lookup dinamico para que monkey-patching de tests funcione.
    ar_mod = import_module("core.application.area_registry")
    uc = ar_mod.ListAreasUseCase(config_manager)
    return jsonify([asdict(a) for a in uc.execute()])


__all__ = ["bp"]
