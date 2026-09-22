"""Bounded Context: Alimentación.

Aporta al core:
  - State extensions de AppState.
  - Catálogo de presentación (consumido por /api/v1/catalog).
  - TIA commands del área (registrados por el tia-loop).
  - Frontend manifest (Vue 3 ESM del área).
  - Config defaults del ConfigManager.
  - FunctionBlock Template (``FunctionTemplate``) registrado como
    ``plantilla``: 10 pasos dummy para validar el engine y el
    progress tracker como faceplate SSE. Sirve también como
    molde para migrar los FBs reales del área.

Los routers web, los use cases legacy, las tools MCP y los FBs no-
template siguen existiendo en el área pero no se montan. El
Composition Root (main_supervisor) llama a ``register(engine, ...)``
para activar la plantilla + FBs migrados.
"""
from __future__ import annotations

from areas.alimentacion.data.data_DispCatalog import build_catalog as build_alim_catalog
from areas.alimentacion.frontend.dispositivos_router import (
    build_routers as build_dispositivos_routers,
)
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
from areas.alimentacion.frontend.manifest import build as build_manifest
from areas.alimentacion.helpers.config_defaults import (
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
    build_dispositivos_routers(app)
    build_excel_routers(app)
    build_disp_preview_routers(app)
    build_disp_sync_routers(app)
    build_proc_plantillas_routers(app)
    build_proc_process_crear_routers(app)
    build_proc_sync_routers(app)


AREA_SPEC = AreaSpec(
    id=AREA_ID,
    label="Área de alimentación",
    icon="",
    config_block="alimentacion",
    contributes_routers=_build_all_routers,
    contributes_config_defaults=install_defaults,
    contributes_catalog=build_alim_catalog,
    contributes_frontend_manifest=build_manifest,
)


def register(
    engine,
    *,
    config_manager=None,
    tia_client=None,
    build_cache=None,
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
      - ``app_state``: ``AppState`` del core. Si es ``None``, se usa
        el Singleton global (vía ``get_app_state()``).

    Los FBs usan ``logger = logging.getLogger(__name__)`` directamente
    tras el commit del bridge (``5840a0b``), ya no se inyecta
    ``log=`` por constructor.

    Si un FB no recibe su dep, cae al Singleton global (mismo patron
    que la plantilla FB). Si un FB NECESITA una dep y se le olvida
    inyectarla, su ``on_start`` o ``run_step`` lanzara ``RuntimeError``.
    """
    from core.runtime.app_state import get_app_state

    from areas.alimentacion.functions.function_SubirExcel import FunctionSubirExcel
    from areas.alimentacion.functions.function_DispGenerarPreview import (
        FunctionDispGenerarPreview,
    )
    from areas.alimentacion.functions.function_DispSincronizar import (
        FunctionDispSincronizar,
    )
    from areas.alimentacion.functions.function_ProcGenerarPreview import (
        FunctionProcGenerarPreview,
    )
    from areas.alimentacion.functions.function_ProcSincronizar import (
        FunctionProcSincronizar,
    )
    from areas.alimentacion.functions.function_ProcProcessCrearPreview import (
        FunctionProcProcessCrearPreview,
    )
    from areas.alimentacion.functions.function_ProcProcessCrearAplicar import (
        FunctionProcProcessCrearAplicar,
    )
    from core.composition.plc_function_template import FunctionTemplate

    # Defaults a Singleton global (mismo patron que la plantilla FB).
    app_state = app_state if app_state is not None else get_app_state()

    # Plantilla FB registrada como ``plantilla``: 10 pasos dummy para
    # validar el engine y el progress tracker como faceplate SSE.
    engine.register_fb("plantilla", FunctionTemplate(nombre="plantilla"))

    # FBs reales migrados al patron plantilla (A.1+).
    engine.register_fb(
        "subir_excel",
        FunctionSubirExcel(
            nombre="subir_excel",
            config_manager=config_manager,
            app_state=app_state,
        ),
    )

    # FB con I/O contra TIA: necesita config_manager + tia_client +
    # build_cache (raiz del BuildCache del area) + log + app_state.
    # Hace export + copytree + 6 dispatches al worker OT. Puede
    # tardar varios minutos (STEP_TIMEOUT_S=300s).
    # (Eliminado A.4: FB ``sincronizar_disp_comentarios``. La logica
    # vive ahora en ``disp_Sincronizar.aplicar_comentarios`` stage 10.)
    # engine.register_fb(...) — borrado.

    # FB con I/O contra TIA: preview de dispositivos vs PLC (export
    # bulk + diff read-only). Reemplaza el legacy generar_prevision
    # del use case DispSyncInstancesUseCase. STEP_TIMEOUT_S=60s.
    engine.register_fb(
        "disp_generar_preview",
        FunctionDispGenerarPreview(
            nombre="disp_generar_preview",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
            app_state=app_state,
        ),
    )

    # FB con I/O contra TIA: sync transaccional de dispositivos vs PLC.
    # Reemplaza el legacy ejecutar_transaccion del use case
    # DispSyncInstancesUseCase. 11 etapas (export, 2 tx, compile,
    # apply comentarios, post_preview). STEP_TIMEOUT_S=600s.
    engine.register_fb(
        "disp_sincronizar",
        FunctionDispSincronizar(
            nombre="disp_sincronizar",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
            app_state=app_state,
        ),
    )

    # FBs con I/O contra TIA: preview + sync de comentarios de
    # procesos vs PLC (DB_PARAM + DB_ALM). Reemplazan los 2
    # metodos legacy del use case ProcSyncComentariosUseCase
    # (``generar_prevision`` + ``ejecutar_transaccion``). 6 + 5
    # etapas. STEP_TIMEOUT_S=180s (preview) y 300s (sync).
    # ``bloques_cache`` se resuelve en on_start() desde el
    # singleton TIADataBloqueCache (acceso sync al dict de
    # clase) si el FB se registro sin esa dep.
    engine.register_fb(
        "proc_generar_preview",
        FunctionProcGenerarPreview(
            nombre="proc_generar_preview",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
            app_state=app_state,
        ),
    )
    engine.register_fb(
        "proc_sincronizar",
        FunctionProcSincronizar(
            nombre="proc_sincronizar",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
            app_state=app_state,
        ),
    )

    # FBs con I/O mixto (disco local + worker OT): crear un proceso
    # completo desde una plantilla TIA (preview read-only + apply con
    # import + compile). El helper ``proc_process_generator`` opera
    # sobre directorios locales; los imports los despachan los FBs
    # via ``core.helpers.tia.dispatch_async``. ``plc_blocks_cache``
    # se resuelve en on_start() desde el singleton TIADataBloqueCache.
    engine.register_fb(
        "proc_process_crear_preview",
        FunctionProcProcessCrearPreview(
            nombre="proc_process_crear_preview",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
        ),
    )
    engine.register_fb(
        "proc_process_crear_aplicar",
        FunctionProcProcessCrearAplicar(
            nombre="proc_process_crear_aplicar",
            config_manager=config_manager,
            tia_client=tia_client,
            build_cache=build_cache,
        ),
    )


__all__ = [
    "AREA_SPEC",
    "build_manifest",
    "register",
]
