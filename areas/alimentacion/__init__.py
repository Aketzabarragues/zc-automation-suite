"""Bounded Context: Alimentación.

Paquete autocontenido que aporta al core:
  - Modelos de dominio (Dispositivo, DispED/EA/SA/V/M/M_VF,
    DimensionesDispositivos) en ``domain/models/dispositivos.py``.
  - Catálogo de presentación del área (``build_catalog``) en
    ``domain/disp_catalog.py``, consumido por ``GET /api/v1/catalog``.
  - Casos de uso de sync de dispositivos y comentarios en
    ``application/use_cases/``.
  - Parser de Excel corporativo en
    ``infrastructure/parsers/alimentacion_excel_parser.py``.
  - Modificadores SimaticML offline de comentarios por instancia y
    registro de MLCs en ``infrastructure/sd/``.
  - 6 comandos transaccionales adicionales al ``COMMAND_REGISTRY``
    del worker OT (``update_disp_comments_db_*``) aportados vía
    ``infrastructure/tia/extra_commands.register``. Cableados a
    ``AREA_SPEC.contributes_tia_commands`` y descubiertos al
    arrancar el worker por ``core.infrastructure.tia.command_loader``.
  - 3 routers web en ``interfaces/web/`` (alimentacion, sync, excel)
    cableados a ``contributes_routers``.
  - 4 tools MCP en ``interfaces/mcp/tools.py`` (sync preview/commit,
    aplicar comentarios, upload excel) cableadas a
    ``contributes_mcp_tools``. Dan paridad con los endpoints web:
    LLM y SPA ejecutan los mismos flujos contra los mismos use cases.
  - Manifest del área para la SPA en ``frontend/manifest.js`` y
    su espejo Python ``frontend/manifest.py`` (URLs strings) en
    ``contributes_frontend_manifest``.
  - Back-compat de las 6 properties legacy en ``AppState`` vía
    ``application/disp_state_extensions.install``.
  - Defaults defensivos del ``ConfigManager`` vía
    ``infrastructure/config_defaults.install``.
  - **Wiring del Engine + 7 FBs + plc_router** vía ``register()``
    (Fase 3, paso DA-005.5). El Composition Root
    (``interfaces/web_server/app.py``) llama a ``register()`` desde
    el ``lifespan`` para activar el runtime de Function Blocks.

Los 7 ``contributes_*`` + ``register()`` cubren todos los extension
points y la activación del runtime. La ``AREA_SPEC`` y ``register``
se mantienen en este mismo archivo (Composition Root del área) para
que añadir/quitar un FB sea 1 edit.
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
from areas.alimentacion.interfaces.mcp.tools import register as register_mcp
from areas.alimentacion.interfaces.web import register_routers
from core.application.area_registry import AreaSpec


# Identificador canónico del área. Re-exportado desde ``_area_id.py``
# (módulo minimal sin imports, evita circular import). Coincide con
# ``AREA_SPEC.id`` y es reutilizado por submódulos del área
# (``infrastructure/build_cache.py``, etc.) que necesitan el id sin
# importar ``AREA_SPEC`` (que arrastra la cadena de imports del registry).
from areas.alimentacion._area_id import AREA_ID  # noqa: E402,F401


AREA_SPEC = AreaSpec(
    id=AREA_ID,
    label="Área de alimentación",
    icon="",
    config_block="alimentacion",
    # ── Implementados en PR 2 ──────────────────────────────────────
    contributes_state_extensions=install_state,
    contributes_config_defaults=install_defaults,
    contributes_catalog=build_alim_catalog,
    # ── Implementado en PR 3 ──────────────────────────────────────
    contributes_tia_commands=register_tia,
    # ── Implementado en PR 4 ──────────────────────────────────────
    contributes_routers=register_routers,
    # ── Implementado en PR 5 (frontend-spa) ────────────────────────
    # Manifest del área para la SPA. Espejo Python de ``manifest.js``
    # (mismo shape, pero con URLs strings en ``loaders`` en vez de
    # ``() => import(...)``). El backend lo serializa a JSON desde el
    # endpoint ``GET /api/v1/areas/<id>/manifest``.
    contributes_frontend_manifest=build_manifest,
    # ── Implementado en PR 6 (backend-api) ────────────────────────
    # 4 tools MCP que dan paridad con los endpoints web del área.
    # Las tools delegan en los mismos use cases que los routers:
    # si cambia un flujo, cambia en un único sitio.
    contributes_mcp_tools=register_mcp,
)


# ── Wiring del Engine + 7 FBs (DA-005.5) ──────────────────────────
# El Composition Root (``interfaces/web_server/app.py::_tia_lifespan``)
# invoca esta función tras construir el ``Engine``. Crea los 7 FBs
# del área con sus dependencias (gateway / config_manager / app_state
# / progress_tracker leídos de ``app.state``) y los registra en el
# engine bajo su nombre canónico (sin prefijo ``Function``).
#
# El ``plc_router`` (la mitad HTTP del wiring: ``POST/GET
# /api/v1/plc/fb/{name}/...``) NO se monta aquí: el shell lo incluye
# en ``create_app`` ANTES del catch-all ``app.mount("/", ...)`` (si se
# monta después, el mount intercepta las requests y devuelve 404).
# Ver ``interfaces/web_server/app.py::create_app``.
#
# Convenciones:
#  * Nombre en el engine: ``<clase>.__name__`` sin el prefijo
#    ``Function`` (ej. ``FunctionSubirExcel`` → ``SubirExcel``).
#    Es el identificador estable que la SPA y el router usan.
#  * Si en el futuro se añade un FB, basta con añadirlo a la lista
#    ``fbs`` de ``register()`` y se registra solo. Sin tocar el resto.
def _fb_engine_name(fb_class: type) -> str:
    """Deriva el nombre del FB en el engine desde el nombre de la clase.

    Quita el prefijo ``Function`` para obtener el nombre canónico
    que la SPA espera en ``/api/v1/plc/fb/{name}/...`` (p. ej.
    ``FunctionSubirExcel`` → ``SubirExcel``).
    """
    name = fb_class.__name__
    return name[len("Function"):] if name.startswith("Function") else name


def register(engine, app) -> None:
    """Cablea los 7 FBs del área en el ``Engine``.

    Llamada desde ``interfaces/web_server/app.py::_tia_lifespan``
    tras crear el ``Engine``. Lee las dependencias (``gateway``,
    ``config_manager``, ``app_state``, ``progress_tracker``) de
    ``app.state`` y construye cada FB con sus deps explícitas.

    NO monta el ``plc_router``: ese router se incluye en
    ``create_app`` del shell, ANTES del catch-all ``app.mount("/")``,
    para que el routing no quede shadowed por el mount estático.

    Args:
        engine: ``core.plc.engine.Engine`` recién creado.
        app:    ``fastapi.FastAPI`` del que se leen las deps de
                ``app.state`` (gateway, config_manager, app_state,
                progress_tracker).
    """
    # Imports diferidos: las FBs importan ``core.models`` y los use
    # cases legacy (que importan ``areas.alimentacion.application.*``).
    # Hacerlo aquí evita que el simple ``import areas.alimentacion``
    # del discovery del AreaRegistry arrastre todo el grafo de
    # dependencias si la app se monta sin lifespan (p. ej. en tests
    # que solo inspeccionan el ``AREA_SPEC``).
    from areas.alimentacion.functions.function_DiffConstants import (
        FunctionDiffConstants,
    )
    from areas.alimentacion.functions.function_GenerarPreview import (
        FunctionGenerarPreview,
    )
    from areas.alimentacion.functions.function_ScanPlcBlocks import (
        FunctionScanPlcBlocks,
    )
    from areas.alimentacion.functions.function_SincronizarDispComentarios import (
        FunctionSincronizarDispComentarios,
    )
    from areas.alimentacion.functions.function_SincronizarDispositivos import (
        FunctionSincronizarDispositivos,
    )
    from areas.alimentacion.functions.function_SincronizarProcesosComentarios import (
        FunctionSincronizarProcesosComentarios,
    )
    from areas.alimentacion.functions.function_SubirExcel import (
        FunctionSubirExcel,
    )

    gateway = app.state.gateway
    config_manager = app.state.config_manager
    app_state = app.state.app_state
    progress_tracker = app.state.progress_tracker

    # 7 FBs (DA-005.5; ver ``_plan/REFACTOR_PLAN.md`` §2.1).
    # El orden es estable: facilita diffs en tests y en logs.
    fbs = [
        FunctionSubirExcel(
            config_manager=config_manager,
            app_state=app_state,
            progress_tracker=progress_tracker,
        ),
        FunctionScanPlcBlocks(
            gateway=gateway,
            progress_tracker=progress_tracker,
        ),
        FunctionGenerarPreview(
            gateway=gateway,
            config_manager=config_manager,
            app_state=app_state,
            progress_tracker=progress_tracker,
        ),
        FunctionSincronizarDispositivos(
            gateway=gateway,
            config_manager=config_manager,
            app_state=app_state,
            progress_tracker=progress_tracker,
        ),
        FunctionSincronizarDispComentarios(
            gateway=gateway,
            config_manager=config_manager,
            app_state=app_state,
            progress_tracker=progress_tracker,
        ),
        FunctionSincronizarProcesosComentarios(
            gateway=gateway,
            config_manager=config_manager,
            app_state=app_state,
            progress_tracker=progress_tracker,
        ),
        FunctionDiffConstants(),
    ]
    for fb in fbs:
        engine.register_fb(_fb_engine_name(type(fb)), fb)


__all__ = [
    "AREA_SPEC",
    "register_tia",
    "register_mcp",
    "build_manifest",
    "register",
]
