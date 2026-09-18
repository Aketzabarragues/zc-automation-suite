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

    # ── Tx B sub-steps (sept-2026) ──
    work_dir: Path | None = None
    exports_subdir: Path | None = None
    exports_param_dir: str | None = None
    exports_alm_dir: str | None = None
    apply_preal_map: dict[str, str] = field(default_factory=dict)
    apply_pint_map: dict[str, str] = field(default_factory=dict)
    apply_alm_map: dict[str, str] = field(default_factory=dict)
    tx_b_ops: list[dict[str, Any]] = field(default_factory=list)

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
    """Tx B: orquestador de las 5 fases + dispatch del lote final.

    El lote se ejecuta con ``tia_client.execute_transactional_batch``:
    ``update_proc_comments_db_param`` (PReal + PInt sobre el mismo
    DB) + ``update_proc_comments_db_alm`` (ALM). El worker abre
    ``start_transaction``, itera los sub-comandos, y cierra con
    ``end_transaction``. Si cualquiera falla, rollback atomico.

    Pipeline (sept-2026 - explicito y testeable):

      Phase 1: proc_tx_b_limpiar
                 -> clean del workdir
      Phase 2: proc_tx_b_detectar_eliminar_export
                 -> re-export de PARAM + ALM
      Phase 3: proc_tx_b_detectar_eliminar_read
                 -> leer comentarios actuales (modo degradado si falla)
      Phase 4: proc_tx_b_calcular_apply_maps
                 -> mezclar Excel + "eliminar" (slots con ".")
      Phase 5: proc_tx_b_construir_ops
                 -> componer las 2 OT ops
      Final:   dispatch execute_transactional_batch

    Historico: antes era 1 funcion monolitica con todo inline. Ahora
    cada fase es una funcion publica testeable (sept-2026: el operario
    pidio refactorizar el orden y exponer sub-steps para
    trazabilidad/QA).
    """
    codigo = (
        ctx.slot_map.db_param_name.split("_")[1]
        if "_" in ctx.slot_map.db_param_name
        else ctx.proc_uid
    )
    undo_text = f"Sync comentarios proceso {codigo} ({ctx.plc_name})"

    # Phase 1
    proc_tx_b_limpiar(ctx)

    # Phase 2 + 3: re-export + read current. Modo degradado:
    # si el re-export o la lectura falla, seguimos con
    # current_* vacios (el apply solo aplicara los slots del Excel,
    # sin detectar "eliminar"). El operario lo vera como
    # "renombrar / agregar", no "eliminar".
    try:
        await proc_tx_b_detectar_eliminar_export(ctx)
        current_preal, current_pint, current_alm = (
            await proc_tx_b_detectar_eliminar_read(ctx)
        )
    except Exception as exc:
        logger.warning(
            f"proc_open_transaction: re-lectura de TIA para "
            f"detectar 'eliminar' fallo: {exc!r}. El apply solo "
            f"aplicara los slots del Excel (modo degradado)."
        )
        current_preal, current_pint, current_alm = {}, {}, {}

    # Phase 4: mezclar Excel + eliminar
    proc_tx_b_calcular_apply_maps(ctx, current_preal, current_pint, current_alm)

    # Phase 5 + Final: commit inline + import_block por DB.
    # SIN wrapper intermedio (sept-2026 refactor DRY): el FB
    # llama 6 veces a commit_array_comments directo, una por
    # array del proceso, sobre los archivos ya exportados.
    # Si el export fallo (exports_param_dir None), skip el commit.
    details: list[dict[str, Any]] = []
    operations_executed = 0
    param_modified = False
    alm_modified = False

    if ctx.exports_param_dir is not None:
        preal_apply_int = {int(k): v for k, v in ctx.apply_preal_map.items()}
        pint_apply_int = {int(k): v for k, v in ctx.apply_pint_map.items()}
        # PARAM DB: 6 arrays (PReal + 3 satellites + PInt + 2 satellites).
        param_arrays = [
            ("PReal",                   "UDT"),
            ("PReal_Vis",               "Simple"),
            ("Aux.PReal_ValorAnterior", "Simple"),
            ("PInt",                    "UDT"),
            ("PInt_Vis",                "Simple"),
            ("Aux.PInt_ValorAnterior",  "Simple"),
        ]
        from core.helpers.simatic_sd import commit_array_comments
        from core.infrastructure.tia.tia_export_paths import SdPair
        for array_name, array_type in param_arrays:
            if array_name in ("PReal", "PReal_Vis", "Aux.PReal_ValorAnterior"):
                slot_map = preal_apply_int
            else:
                slot_map = pint_apply_int
            if not slot_map:
                continue
            result = commit_array_comments(
                SdPair(Path(ctx.exports_param_dir), ctx.slot_map.db_param_name).dcl,
                SdPair(Path(ctx.exports_param_dir), ctx.slot_map.db_param_name).res,
                array_name=array_name,
                slot_map=slot_map,
                array_type=array_type,
                write_to_original=True,
            )
            details.append({
                "array": array_name,
                "injected": dict(result.injected),
                "updated": dict(result.updated),
                "removed": list(result.removed),
            })
            operations_executed += 1
            if (len(result.injected) + len(result.updated) + len(result.removed)) > 0:
                param_modified = True

    if ctx.exports_alm_dir is not None:
        alm_apply_int = {int(k): v for k, v in ctx.apply_alm_map.items()}
        # ALM DB: 1 array (sin satellites).
        if alm_apply_int:
            from core.helpers.simatic_sd import commit_array_comments
            from core.infrastructure.tia.tia_export_paths import SdPair
            result = commit_array_comments(
                SdPair(Path(ctx.exports_alm_dir), ctx.slot_map.db_alm_name).dcl,
                SdPair(Path(ctx.exports_alm_dir), ctx.slot_map.db_alm_name).res,
                array_name="ALM",
                slot_map=alm_apply_int,
                array_type="Simple",
                write_to_original=True,
            )
            details.append({
                "array": "ALM",
                "injected": dict(result.injected),
                "updated": dict(result.updated),
                "removed": list(result.removed),
            })
            operations_executed += 1
            if (len(result.injected) + len(result.updated) + len(result.removed)) > 0:
                alm_modified = True

    # Import unico: TIA Portal V21 importa todos los bloques del
    # directorio en una sola operacion atomica (sept-2026 DRY).
    # Antes (Commit 25): 2 ``import_block`` separados (PARAM + ALM) =
    # ~14s cada uno = ~28s. Ahora: 1 solo import_block = ~14s.
    #
    # Sin ``target_folder``: el handler OT legacy advierte que pasar
    # target_folder explicito causa "CommitOnDispose" en TIA V21.
    # Con target_folder="" TIA escanea recursivamente.
    target_folder_param = ctx.config_manager.get_tia_folder_proceso()
    plc_name = (
        ctx.bloques_cache.plc_name if ctx.bloques_cache is not None else ""
    )
    import shutil
    from areas.alimentacion.helpers.build_cache import build_cache

    if (param_modified or alm_modified) and plc_name:
        # Copytree exports -> modified_bloques/<subpath> para
        # ambos DBs. Si PARAM y ALM comparten el mismo subpath raiz,
        # se hacen 2 copytrees (uno por DB).
        proc_ctx = build_cache(root=ctx.build_cache_root).procesos
        modified_root = proc_ctx.modified_bloques

        if param_modified and ctx.exports_param_dir is not None:
            modified_param_dir = (
                str(Path(modified_root) / ctx.slot_map.param_subpath)
                if ctx.slot_map.param_subpath
                else str(modified_root)
            )
            if Path(ctx.exports_param_dir).exists():
                Path(modified_param_dir).mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    ctx.exports_param_dir, modified_param_dir,
                    dirs_exist_ok=True,
                )

        if alm_modified and ctx.exports_alm_dir is not None:
            modified_alm_dir = (
                str(Path(modified_root) / ctx.slot_map.alm_subpath)
                if ctx.slot_map.alm_subpath
                else str(modified_root)
            )
            if Path(ctx.exports_alm_dir).exists():
                Path(modified_alm_dir).mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    ctx.exports_alm_dir, modified_alm_dir,
                    dirs_exist_ok=True,
                )

        # UN SOLO import_block al final: TIA importa todos los
        # .s7dcl del directorio modified_bloques en una sola
        # operacion atomica.
        await dispatch_async(
            ctx.tia_client,
            "import_block",
            {
                "plc_name": plc_name,
                "import_dir": str(modified_root),
                "target_folder": "",  # default: TIA escanea recursivo
            },
            timeout_s=600.0,
        )

    ctx.tx_result = {
        "operations_executed": operations_executed,
        "details": details,
    }


# ===========================================================================
# 4 funciones para el flujo Tx A + compile (sept-2026)
# ===========================================================================

def proc_compute_nmax_ops(ctx: ProcSyncContext) -> None:
    """Calcula las ops de N_MAX via el helper puro
    ``proc_compute_nmax_diff`` y las guarda en ``ctx.nmax_ops``.

    Sept-2026 (fix bug N_MAX diff=0): el helper ahora toma ``proc_uid``
    y ``slot_map`` (no ``app_state``/``config_manager``/``list_nmax_active``),
    porque los N_MAX de proc viven en la tabla del PROCESO
    (``slot_map.table_name``), no en la tabla global de dispositivos.

    Si el helper lanza ``RuntimeError`` (ej. tabla no exportada en
    TIA, porque el operario no ejecuto el preview antes del commit),
    el raise se PROPAGA al FB. El step ``build_slot_maps_commit``
    atrapa en su log "N_MAX diff: X ops a aplicar"; si no llega
    ahi, el FB aborta con nStep=98 y mensaje accionable.

    Args:
        ctx: contexto con deps + ``slot_map`` (ya populado por el
            step ``build_slot_maps_commit``).
    """
    from areas.alimentacion.helpers.build_cache import build_cache
    from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
        proc_compute_nmax_diff,
    )

    if ctx.tags_base is None:
        proc_ctx = build_cache(root=ctx.build_cache_root).procesos
        ctx.tags_base = proc_ctx.preview_variables

    ctx.nmax_ops = proc_compute_nmax_diff(
        ctx.tags_base, ctx.proc_uid, ctx.slot_map,
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
# Tx B: 5 sub-steps del sync de comentarios (sept-2026 - explicit pipeline)
# ===========================================================================
#
# Cada fase es una funcion publica testeable de forma independiente.
# ``proc_open_transaction`` las orquesta en orden y luego hace el
# dispatch final a ``execute_transactional_batch``. Mantiene la misma
# forma de ejecucion que antes; el cambio es solo estructural.
#
# Flujo (5 fases + dispatch):
#   1. proc_tx_b_limpiar                       - clean() del workdir
#   2. proc_tx_b_detectar_eliminar_export      - re-export de los 2 DBs
#   3. proc_tx_b_detectar_eliminar_read        - leer comentarios actuales
#                                                (devuelve current_* en ctx)
#   4. proc_tx_b_calcular_apply_maps           - mezcla Excel + eliminar
#                                                (devuelve apply_* en ctx)
#   5. proc_tx_b_construir_ops                 - componer las 2 OT ops
#   Final: dispatch_async(execute_transactional_batch, ops)


def proc_tx_b_limpiar(ctx: ProcSyncContext) -> None:
    """Fase 1: limpieza del workdir antes del batch.

    Borra ``.build_cache/alimentacion/procesos/{exports,modified}/``
    para que el ``import_block`` no encuentre archivos stale de runs
    anteriores (validado sept-2026: stale = "Import failed because
    object with name X already exists").
    """
    from areas.alimentacion.helpers.build_cache import build_cache

    proc_ctx = build_cache(root=ctx.build_cache_root).procesos
    proc_ctx.clean()
    ctx.work_dir = proc_ctx.modified_bloques
    ctx.exports_subdir = proc_ctx.exports_bloques


async def proc_tx_b_detectar_eliminar_export(ctx: ProcSyncContext) -> None:
    """Fase 2: re-export de los 2 DBs a ``exports/<subpath>/``.

    Exporta PARAM + ALM al snapshot limpio. Si falla, el FB lo
    reporta; el lote se aborta (no hay punto en continuar sin
    estado actual fiable).
    """
    from areas.alimentacion.helpers.build_cache import build_cache

    proc_ctx = build_cache(root=ctx.build_cache_root).procesos
    plc_name = (
        ctx.bloques_cache.plc_name
        if ctx.bloques_cache is not None
        else ""
    )

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
    ctx.exports_param_dir = exports_param_dir
    ctx.exports_alm_dir = exports_alm_dir


async def proc_tx_b_detectar_eliminar_read(
    ctx: ProcSyncContext,
) -> "tuple[dict[int, str | None], dict[int, str | None], dict[int, str | None]]":
    """Fase 3: leer comentarios ``es-ES`` actuales de cada array.

    Usa los archivos exportados en fase 2. Si falla el parseo
    (YAML invalido o .s7dcl ausente), retorna ``({}, {}, {})`` y el
    apply seguira solo con los slots del Excel (modo degradado).

    Sept-2026 DRY: usa ``find_array_slots`` y ``read_current_comments``
    del helper transversal (sin updater viejo ni dataclasses).
    """
    from core.helpers.simatic_sd import (
        find_array_slots,
        read_current_comments,
    )
    from core.infrastructure.tia.tia_export_paths import SdPair

    try:
        # Modo solo-lectura: ``commit_array_comments`` no se llama
        # aqui (eso es Tx B fase 5). Solo leemos el estado actual.
        dcl_param = SdPair(Path(ctx.exports_param_dir), ctx.slot_map.db_param_name).dcl
        res_param = SdPair(Path(ctx.exports_param_dir), ctx.slot_map.db_param_name).res
        dcl_alm = SdPair(Path(ctx.exports_alm_dir), ctx.slot_map.db_alm_name).dcl
        res_alm = SdPair(Path(ctx.exports_alm_dir), ctx.slot_map.db_alm_name).res

        dcl_param_text = dcl_param.read_text(encoding="utf-8-sig") \
            if dcl_param.exists() else ""
        res_param_text = res_param.read_text(encoding="utf-8-sig") \
            if res_param.exists() else ""
        dcl_alm_text = dcl_alm.read_text(encoding="utf-8-sig") \
            if dcl_alm.exists() else ""
        res_alm_text = res_alm.read_text(encoding="utf-8-sig") \
            if res_alm.exists() else ""

        preal_slots = sorted(
            set(ctx.slot_map.preal.keys())
            | find_array_slots(dcl_param_text, "PReal", "UDT")
        )
        pint_slots = sorted(
            set(ctx.slot_map.pint.keys())
            | find_array_slots(dcl_param_text, "PInt", "UDT")
        )
        alm_slots = sorted(
            set(ctx.slot_map.alm.keys())
            | find_array_slots(dcl_alm_text, "ALM", "Simple")
        )
        current_preal = read_current_comments(
            res_param_text, "PReal", preal_slots, dcl_param_text, "UDT",
        )
        current_pint = read_current_comments(
            res_param_text, "PInt", pint_slots, dcl_param_text, "UDT",
        )
        current_alm = read_current_comments(
            res_alm_text, "ALM", alm_slots, dcl_alm_text, "Simple",
        )
    except Exception as exc:
        logger.warning(
            f"proc_tx_b_detectar_eliminar_read: parseo de 'es-ES' "
            f"fallo ({exc!r}). apply solo aplicara slots del Excel "
            f"(modo degradado)."
        )
        return {}, {}, {}

    return current_preal, current_pint, current_alm


def proc_tx_b_calcular_apply_maps(
    ctx: ProcSyncContext,
    current_preal: dict[int, str | None],
    current_pint: dict[int, str | None],
    current_alm: dict[int, str | None],
) -> "tuple[dict[str, str], dict[str, str], dict[str, str]]":
    """Fase 4: mezcla Excel + "eliminar" (``"."``).

    "Eliminar" = slot presente en TIA (current) pero NO en el
    Excel (slot_map). Su comentario se resetea a ``"."``. Asi el
    operario ve "renombrar / agregar / eliminar" en la preview.

    El resultado se guarda en ``ctx.apply_preal_map`` / ``apply_pint_map``
    / ``apply_alm_map`` para que ``proc_tx_b_construir_ops`` lo use.
    """
    def _merge(
        slot_map: dict[int, str],
        current: dict[int, str | None],
    ) -> dict[str, str]:
        # Slots presentes solo en TIA (no en Excel) -> "."
        to_delete = {
            str(slot): "."
            for slot in sorted(set(current.keys()) - set(slot_map.keys()))
            if current.get(slot)
        }
        return {
            **{str(k): v for k, v in slot_map.items()},
            **to_delete,
        }

    preal_apply = _merge(ctx.slot_map.preal, current_preal)
    pint_apply = _merge(ctx.slot_map.pint, current_pint)
    alm_apply = _merge(ctx.slot_map.alm, current_alm)

    ctx.apply_preal_map = preal_apply
    ctx.apply_pint_map = pint_apply
    ctx.apply_alm_map = alm_apply
    return preal_apply, pint_apply, alm_apply


def proc_tx_b_construir_ops(ctx: ProcSyncContext) -> list[dict[str, Any]]:
    """Fase 5: compone las 2 OT ops (PARAM + ALM).

    1 op combinada para PReal + PInt sobre el MISMO DB PARAM
    (evita el bug del doble ``export_block`` que sobreescribia
    el cambio de PReal al re-exportar para PInt).

    ``db_subpath`` es la subcarpeta TIA donde esta el DB (de
    ``DataBloqueCache.blocks[<db>].ruta``). TIA Portal V21
    requiere reimportar en la MISMA ruta donde ya existe el
    bloque, si no, falla con "object with the name already
    exists" (validado 2026-09-07).

    Guarda ``ctx.tx_b_ops`` (alias) y devuelve la lista. El
    caller (``proc_open_transaction``) la pasa tal cual a
    ``dispatch_async(execute_transactional_batch, ...)``.
    """
    target_folder = ctx.config_manager.get_tia_folder_proceso()

    operations: list[dict[str, Any]] = [
        {
            "command": "update_proc_comments_db_param",
            "args": {
                "plc_name": ctx.plc_name,
                "db_name": ctx.slot_map.db_param_name,
                "db_subpath": ctx.slot_map.param_subpath,
                "preal_slot_map": ctx.apply_preal_map,
                "pint_slot_map": ctx.apply_pint_map,
                "work_dir": str(ctx.work_dir),
                "exports_subdir": str(ctx.exports_subdir),
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
                "slot_map": ctx.apply_alm_map,
                "work_dir": str(ctx.work_dir),
                "exports_subdir": str(ctx.exports_subdir),
                "target_folder": target_folder,
            },
        },
    ]
    ctx.tx_b_ops = operations
    return operations


# ===========================================================================
# Internals puras/async (legacy, conservadas para compat con tests)
# ===========================================================================

async def _compute_apply_maps(
    ctx: ProcSyncContext,
) -> "tuple[dict[str, str], dict[str, str], dict[str, str]]":
    """DEPRECATED wrapper. Usar las 4 fases publicas de Tx B en su lugar.

    Conservada para compat con callers / tests legacy. Internamente
    delega en ``proc_tx_b_*``.
    """
    if not hasattr(ctx, "exports_param_dir"):
        await proc_tx_b_detectar_eliminar_export(ctx)
    current_preal, current_pint, current_alm = (
        await proc_tx_b_detectar_eliminar_read(ctx)
    )
    return proc_tx_b_calcular_apply_maps(
        ctx, current_preal, current_pint, current_alm
    )


async def _re_export_current(  # noqa: D401 - legacy shim
    ctx: ProcSyncContext,
) -> "tuple[dict[int, str | None], dict[int, str | None], dict[int, str | None]]":
    """DEPRECATED wrapper. Usar ``proc_tx_b_detectar_eliminar_export`` +
    ``proc_tx_b_detectar_eliminar_read`` en su lugar."""
    await proc_tx_b_detectar_eliminar_export(ctx)
    return await proc_tx_b_detectar_eliminar_read(ctx)


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
    # Sept-2026: Tx B sub-steps publicos
    "proc_tx_b_limpiar",
    "proc_tx_b_detectar_eliminar_export",
    "proc_tx_b_detectar_eliminar_read",
    "proc_tx_b_calcular_apply_maps",
    "proc_tx_b_construir_ops",
    # Constantes
    "TIA_CONSOLIDATION_SLEEP_S",
    # Sept-2026: nuevos steps Tx A + compile
    "proc_compute_nmax_ops",
    "proc_sync_nmax",
    "proc_wait_consolidation",
    "proc_discover_compile_dbs",
    "proc_compile_blocks",
]
