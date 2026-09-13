"""Bounded Context: Alimentación.

Aporta al core:
  - State extensions (back-compat legacy de AppState).
  - Catálogo de presentación (consumido por /api/v1/catalog).
  - TIA commands del área (registrados por el tia-loop).
  - Frontend manifest (Vue 3 ESM del área).
  - Config defaults del ConfigManager.
  - FunctionBlock Template (10 pasos x 1s) para validar el engine.

Los routers web, los use cases legacy, las tools MCP y los FBs no-
template siguen existiendo en el area pero no se montan en este
momento (Fase 2). El Composition Root (main_supervisor) llama a
``register(engine)`` para activar el template.
"""
from __future__ import annotations

from areas.alimentacion.application.disp_state_extensions import (
    install as install_state,
)
from areas.alimentacion.domain.disp_catalog import build_catalog as build_alim_catalog
from areas.alimentacion.frontend.manifest import build as build_manifest
from areas.alimentacion.infrastructure.config_defaults import (
    install as install_defaults,
)
from areas.alimentacion.infrastructure.tia.extra_commands import (
    register as register_tia,
)
from core.application.area_registry import AreaSpec
from areas.alimentacion._area_id import AREA_ID  # noqa: E402,F401


AREA_SPEC = AreaSpec(
    id=AREA_ID,
    label="Área de alimentación",
    icon="",
    config_block="alimentacion",
    contributes_state_extensions=install_state,
    contributes_config_defaults=install_defaults,
    contributes_catalog=build_alim_catalog,
    contributes_tia_commands=register_tia,
    contributes_frontend_manifest=build_manifest,
)


def register(engine) -> None:
    """Registra el FunctionBlock Template en el engine.

    Llamado desde launcher.main_supervisor._build_components() tras
    crear el engine. Solo registra el template (dummy con 10 pasos x
    1s); los FBs reales (SubirExcel, ScanPlcBlocks, etc.) se
    reincorporan cuando migren al modelo OB1.
    """
    from areas.alimentacion.functions.function_Template import FunctionTemplate
    engine.register_fb("Template", FunctionTemplate())


__all__ = [
    "AREA_SPEC",
    "register_tia",
    "build_manifest",
    "register",
]
