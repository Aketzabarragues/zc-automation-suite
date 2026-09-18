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

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from areas.alimentacion.helpers.tia.dispatch_async import dispatch_async


logger = logging.getLogger("zc.areas.alimentacion.proc_sincronizar")

# Sept-2026: misma espera que usa ``disp_Sincronizar.wait_consolidation``
# tras Tx A. TIA necesita consolidar internamente antes de que el
# ``compile_blocks`` vea el resize de los DBs.
TIA_CONSOLIDATION_SLEEP_S: float = 2.0


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

    # ── Resultado de proc_sync_nmax (Tx A: N_MAX online) ──
    tags_base: Path | None = None
    nmax_ops: list[dict[str, Any]] = field(default_factory=list)
    nmax_result: "dict[str, Any] | None" = None

    # ── Resultado de proc_compile_blocks (post-Tx A) ──
    compile_result: "dict[str, Any] | None" = None
    compile_ok: bool = True
    compile_error: str | None = None

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

    # Normalizar return shape del gateway: ``{"ok": bool, "result":
    # {"operations_executed": int, "details": [...]}, "error": str | None}``.
    # Si ``ok=False``, propagamos el error (rollback atomico del worker).
    batch_result = await dispatch_async(
        ctx.tia_client,
        "execute_transactional_batch",
        {
            "operations": operations,
            "undo_text": undo_text,
        },
        timeout_s=300.0,
    )
    if not batch_result.get("ok"):
        raise RuntimeError(
            f"execute_transactional_batch fallo: "
            f"{batch_result.get('error') or '<sin error>'}"
        )
    inner = batch_result.get("result") or {}
    ctx.tx_result = {
        "operations_executed": int(inner.get("operations_executed", 0)),
        "details": inner.get("details") or [],
    }


# ===========================================================================
# 4 funciones para el flujo Tx A + compile (sept-2026)
# ===========================================================================

def proc_compute_nmax_ops(ctx: ProcSyncContext) -> None:
    """Calcula las ops de N_MAX via el helper puro
    ``proc_compute_nmax_diff`` y las guarda en ``ctx.nmax_ops``.

    Si ``ctx.tags_base`` es ``None``, lo resuelve desde
    ``build_cache(area_id='alimentacion').procesos.preview_variables``.
    Si no hay AppState o no hay config, ``ctx.nmax_ops`` queda como
    ``[]`` y el step ``proc_sync_nmax`` aun despachara el handler
    (requisito "sync_nmax incondicional").
    """
    from areas.alimentacion.helpers.build_cache import build_cache
    from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
        proc_compute_nmax_diff,
    )

    if ctx.tags_base is None:
        proc_ctx = build_cache(root=ctx.build_cache_root).procesos
        ctx.tags_base = proc_ctx.preview_variables

    if ctx.app_state is None or ctx.config_manager is None:
        ctx.nmax_ops = []
        return

    ctx.nmax_ops = proc_compute_nmax_diff(
        ctx.tags_base, ctx.config_manager, ctx.app_state
    )


async def proc_sync_nmax(ctx: ProcSyncContext) -> None:
    """Tx A (online): dispatch ``commit_user_constants_online`` con
    ``nmax_ops=ctx.nmax_ops`` y ``rename_ops=[]``.

    El handler ``commit_user_constants_online`` abre/cierra su propia
    tx TIA (sept-2026 fix del rollback silencioso V21 cuando se
    mezclan ``set_property`` con ``import_plc_tags`` en una sola tx).

    INCONDICIONAL (requisito del operario): aunque ``nmax_ops=[]``, se
    despacha el handler igualmente para que el flujo se ejecute
    completo.
    """
    nmax_result = await dispatch_async(
        ctx.tia_client,
        "commit_user_constants_online",
        {
            "plc_name": ctx.plc_name,
            "nmax_ops": ctx.nmax_ops,
            "rename_ops": [],
            "undo_text": f"Sync N_MAX proceso {ctx.proc_uid} ({ctx.plc_name})",
        },
    )
    if not nmax_result.get("ok"):
        raise RuntimeError(
            f"commit_user_constants_online fallo: "
            f"{nmax_result.get('error') or '<sin error>'}"
        )
    ctx.nmax_result = nmax_result.get("result") or {}


async def proc_wait_consolidation(ctx: ProcSyncContext) -> None:
    """Sleep 2s para que TIA consolide internamente tras Tx A.

    Mismo patron que ``disp_Sincronizar.wait_consolidation``.
    Antes del compile, TIA necesita haber aplicado los N_MAX en su
    modelo interno; si no, el resize de los DBs PARAM/ALM no esta
    visible para ``compile_blocks``.
    """
    await asyncio.to_thread(time.sleep, TIA_CONSOLIDATION_SLEEP_S)


def proc_discover_compile_dbs(ctx: ProcSyncContext) -> list[str]:
    """Devuelve los nombres canonicos de DBs a compilar tras Tx A.

    Para proc son los 2 DBs del proceso actual:
      - ``db_param_name`` (PReal + PInt)
      - ``db_alm_name`` (Alarmas)

    Si ``ctx.slot_map`` no esta inicializado aun, retorna ``[]``.
    El FB se asegura de invocar este helper DESPUES de
    ``proc_build_slot_maps_commit``.
    """
    if ctx.slot_map is None:
        return []
    return [ctx.slot_map.db_param_name, ctx.slot_map.db_alm_name]


async def proc_compile_blocks(ctx: ProcSyncContext) -> None:
    """Compila los DBs PARAM + ALM del proceso actual.

    Patron paralelo a ``disp_Sincronizar.compilar_bloques``: dispatch
    de ``compile_blocks`` con ``block_names=[param_db, alm_db]``.
    Timeout 120s para PLCs grandes (la compilacion tras un resize de
    N_MAX puede tardar).

    Si TIA reporta errores parciales, marca ``ctx.compile_ok=False``
    y guarda el mensaje en ``ctx.compile_error`` (el FB lo evalua
    en su post-step).
    """
    block_names = proc_discover_compile_dbs(ctx)
    if not block_names:
        ctx.compile_ok = False
        ctx.compile_error = (
            "proc_discover_compile_dbs retorno []: ctx.slot_map no "
            "inicializado. Fallo previo en build_slot_maps_commit."
        )
        return

    try:
        compile_result = await dispatch_async(
            ctx.tia_client,
            "compile_blocks",
            {"plc_name": ctx.plc_name, "block_names": block_names},
            timeout_s=120.0,
        )
    except Exception as e:
        ctx.compile_ok = False
        ctx.compile_error = f"compile_blocks excepcion: {e!r}"
        return

    if not compile_result.get("ok"):
        ctx.compile_ok = False
        ctx.compile_error = (
            compile_result.get("error") or "compile_blocks fallo"
        )
        return

    ctx.compile_result = compile_result.get("result") or {}
    compiled = (ctx.compile_result or {}).get("compiled", [])
    errors = (ctx.compile_result or {}).get("errors", [])
    any_had_errors = any(c.get("had_errors") for c in compiled)
    if any_had_errors or errors:
        ctx.compile_ok = False
        n_had = sum(1 for c in compiled if c.get("had_errors"))
        n_err = len(errors)
        n_not_found = len((ctx.compile_result or {}).get("not_found", []))
        ctx.compile_error = (
            f"TIA reporta errores de compilacion post-N_MAX: "
            f"{n_had} bloque(s) con errores, "
            f"{n_err} excepcion(es), "
            f"{n_not_found} no encontrado(s). "
            f"Revisa el proyecto en TIA Portal: los DBs pueden haber "
            f"quedado con tamano inconsistente tras el resize."
        )
        logger.warning(
            f"[{ctx.plc_name}] Compilacion parcial proc tras N_MAX: "
            f"{compile_result}"
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

    Exporta a ``exports_bloques/<db_subpath>/`` (NO a ``modified_bloques/``),
    mismo patron que el sync handler ``update_proc_comments_db_param``.
    Esto evita dejar archivos stale en ``modified_bloques/`` (raiz)
    que el ``import_block`` posterior reescaneaba recursivamente y
    marcaba como ``already exists``.

    Flujo completo (con fix 2026-09-17):
      1. ``proc_ctx.clean()`` borra ``exports/`` y ``modified/`` enteras.
      2. ``_re_export_current`` exporta a ``exports/<subpath>/``.
      3. Sync handler ``update_proc_comments_db_param``:
         - re-exporta a ``exports/<subpath>/`` (overwrite),
         - copytree ``exports/<subpath>/`` -> ``modified/<subpath>/``,
         - updater modifica ``modified/<subpath>/DB_NAME.{s7dcl,s7res}``,
         - ``import_block`` escanea ``modified/bloques/`` recursivamente
           y SOLO encuentra ``modified/<subpath>/DB_NAME`` (la raiz
           esta limpia despues de ``clean()``).
    """
    from areas.alimentacion.helpers.build_cache import build_cache
    from areas.alimentacion.helpers.simatic_sd.simatic_sd_proc_comment_updater import (
        ProcCommentUpdater,
    )
    from core.infrastructure.tia.tia_export_paths import SdPair

    proc_ctx = build_cache(root=ctx.build_cache_root).procesos
    plc_name = (
        ctx.bloques_cache.plc_name
        if ctx.bloques_cache is not None
        else ""
    )

    # Resolver la subcarpeta TIA de cada DB. Si la cache no la tiene
    # (fallback legacy), se exporta a la raiz (mismo caso que el
    # sync handler).
    param_subpath = ctx.slot_map.param_subpath or ""
    alm_subpath = ctx.slot_map.alm_subpath or ""

    exports_param_dir = (
        str(proc_ctx.exports_bloques / param_subpath)
        if param_subpath else str(proc_ctx.exports_bloques)
    )
    exports_alm_dir = (
        str(proc_ctx.exports_bloques / alm_subpath)
        if alm_subpath else str(proc_ctx.exports_bloques)
    )

    # 1. Exportar los 2 DBs (secuencial; export_block no es
    # thread-safe a nivel del wrapper .NET).
    await dispatch_async(
        ctx.tia_client,
        "export_block",
        {
            "plc_name": plc_name,
            "block_name": ctx.slot_map.db_param_name,
            "target_dir": exports_param_dir,
        },
        timeout_s=120.0,
    )
    await dispatch_async(
        ctx.tia_client,
        "export_block",
        {
            "plc_name": plc_name,
            "block_name": ctx.slot_map.db_alm_name,
            "target_dir": exports_alm_dir,
        },
        timeout_s=120.0,
    )

    # 2. Leer los comentarios actuales de cada array.
    updater_param = ProcCommentUpdater(
        s7dcl_path=SdPair(Path(exports_param_dir), ctx.slot_map.db_param_name).dcl,
        s7res_path=SdPair(Path(exports_param_dir), ctx.slot_map.db_param_name).res,
        slot_map={},
    )
    updater_alm = ProcCommentUpdater(
        s7dcl_path=SdPair(Path(exports_alm_dir), ctx.slot_map.db_alm_name).dcl,
        s7res_path=SdPair(Path(exports_alm_dir), ctx.slot_map.db_alm_name).res,
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


# Nota: ``dispatch_async`` se importa arriba desde
# ``areas.alimentacion.helpers.tia.dispatch_async``. Antes vivia
# duplicado aqui (4 copias en total: 2 disp + 2 proc); ahora vive
# como helper compartido.


__all__ = [
    "ProcSyncContext",
    "proc_check_state_commit",
    "proc_check_blocks_commit",
    "proc_build_slot_maps_commit",
    "proc_open_transaction",
    "proc_done_summary_commit",
]
