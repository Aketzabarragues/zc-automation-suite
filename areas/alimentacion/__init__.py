"""Bounded Context: Alimentacion.

Aporta al core:
  - State extensions de AppCache.
  - Catalogo de presentacion (consumido por /api/v1/catalog).
  - TIA commands del area (registrados por el tia-loop).
  - Frontend manifest (Vue 3 ESM del area).
  - Config defaults del ConfigManager.
  - FunctionBlocks del area (registrados en el engine del core).

Los routers web del area se montan: ``contributes_routers`` apunta a
``_build_all_routers``, que el Composition Root invoca al crear la app
Flask. Las tools MCP no existen todavia (el campo
``contributes_mcp_tools`` de ``AreaSpec`` esta declarado pero sin
materializar). El Composition Root (``main_supervisor``) llama a
``register(engine, ...)`` para activar los FBs del area.
"""
from __future__ import annotations

from areas.alimentacion.data.data_disp_catalog import build_catalog as build_alim_catalog
from areas.alimentacion.data.data_proc_catalog import build_software_catalog
from areas.alimentacion.data.data_entidades_catalog import (
    build_entidades_catalog,
)


def _build_alim_catalog_combined(config_manager):
    """Fusiona catalog de dispositivos, software y entidades para el endpoint ``/api/v1/catalog``.

    Las claves del catalog de disp (``device_tabs``, ``nmax``,
    ``model_columns``, ``col_labels``, ``mono_cols``) viven en el
    top-level. Las del catalog de software se prefijan con ``proc_``
    (``proc_model_columns``, etc.) y las de entidades con ``ent_`` para
    no colisionar.
    """
    return {
        **build_alim_catalog(config_manager),
        **build_software_catalog(config_manager),
        **build_entidades_catalog(config_manager),
    }
from areas.alimentacion.frontend.excel_router import (
    build_routers as build_excel_routers,
)
from areas.alimentacion.frontend.disp_preview_router import (
    build_routers as build_disp_preview_routers,
)
from areas.alimentacion.frontend.disp_sync_router import (
    build_routers as build_disp_sync_routers,
)
from areas.alimentacion.frontend.proc_plantillas_router import (
    build_routers as build_proc_plantillas_routers,
)
from areas.alimentacion.frontend.proc_process_crear_router import (
    build_routers as build_proc_process_crear_routers,
)
from areas.alimentacion.frontend.proc_sync_router import (
    build_routers as build_proc_sync_routers,
)
from areas.alimentacion.frontend.entidades_router import (
    build_routers as build_entidades_routers,
)
from areas.alimentacion.frontend.entidades_preview_router import (
    build_routers as build_entidades_preview_routers,
)
from areas.alimentacion.frontend.manifest import build as build_manifest
from areas.alimentacion.helpers.config.config_defaults import (
    install as install_defaults,
)
from core.composition.app_area_registry import AreaSpec
from areas.alimentacion._area_id import AREA_ID  # noqa: E402,F401


def _build_all_routers(app) -> None:
    """Registra TODOS los routers del area en la Flask app.

    Llamado por ``AreaRegistry.for_each("contributes_routers", app=app)``
    desde ``core/web_server/app_flask.create_app``. Llama a los
    ``build_routers`` de cada modulo del frontend en orden.

    Añadir un router nuevo al area:
      1. Crear ``areas/<area>/frontend/<x>_router.py`` con un
         blueprint ``bp`` y un hook ``build_routers(app)``.
      2. Importar aqui y llamar ``<modulo>_routers.build_routers(app)``.
    """
    build_excel_routers(app)
    build_disp_preview_routers(app)
    build_disp_sync_routers(app)
    build_proc_plantillas_routers(app)
    build_proc_process_crear_routers(app)
    build_proc_sync_routers(app)
    build_entidades_preview_routers(app)
    build_entidades_routers(app)


def _contributes_caches(app_cache) -> None:
    """Registra el ``AlimentacionAreaCache`` del area en ``app_cache``.

    Llamado por ``core.launcher.main_supervisor`` al arrancar la app.
    Lazy import del dataclass para evitar ciclos en el discovery.
    """
    from areas.alimentacion.state.area_cache import AlimentacionAreaCache

    app_cache.register_area("alimentacion", AlimentacionAreaCache())


AREA_SPEC = AreaSpec(
    id=AREA_ID,
    label="Área de alimentación",
    icon="",
    config_block="alimentacion",
    contributes_routers=_build_all_routers,
    contributes_config_defaults=install_defaults,
    contributes_catalog=_build_alim_catalog_combined,
    contributes_frontend_manifest=build_manifest,
    contributes_caches=_contributes_caches,
)


def register(
    engine,
    *,
    config_manager=None,
    tia_client=None,
    build_cache=None,
    app_cache=None,
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
      - ``app_cache``: ``AppCache`` del core. Si es ``None``, se usa
        el Singleton global (vía ``get_app_cache()``).

    Los FBs usan ``logger = logging.getLogger(__name__)`` directamente
    (``log=`` ya no se inyecta por constructor).

    Si un FB no recibe su dep, cae al Singleton global (mismo patron
    que la plantilla FB). Si un FB NECESITA una dep y se le olvida
    inyectarla, su ``on_start`` o ``run_step`` lanzara ``RuntimeError``.
    """
    from core.runtime.app_cache import get_app_cache

    from areas.alimentacion.functions.function_excel_cargar import FunctionExcelCargar
    from areas.alimentacion.functions.function_disp_generar_preview import (
        FunctionDispGenerarPreview,
    )
    from areas.alimentacion.functions.function_disp_sincronizar import (
        FunctionDispSincronizar,
    )
    from areas.alimentacion.functions.function_proc_db_generar_preview import (
        FunctionProcDBGenerarPreview,
    )
    from areas.alimentacion.functions.function_proc_db_sincronizar import (
        FunctionProcDBSincronizar,
    )
    from areas.alimentacion.functions.function_proc_crear_generar_preview import (
        FunctionProcCrearGenerarPreview,
    )
    from areas.alimentacion.functions.function_proc_crear_sincronizar import (
        FunctionProcCrearSincronizar,
    )
    from areas.alimentacion.functions.function_entidades_generar_preview import (
        FunctionEntidadesGenerarPreview,
    )

    # Defaults a Singleton global.
    app_cache = app_cache if app_cache is not None else get_app_cache()

    # FBs del area basados en FunctionBase (con steps).
    engine.register_fb(
        "subir_excel",
        FunctionExcelCargar(
            nombre="subir_excel",
            config_manager=config_manager,
            app_cache=app_cache,
        ),
    )

    # FB con I/O contra TIA: preview de dispositivos vs PLC (export
    # bulk + diff read-only). STEP_TIMEOUT_S=60s.
    engine.register_fb(
        "disp_generar_preview",
        FunctionDispGenerarPreview(
            nombre="disp_generar_preview",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
            app_cache=app_cache,
        ),
    )

    # FB con I/O contra TIA: sync transaccional de dispositivos vs PLC.
    # 11 etapas (export, 2 tx, compile, apply comentarios, post_preview).
    # STEP_TIMEOUT_S=600s.
    engine.register_fb(
        "disp_sincronizar",
        FunctionDispSincronizar(
            nombre="disp_sincronizar",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
            app_cache=app_cache,
        ),
    )

    # FBs con I/O contra TIA: preview + sync de comentarios de
    # procesos vs PLC (DB_PARAM + DB_ALM). 6 + 5 etapas.
    # STEP_TIMEOUT_S=180s (preview) y 300s (sync).
    engine.register_fb(
        "proc_db_generar_preview",
        FunctionProcDBGenerarPreview(
            nombre="proc_db_generar_preview",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
            app_cache=app_cache,
        ),
    )
    engine.register_fb(
        "proc_db_sincronizar",
        FunctionProcDBSincronizar(
            nombre="proc_db_sincronizar",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
            app_cache=app_cache,
        ),
    )

    # FBs con I/O mixto (disco local + worker OT): crear un proceso
    # completo desde una plantilla TIA (preview read-only + apply con
    # import + compile). El preview no toca TIA: solo trabaja sobre
    # directorios locales. El apply construye el proceso en disco y
    # despacha el import al worker OT con
    # ``tia_client.submit_and_wait("execute_transactional_batch", ...)``
    # (bloqueante, desde el hilo del dispatcher del OB1), seguido de
    # ``submit_and_wait("compile_plc", ...)``. ``plc_blocks_cache``
    # llega como param de runtime desde el router.
    engine.register_fb(
        "proc_process_crear_preview",
        FunctionProcCrearGenerarPreview(
            nombre="proc_process_crear_preview",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
        ),
    )
    engine.register_fb(
        "proc_process_crear_aplicar",
        FunctionProcCrearSincronizar(
            nombre="proc_process_crear_aplicar",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
        ),
    )

    # FB con I/O contra TIA: preview de entidades vs PLC (export bulk
    # + 2 dispatches al worker OT: 1 export_tables + 1 export_blocks).
    # STEP_TIMEOUT_S=60s.
    engine.register_fb(
        "entidades_generar_preview",
        FunctionEntidadesGenerarPreview(
            nombre="entidades_generar_preview",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
            app_cache=app_cache,
        ),
    )

    # FB con I/O contra TIA: sync transaccional de entidades vs PLC (11
    # stages: exportar + diff + Tx A NMAX online + Tx B constants + compile +
    # Tx C comments + post preview). STEP_TIMEOUT_S=600s.
    from areas.alimentacion.functions.function_entidades_sincronizar import (
        FunctionEntidadesSincronizar,
    )
    engine.register_fb(
        "entidades_sincronizar",
        FunctionEntidadesSincronizar(
            nombre="entidades_sincronizar",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
            app_cache=app_cache,
        ),
    )


__all__ = [
    "AREA_SPEC",
    "build_manifest",
    "register",
]
