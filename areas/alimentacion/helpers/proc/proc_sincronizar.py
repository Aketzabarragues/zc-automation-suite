"""Helper IT: sincroniza los comentarios de un proceso contra TIA
Portal (DB_PARAM + DB_ALM) en UNA sola transaccion COM atomica.

Funciones puras independientes. Cada funcion toma un
``ProcSyncContext`` por argumento y muta sus campos con el
resultado de su trabajo.

Este modulo **no contiene state machine**. La orquestacion de las
funciones (orden, dependencias entre etapas, mapeo a steps del FB)
vive exclusivamente en
``areas/alimentacion/functions/function_ProcSincronizar.py``.
Aqui solo estan las funciones puras y la forma del estado
compartido (``ProcSyncContext``).

Output (shape legacy back-compat con la SPA)::

    {
      "proc_uid":             int,
      "plc_name":             str,
      "success":              True,
      "applied":              True,
      "operations_executed":  int,
      "details":              list[dict],
      "warnings":             list[str],
    }

Politica: el diff se **recalcula desde el AppState** (no se usa la
``prevision`` del body) para evitar race conditions con cambios de
Excel entre el preview y el commit.

Restricciones arquitectonicas (.clinerules):
  - NO importa ``siemens_tia_scripting``.
  - Toda interaccion con TIA Portal pasa por ``tia_client`` (gateway
    asincrono, inyectable como kwarg).
  - Sin Singletons dentro del helper; todas las deps inyectadas.
  - Cero rutas hardcodeadas: rutas y carpetas se leen del
    ``ConfigManager`` y del ``build_cache``.
  - El helper NO toca ``progress_tracker``; eso es responsabilidad
    del FB wrapper (``FunctionProcSincronizar``).
  - El helper NO contiene state machine (orden, mapping, dispatch);
    eso vive en el FB.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


logger = logging.getLogger("zc.areas.alimentacion.proc_sincronizar")


# ===========================================================================
# Contexto mutable (estado compartido entre las funciones del helper)
# ===========================================================================

@dataclass
class ProcSyncContext:
    """Estado compartido entre las funciones de ``proc_sincronizar``.

    Cada funcion toma un ``ProcSyncContext`` por argumento, lee las
    deps inyectadas y los resultados de funciones previas, y muta los
    campos que representan resultados de su trabajo. El FB
    ``FunctionProcSincronizar`` instancia uno y lo reusa entre sus 5
    ticks para que los resultados intermedios esten disponibles para
    las funciones posteriores.
    """

    # ── Deps inyectadas ──
    plc_name: str
    proc_uid: int
    tia_client: Any
    config_manager: Any
    app_state: Any
    build_cache_root: Path
    bloques_cache: Any  # DataBloqueCache o None

    # ── Resultado de proc_check_state_commit ──
    excel_loaded: bool = True

    # ── Resultado de proc_check_blocks_commit ──
    bloques_loaded: bool = True

    # ── Resultado de proc_build_slot_maps_commit ──
    slot_map: Any = None  # DataProcSlotMap o None

    # ── Resultado de proc_open_transaction ──
    tx_result: "dict[str, Any] | None" = None

    # ── Resultado final (shape legacy) ──
    result: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# 5 funciones puras/async (cada una muta ``ctx``; sin state machine aqui)
# ===========================================================================

def proc_check_state_commit(ctx: ProcSyncContext) -> None:
    """Valida que ``AppState.excel_cache`` esta cargado.

    Marca ``ctx.excel_loaded = False`` si no lo esta. El FB
    inspecciona este flag para lanzar ``RuntimeError`` con un
    mensaje accionable antes de delegar al gateway.
    """
    if ctx.app_state is None or ctx.app_state.excel_cache is None:
        ctx.excel_loaded = False
        return
    ctx.excel_loaded = True


def proc_check_blocks_commit(ctx: ProcSyncContext) -> None:
    """Valida que el cache de bloques del PLC esta disponible.

    Marca ``ctx.bloques_loaded = False`` si no lo esta. El FB
    inspecciona este flag para lanzar ``RuntimeError`` con un
    mensaje accionable antes de delegar al gateway.
    """
    ctx.bloques_loaded = ctx.bloques_cache is not None


def proc_build_slot_maps_commit(ctx: ProcSyncContext) -> None:
    """Recalcula slot maps desde ``AppState`` (no usa ``prevision``).

    El FB ya valido ``excel_loaded`` y ``bloques_loaded`` en pasos
    previos; aqui solo llamamos al ``proc_build_slot_maps`` del
    modulo de datos. Si la operacion lanza ``RuntimeError`` (uid
    no existe, PLC sin bloques, etc.), se propaga al FB que
    decide si abortar el commit.
    """
    from areas.alimentacion.data.data_ProcSlotMap import proc_build_slot_maps
    ctx.slot_map = proc_build_slot_maps(
        ctx.app_state, ctx.config_manager, ctx.proc_uid, ctx.bloques_cache
    )


async def proc_open_transaction(ctx: ProcSyncContext) -> None:
    """Compone las 2 OT ops y las envia al gateway en una sola TX.

    El lote se ejecuta con ``tia_client.execute_transactional_batch``:
    ``update_proc_comments_db_param`` (PReal + PInt sobre el mismo
    DB) + ``update_proc_comments_db_alm`` (ALM). El worker abre
    ``start_transaction``, itera los sub-comandos, y cierra con
    ``end_transaction``. Si cualquiera falla, rollback atomico.

    Historico: antes habia 3 ops (``_preal`` + ``_pint`` + ``_alm``).
    Se unificaron ``_preal`` y ``_pint`` en ``_param`` para evitar
    el bug del doble ``export_block`` sobre el mismo DB (el segundo
    export SOBREESCRIBIA el cambio de PReal con el contenido
    ORIGINAL de TIA si TIA rechazaba ese MLC concreto).

    Stages internos:
      1. Limpiar el workdir (``proc_ctx.clean()``) para no dejar
         residuos de runs anteriores.
      2. Re-leer el ``current`` de TIA para detectar slots a
         "eliminar" (en TIA pero no en el Excel). Si el re-export
         falla, seguimos solo con los slots del Excel (modo
         degradado).
      3. Componer ``preal_apply`` / ``pint_apply`` / ``alm_apply``
         mezclando Excel + "eliminar" (reset a ``"."``).
      4. Enviar las 2 ops al gateway.

    Args:
        ctx: contexto con deps + resultados previos.
            Requiere: ``ctx.slot_map`` ya populado y valido
            (``missing_blocks == []``).
    """
    from areas.alimentacion.helpers.build_cache import build_cache

    proc_ctx = build_cache(root=ctx.build_cache_root).procesos
    proc_ctx.clean()
    work_dir = proc_ctx.modified_bloques
    exports_subdir = proc_ctx.exports_bloques
    target_folder = ctx.config_manager.get_tia_folder_proceso()

    codigo = (
        ctx.slot_map.db_param_name.split("_")[1]
        if "_" in ctx.slot_map.db_param_name
        else ctx.proc_uid
    )
    undo_text = f"Sync comentarios proceso {codigo} ({ctx.plc_name})"

    preal_apply, pint_apply, alm_apply = await _compute_apply_maps(ctx)

    operations: list[dict[str, Any]] = [
        # 1 op combinada para PReal + PInt sobre el MISMO DB PARAM.
        # Evita el bug del doble ``export_block`` que SOBREESCRIBIA
        # el cambio de PReal al exportar PInt.
        #
        # ``db_subpath`` es la subcarpeta TIA donde esta el DB
        # (extraida de ``DataBloqueCache.blocks[<db>].ruta``). TIA
        # Portal V21 requiere reimportar en la MISMA ruta donde ya
        # existe el bloque, si no, falla con "object with the name
        # already exists" (validado 2026-09-07). Si la cache no
        # tiene la ruta (``""``), el handler cae al comportamiento
        # legacy (raiz de ``work_dir``).
        #
        # ``work_dir`` apunta a ``modified_bloques`` y
        # ``exports_subdir`` al snapshot limpio (``exports_bloques``).
        # El handler hace 1 export a ``exports_subdir/<db_subpath>``
        # + ``shutil.copytree`` a ``work_dir/<db_subpath>`` y luego
        # el updater modifica la copia.
        {
            "command": "update_proc_comments_db_param",
            "args": {
                "plc_name": ctx.plc_name,
                "db_name": ctx.slot_map.db_param_name,
                "db_subpath": ctx.slot_map.param_subpath,
                "preal_slot_map": preal_apply,
                "pint_slot_map": pint_apply,
                "work_dir": str(work_dir),
                "exports_subdir": str(exports_subdir),
                "target_folder": target_folder,
            },
        },
        {
            "command": "update_proc_comments_db_alm",
            "args": {
                "plc_name": ctx.plc_name,
                "db_name": ctx.slot_map.db_alm_name,
                "db_subpath": ctx.slot_map.alm_subpath,
                "array_name": "ALM",
                "slot_map": alm_apply,
                "work_dir": str(work_dir),
                "exports_subdir": str(exports_subdir),
                "target_folder": target_folder,
            },
        },
    ]

    ctx.tx_result = await ctx.tia_client.execute_transactional_batch(
        operations=operations,
        undo_text=undo_text,
    )


def proc_done_summary_commit(ctx: ProcSyncContext) -> dict[str, Any]:
    """Compone el ``ctx.result`` con el shape legacy de la SPA.

    Inspecciona ``ctx.tx_result`` para extraer el resumen del lote
    (``operations_executed``, ``details``) y los warnings del
    slot_map.

    Args:
        ctx: contexto con todos los pasos previos ejecutados.

    Returns:
        El mismo dict que se asigna a ``ctx.result``.
    """
    tx = ctx.tx_result or {}
    ops_executed = tx.get("operations_executed", 0)
    warnings = ctx.slot_map.warnings if ctx.slot_map else []
    ctx.result = {
        "proc_uid": ctx.proc_uid,
        "plc_name": ctx.plc_name,
        "success": True,
        "applied": True,
        "operations_executed": ops_executed,
        "details": tx.get("details", []),
        "warnings": warnings,
    }
    return ctx.result


# ===========================================================================
# Internals puras/async
# ===========================================================================

async def _compute_apply_maps(
    ctx: ProcSyncContext,
) -> "tuple[dict[str, str], dict[str, str], dict[str, str]]":
    """Compone los slot_maps a aplicar (Excel + "eliminar").

    "Eliminar" = slots que existen en TIA pero NO en el Excel.
    El apply los resetea a ``"."`` (convencion TIA "sin
    comentario"). Si el re-export de TIA falla, seguimos solo con
    los slots del Excel (modo degradado: el operario vera solo
    "renombrar / agregar", no "eliminar").
    """
    preal_to_delete: dict[int, str] = {}
    pint_to_delete: dict[int, str] = {}
    alm_to_delete: dict[int, str] = {}
    try:
        current_preal, current_pint, current_alm = await _re_export_current(ctx)
        if current_preal:
            for slot in sorted(
                set(current_preal.keys()) - set(ctx.slot_map.preal.keys())
            ):
                text = current_preal[slot]
                if text:
                    preal_to_delete[slot] = "."
        if current_pint:
            for slot in sorted(
                set(current_pint.keys()) - set(ctx.slot_map.pint.keys())
            ):
                text = current_pint[slot]
                if text:
                    pint_to_delete[slot] = "."
        if current_alm:
            for slot in sorted(
                set(current_alm.keys()) - set(ctx.slot_map.alm.keys())
            ):
                text = current_alm[slot]
                if text:
                    alm_to_delete[slot] = "."
    except Exception as exc:
        logger.warning(
            f"_compute_apply_maps: re-lectura de TIA para "
            f"detectar 'eliminar' fallo: {exc}. El apply solo "
            f"aplicara los slots del Excel (sin 'eliminar')."
        )

    preal_apply = {
        **{str(k): v for k, v in ctx.slot_map.preal.items()},
        **{str(k): v for k, v in preal_to_delete.items()},
    }
    pint_apply = {
        **{str(k): v for k, v in ctx.slot_map.pint.items()},
        **{str(k): v for k, v in pint_to_delete.items()},
    }
    alm_apply = {
        **{str(k): v for k, v in ctx.slot_map.alm.items()},
        **{str(k): v for k, v in alm_to_delete.items()},
    }
    return preal_apply, pint_apply, alm_apply


async def _re_export_current(
    ctx: ProcSyncContext,
) -> "tuple[dict[int, str | None], dict[int, str | None], dict[int, str | None]]":
    """Re-exporta los 2 DBs del proceso y lee los ``es-ES`` actuales.

    Re-usa la misma logica que ``proc_export_and_diff`` del helper
    de preview, pero escribe a ``modified_bloques`` (en lugar de
    ``preview_bloques``) porque estos son los archivos que el
    updater va a modificar.
    """
    from areas.alimentacion.helpers.build_cache import build_cache
    from areas.alimentacion.helpers.simatic_sd.simatic_sd_proc_comment_updater import (
        ProcCommentUpdater,
    )
    from core.infrastructure.tia.tia_export_paths import SdPair

    work_dir = build_cache(root=ctx.build_cache_root).procesos.modified_bloques
    plc_name = (
        ctx.bloques_cache.plc_name
        if ctx.bloques_cache is not None
        else ""
    )

    # 1. Exportar los 2 DBs (secuencial; export_block no es
    # thread-safe a nivel del wrapper .NET).
    await ctx.tia_client.export_block(
        plc_name=plc_name,
        block_name=ctx.slot_map.db_param_name,
        target_dir=str(work_dir),
    )
    await ctx.tia_client.export_block(
        plc_name=plc_name,
        block_name=ctx.slot_map.db_alm_name,
        target_dir=str(work_dir),
    )

    # 2. Leer los comentarios actuales de cada array.
    updater_param = ProcCommentUpdater(
        s7dcl_path=SdPair(work_dir, ctx.slot_map.db_param_name).dcl,
        s7res_path=SdPair(work_dir, ctx.slot_map.db_param_name).res,
        slot_map={},
    )
    updater_alm = ProcCommentUpdater(
        s7dcl_path=SdPair(work_dir, ctx.slot_map.db_alm_name).dcl,
        s7res_path=SdPair(work_dir, ctx.slot_map.db_alm_name).res,
        slot_map={},
    )

    preal_slots = sorted(
        set(ctx.slot_map.preal.keys()) | updater_param.find_array_slots("PReal")
    )
    pint_slots = sorted(
        set(ctx.slot_map.pint.keys()) | updater_param.find_array_slots("PInt")
    )
    alm_slots = sorted(
        set(ctx.slot_map.alm.keys()) | updater_alm.find_array_slots("ALM")
    )
    return (
        updater_param.read_current_comments(preal_slots, "PReal"),
        updater_param.read_current_comments(pint_slots, "PInt"),
        updater_alm.read_current_comments(alm_slots, "ALM"),
    )


__all__ = [
    "ProcSyncContext",
    "proc_check_state_commit",
    "proc_check_blocks_commit",
    "proc_build_slot_maps_commit",
    "proc_open_transaction",
    "proc_done_summary_commit",
]
