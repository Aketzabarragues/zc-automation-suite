"""Bounded Context: Alimentación.

Aporta al core:
  - State extensions (back-compat legacy de AppState).
  - Catálogo de presentación (consumido por /api/v1/catalog).
  - TIA commands del área (registrados por el tia-loop).
  - Frontend manifest (Vue 3 ESM del área).
  - Config defaults del ConfigManager.
  - FunctionBlock Template (``FunctionTemplate``) registrado como
    ``plantilla``: 10 pasos dummy para validar el engine y el
    progress tracker como faceplate SSE. Sirve tambien como
    molde para migrar los FBs reales del area (Fase 2).

Los routers web, los use cases legacy, las tools MCP y los FBs no-
template siguen existiendo en el area pero no se montan en este
momento (Fase 2). El Composition Root (main_supervisor) llama a
``register(engine, ...)`` para activar la plantilla + FBs migrados.
"""
from __future__ import annotations

from areas.alimentacion.helpers.state.install_state_extensions import (
    install as install_state,
)
from areas.alimentacion.data.data_DispCatalog import build_catalog as build_alim_catalog
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
    label="Área de alimentación",
    icon="",
    config_block="alimentacion",
    contributes_routers=build_routers,
    contributes_state_extensions=install_state,
    contributes_config_defaults=install_defaults,
    contributes_catalog=build_alim_catalog,
    contributes_tia_commands=register_tia,
    contributes_frontend_manifest=build_manifest,
)


def register(
    engine,
    *,
    config_manager=None,
    tia_client=None,
    build_cache=None,
    log=None,
    app_state=None,
) -> None:
    """Registra los FBs del area en el engine.

    Llamado desde ``core.launcher.main_supervisor._build_components()``
    tras crear el engine.

    Los kwargs son las deps comunes de la plantilla FB (Zona 0):
      - ``config_manager``: ``ConfigManager`` del departamento activo.
        Obligatorio para FBs que leen hw_types, n_max_catalog, etc.
      - ``tia_client``: ``SyncTIAClient`` del core. Obligatorio para
        FBs que ejecutan comandos contra TIA.
      - ``build_cache``: ``BuildCache`` del area. Obligatorio para FBs
        que exportan a ``.build_cache/<area>/<contexto>/...``.
      - ``log``: ``LogBuffer`` del core. Si es ``None``, se usa el
        Singleton global (vía ``get_log_buffer()``).
      - ``app_state``: ``AppState`` del core. Si es ``None``, se usa
        el Singleton global (vía ``get_app_state()``).

    Si un FB no recibe su dep, cae al Singleton global (mismo patron
    que la plantilla FB). Si un FB NECESITA una dep y se le olvida
    inyectarla, su ``on_start`` o ``run_step`` lanzara ``RuntimeError``.
    """
    from core.runtime.app_state import get_app_state
    from core.runtime.log_buffer import get_log_buffer

    from areas.alimentacion.functions.function_cuatro_pasos import FunctionCuatroPasos
    from areas.alimentacion.functions.function_seis_pasos import FunctionSeisPasos
    from areas.alimentacion.functions.function_template import FunctionTemplate
    from areas.alimentacion.functions.function_SubirExcel import FunctionSubirExcel

    # Defaults a Singleton global (mismo patron que la plantilla FB).
    log = log if log is not None else get_log_buffer()
    app_state = app_state if app_state is not None else get_app_state()

    # Demos (intactos): no necesitan deps externas.
    engine.register_fb("plantilla", FunctionTemplate(nombre="plantilla"))
    engine.register_fb(
        "cuatro_pasos", FunctionCuatroPasos(nombre="cuatro_pasos"),
    )
    engine.register_fb(
        "seis_pasos", FunctionSeisPasos(nombre="seis_pasos"),
    )

    # FBs reales migrados al patron plantilla (A.1+).
    engine.register_fb(
        "subir_excel",
        FunctionSubirExcel(
            nombre="subir_excel",
            config_manager=config_manager,
            log=log,
            app_state=app_state,
        ),
    )


__all__ = [
    "AREA_SPEC",
    "register_tia",
    "build_manifest",
    "register",
]
