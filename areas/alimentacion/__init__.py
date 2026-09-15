"""Bounded Context: AlimentaciÃ³n.

Aporta al core:
  - State extensions (back-compat legacy de AppState).
  - CatÃ¡logo de presentaciÃ³n (consumido por /api/v1/catalog).
  - TIA commands del Ã¡rea (registrados por el tia-loop).
  - Frontend manifest (Vue 3 ESM del Ã¡rea).
  - Config defaults del ConfigManager.
  - FunctionBlock Template (``FunctionTemplate``) registrado como
    ``plantilla``: 10 pasos dummy para validar el engine y el
    progress tracker como faceplate SSE. Sirve tambien como
    molde para migrar los FBs reales del area (Fase 2).

Los routers web, los use cases legacy, las tools MCP y los FBs no-
template siguen existiendo en el area pero no se montan en este
momento (Fase 2). El Composition Root (main_supervisor) llama a
``register(engine)`` para activar la plantilla.
"""
from __future__ import annotations

from areas.alimentacion.helpers.state.install_state_extensions import (
    install as install_state,
)
from areas.alimentacion.domain.disp_catalog import build_catalog as build_alim_catalog
from areas.alimentacion.frontend.dispositivos_router import build_routers
from areas.alimentacion.frontend.manifest import build as build_manifest
from areas.alimentacion.helpers.config_defaults import (
    install as install_defaults,
)
from areas.alimentacion.helpers.tia.extra_commands import (
    register as register_tia,
)
from core.composition.app_area_registry import AreaSpec
from areas.alimentacion._area_id import AREA_ID  # noqa: E402,F401


AREA_SPEC = AreaSpec(
    id=AREA_ID,
    label="Ãrea de alimentaciÃ³n",
    icon="",
    config_block="alimentacion",
    contributes_routers=build_routers,
    contributes_state_extensions=install_state,
    contributes_config_defaults=install_defaults,
    contributes_catalog=build_alim_catalog,
    contributes_tia_commands=register_tia,
    contributes_frontend_manifest=build_manifest,
)


def register(engine) -> None:
    """Registra los FBs del area en el engine.

    Llamado desde ``core.launcher.main_supervisor._build_components()`` tras
    crear el engine. Registra tres FBs para validar el faceplate SSE
    dinamico end-to-end (cada uno con stages ``paso_X`` o ``test_X_Y``):

      - ``plantilla``:  FunctionTemplate (10 pasos dummy, paso_1..paso_10).
      - ``cuatro_pasos``: FunctionCuatroPasos (4 pasos, test_1_1..test_1_4).
      - ``seis_pasos``:   FunctionSeisPasos (6 pasos, test_2_1..test_2_6).

    Cuando se migren los FBs reales del area (Fase 2), este registro
    se sustituye por el ``register_fb(...)`` de cada FB concreto
    (copia de ``FunctionTemplate`` con su logica).
    """
    from areas.alimentacion.functions.function_cuatro_pasos import FunctionCuatroPasos
    from areas.alimentacion.functions.function_seis_pasos import FunctionSeisPasos
    from areas.alimentacion.functions.function_template import FunctionTemplate
    # ``nombre="X"`` para que el ``operation`` del progress_tracker
    # coincida con el key del engine (mismo string en ambos sitios).
    engine.register_fb("plantilla", FunctionTemplate(nombre="plantilla"))
    engine.register_fb(
        "cuatro_pasos", FunctionCuatroPasos(nombre="cuatro_pasos"),
    )
    engine.register_fb(
        "seis_pasos", FunctionSeisPasos(nombre="seis_pasos"),
    )


__all__ = [
    "AREA_SPEC",
    "register_tia",
    "build_manifest",
    "register",
]
