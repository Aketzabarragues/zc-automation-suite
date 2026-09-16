"""Helper IT: sincronización transaccional de dispositivos vs PLC.

Funciones puras independientes. Cada función toma un ``DispSyncContext``
por argumento y muta sus campos con el resultado de su trabajo.

Este modulo **no contiene state machine**. La orquestacion de las 11
funciones (orden, dependencias entre etapas, mapeo a steps del FB) vive
exclusivamente en ``areas/alimentacion/functions/
function_DispSincronizar.py``. Aqui solo estan las funciones
puras y la forma del estado compartido (``DispSyncContext``).

Las 11 funciones siguen el orden del legacy:

  1.  ``exportar_tags``           -> clean modified/ + export 7 tablas.
  2.  ``compute_diff``             -> diff read-only (CPU en to_thread).
  3.  ``preparar_ops``              -> ops NMAX + device_changes para apply.
  4.  ``tx_a_nmax_renames``        -> dispatch ``commit_disp_nmax_renames_online``
                                       (online puro, abre/cierra su tx TIA).
  5.  ``wait_consolidation``       -> sleep 2s para que TIA consolide.
  6.  ``exportar_post_tx_a``       -> releer XMLs post-Tx A.
  7.  ``editar_xmls_offline``      -> TagTableModifier sobre los XMLs.
  8.  ``tx_b_devices``             -> dispatch ``commit_disp_devices_offline``
                                       (offline puro, abre/cierra su tx TIA).
  9.  ``compilar_bloques``         -> dispatch ``compile_blocks`` (fuera de tx).
  10. ``aplicar_comentarios``      -> reusa ``apply_disp_comments`` de A.4.
  11. ``post_preview``             -> reusa ``disp_generate_preview`` de A.5
                                       para que la SPA vea "todo en sync".

Restricciones arquitectonicas (.clinerules):
  - NO importa ``siemens_tia_scripting``.
  - Toda interaccion con TIA Portal pasa por ``tia_client`` (Singleton
    core, inyectable como kwarg).
  - Sin Singletons dentro del helper; todas las deps inyectadas.
  - Cero rutas hardcodeadas; todo via ConfigManager.
  - El helper NO toca ``progress_tracker``; eso es responsabilidad
    del FB wrapper (``FunctionDispSincronizar``).
  - El helper NO contiene state machine (orden, mapping, dispatch);
    eso vive en el FB.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any


logger = logging.getLogger("zc.areas.alimentacion.disp_Sincronizar")


# Sincronizacion con TIA V21: tras un commit online, TIA tarda ~2s en
# consolidar internamente. Sin esta espera, el re-export post-Tx A puede
# leer XMLs en estado inconsistente y provocar el rollback silencioso.
TIA_CONSOLIDATION_SLEEP_S: float = 2.0


# ===========================================================================
# Contexto mutable (estado compartido entre las 11 funciones)
# ===========================================================================

@dataclass
class DispSyncContext:
    """Estado compartido entre las 11 funciones de ``disp_Sincronizar``.

    Cada funcion toma un ``DispSyncContext`` por argumento, lee las deps
    inyectadas y los resultados de funciones previas, y muta los campos
    que representan resultados de su trabajo. El FB
    ``FunctionDispSincronizar`` instancia uno y lo reusa
    entre sus 11 ticks para que los resultados intermedios esten
    disponibles para las funciones posteriores.
    """

    # ── Deps inyectadas ──
    plc_name: str
    tia_client: Any
    config_manager: Any
    app_state: Any
    build_cache_root: Path

    # ── Resultados de exportar_tags ──
    tags_base: Path | None = None
    selective_tables: list[str] = field(default_factory=list)

    # ── Resultados de compute_diff ──
    desired_state_per_table: dict[str, dict[str, str]] = field(default_factory=dict)
    added_per_table: dict[str, list[str]] = field(default_factory=dict)
    removed_per_table: dict[str, list[str]] = field(default_factory=dict)
    renamed_per_table: dict[str, tuple[str, str]] = field(default_factory=dict)
    base_state_per_table: dict[str, dict[str, str]] = field(default_factory=dict)

    # ── Resultados de preparar_ops ──
    nmax_ops: list[dict[str, Any]] = field(default_factory=list)
    rename_ops: list[dict[str, Any]] = field(default_factory=list)
    device_changes: list[dict[str, Any]] = field(default_factory=list)

    # ── Resultados de tx_a_nmax_renames ──
    nmax_result: dict[str, Any] = field(default_factory=dict)

    # ── Resultados de tx_b_devices ──
    devices_result: dict[str, Any] = field(default_factory=dict)

    # ── Resultados de compilar_bloques ──
    compile_ok: bool = True
    compile_error: str | None = None

    # ── Resultados de aplicar_comentarios ──
    comments_result: dict[str, Any] = field(default_factory=dict)

    # ── Resultados de post_preview ──
    post_sync_preview: dict[str, Any] | None = None


# ===========================================================================
# 11 funciones puras (cada una muta ``ctx``; sin state machine aqui)
# ===========================================================================

async def exportar_tags(ctx: DispSyncContext) -> None:
    """Limpia modified/ y exporta las tablas selectivas al snapshot."""
    from areas.alimentacion.helpers.build_cache import build_cache

    disp_ctx = build_cache(root=ctx.build_cache_root).dispositivos
    disp_ctx.clean()
    # El snapshot limpio vive en ``exports_variables`` (convencion de 9
    # carpetas). ``modified_variables`` se rellena en ``editar_xmls_offline``
    # via ``shutil.copytree`` filtrado (que excluye ``000_Config_Dispositivos``
    # para no re-importar la N_MAX online en Tx B).
    ctx.tags_base = disp_ctx.exports_variables
    ctx.selective_tables = _selective_table_names(ctx.config_manager)
    await _dispatch_async(
        ctx.tia_client,
        "export_plc_tags_xml",
        {
            "plc_name": ctx.plc_name,
            "target_dir": str(ctx.tags_base),
            "table_names": ctx.selective_tables,
        },
    )


async def compute_diff(ctx: DispSyncContext) -> None:
    """Calcula el diff entre los XMLs exportados y el AppState (read-only)."""
    assert ctx.tags_base is not None, (
        "compute_diff requiere exportar_tags previo"
    )
    from areas.alimentacion.helpers.disp.disp_generate_preview import (
        _build_desired_state_from_app,
        _compute_diff_readonly,
    )
    ctx.desired_state_per_table = _build_desired_state_from_app(
        ctx.app_state, ctx.config_manager,
    )
    (
        ctx.added_per_table,
        ctx.removed_per_table,
        ctx.renamed_per_table,
        ctx.base_state_per_table,
    ) = await asyncio.to_thread(
        _compute_diff_readonly,
        ctx.tags_base, ctx.desired_state_per_table,
    )


async def preparar_ops(ctx: DispSyncContext) -> None:
    """Calcula nmax_ops + rename_ops + device_changes para los handlers."""
    assert ctx.tags_base is not None, (
        "preparar_ops requiere exportar_tags previo"
    )
    ctx.nmax_ops = _compute_nmax_ops_for_apply(
        ctx.tags_base, ctx.config_manager, ctx.app_state,
    )

    # Rename ops (shape legacy: {table_name, current_name, new_name}).
    # Tx A las pasa separadas al handler commit_disp_nmax_renames_online.
    ctx.rename_ops = [
        {
            "table_name": uid.split(":", 1)[0],
            "current_name": old,
            "new_name": new,
        }
        for uid, (old, new) in ctx.renamed_per_table.items()
    ]

    # Device changes: lista de {table_name, tia_folder, adds, removes}.
    # ``tia_folder`` resuelve la subcarpeta donde vive el XML del device
    # dentro de modified/variables (e.g. "PLC_Tags" o ""). Se necesita
    # tanto en ``editar_xmls_offline`` (para encontrar el XML a editar)
    # como en el copytree filtrado (Stage 7).
    ctx.device_changes = []
    nmax_table = ctx.config_manager.get_global_config_table_name()
    for table_key in ctx.selective_tables:
        if table_key == nmax_table:
            continue  # N_MAX no es device change.
        adds = [
            {"uid": uid, "plc_tag": ctx.desired_state_per_table[table_key][uid]}
            for uid in ctx.added_per_table.get(table_key, [])
            if uid in ctx.desired_state_per_table[table_key]
        ]
        # ``removes`` debe ser lista de strings (uids), NO lista de dicts:
        # ``TagTableModifier.remove_user_constants`` espera ``set[str]``.
        # ``adds`` si es lista de dicts (``{"uid", "plc_tag"}``) porque
        # ``add_user_constants_by_table`` los desempaqueta como name+value.
        removes = list(ctx.removed_per_table.get(table_key, []))
        if adds or removes:
            ctx.device_changes.append({
                "table_name": table_key,
                "tia_folder": _resolve_tia_folder(ctx.config_manager, table_key),
                "adds": adds,
                "removes": removes,
            })


async def tx_a_nmax_renames(ctx: DispSyncContext) -> None:
    """Tx A (online puro): dispatch de N_MAX + renames contra TIA."""
    assert ctx.tags_base is not None, (
        "tx_a_nmax_renames requiere exportar_tags previo"
    )
    if ctx.nmax_ops or ctx.rename_ops:
        nmax_result = await _dispatch_async(
            ctx.tia_client,
            "commit_disp_nmax_renames_online",
            {
                "plc_name": ctx.plc_name,
                "nmax_ops": ctx.nmax_ops,
                # Key ``rename_ops`` + items con ``table_name``,
                # ``current_name``, ``new_name``: shape que espera el
                # handler ``commit_disp_nmax_renames_online``. Antes
                # pasabamos ``renames`` con keys ``table`` y
                # ``current_value``: el handler las ignoraba
                # silenciosamente y los renames NUNCA se aplicaban.
                "rename_ops": ctx.rename_ops,
                "undo_text": "Sync N_MAX + renames",
            },
            timeout_s=120.0,
        )
        if not nmax_result.get("ok"):
            raise RuntimeError(
                f"Tx A (N_MAX renames) fallo: {nmax_result.get('error')}"
            )
        ctx.nmax_result = nmax_result
    else:
        ctx.nmax_result = {
            "success": True,
            "operations_executed": 0,
            "details": [],
        }


async def wait_consolidation(ctx: DispSyncContext) -> None:
    """Espera 2s para que TIA consolide internamente tras Tx A."""
    await asyncio.to_thread(time.sleep, TIA_CONSOLIDATION_SLEEP_S)


async def exportar_post_tx_a(ctx: DispSyncContext) -> None:
    """Relee los XMLs de los devices tras Tx A (estado ya consolidado)."""
    assert ctx.tags_base is not None, (
        "exportar_post_tx_a requiere exportar_tags previo"
    )
    # Re-exportar solo las 6 tablas de devices (NO la N_MAX: ya esta
    # consolidada en Tx A). El destino es ``exports_variables``
    # (snapshot limpio), no ``modified_variables``: el copytree de
    # Stage 7 hace la copia filtrada.
    from areas.alimentacion.helpers.build_cache import build_cache
    disp_ctx = build_cache(root=ctx.build_cache_root).dispositivos
    await _dispatch_async(
        ctx.tia_client,
        "export_plc_tags_xml",
        {
            "plc_name": ctx.plc_name,
            "target_dir": str(disp_ctx.exports_variables),
            "table_names": [dc["table_name"] for dc in ctx.device_changes],
        },
    )


async def editar_xmls_offline(ctx: DispSyncContext) -> None:
    """Copia filtrada exports->modified + edita XMLs offline (adds/removes)."""
    assert ctx.tags_base is not None, (
        "editar_xmls_offline requiere exportar_tags previo"
    )
    await asyncio.to_thread(
        _copy_and_edit_offline,
        ctx.build_cache_root, ctx.device_changes,
    )


async def tx_b_devices(ctx: DispSyncContext) -> None:
    """Tx B (offline puro): dispatch de import_plc_tags_xml contra TIA."""
    assert ctx.tags_base is not None, (
        "tx_b_devices requiere exportar_tags previo"
    )
    if ctx.device_changes:
        # NO pasamos ``target_folder`` (TIA Portal V21 escanea
        # ``modified_variables/`` recursivamente: si encuentra la
        # estructura interna del PLC (e.g.
        # ``2000_Dispositivos/2000_Disp_ED.xml``), hace match
        # automatico con su PLC tag interno y dispara UPDATE (no
        # CREATE). Pasar ``target_folder`` con un valor explicito
        # fuer.a el match a una sola carpeta, lo rompe y causa
        # ``CommitOnDispose``. Import a RAIZ con ``target_folder=""``
        # (default del handler) es el camino feliz.
        from areas.alimentacion.helpers.build_cache import build_cache
        disp_ctx = build_cache(root=ctx.build_cache_root).dispositivos
        devices_result = await _dispatch_async(
            ctx.tia_client,
            "commit_disp_devices_offline",
            {
                "plc_name": ctx.plc_name,
                "device_changes": ctx.device_changes,
                "modified_dir": str(disp_ctx.modified_variables),
                "undo_text": "Sync devices",
            },
            timeout_s=180.0,
        )
        if not devices_result.get("ok"):
            raise RuntimeError(
                f"Tx B (devices offline) fallo: {devices_result.get('error')}"
            )
        ctx.devices_result = devices_result
    else:
        ctx.devices_result = {
            "success": True,
            "operations_executed": 0,
            "details": [],
        }


async def compilar_bloques(ctx: DispSyncContext) -> None:
    """Compila los DBs afectados (fuera de tx; el commit ya esta aplicado)."""
    affected_dbs = _get_affected_dbs_for_compile(ctx.config_manager)
    try:
        compile_result = await _dispatch_async(
            ctx.tia_client,
            "compile_blocks",
            {"plc_name": ctx.plc_name, "block_names": affected_dbs},
            timeout_s=120.0,
        )
        if not compile_result.get("ok"):
            ctx.compile_ok = False
            ctx.compile_error = (
                compile_result.get("error", "compile_blocks fallo")
            )
            return
        data = compile_result.get("result") or {}
        compiled = data.get("compiled", [])
        errors = data.get("errors", [])
        any_had_errors = any(c.get("had_errors") for c in compiled)
        if any_had_errors or errors:
            ctx.compile_ok = False
            n_had = sum(1 for c in compiled if c.get("had_errors"))
            n_err = len(errors)
            n_not_found = len(data.get("not_found", []))
            ctx.compile_error = (
                f"TIA reporta errores de compilacion: "
                f"{n_had} bloque(s) con errores, "
                f"{n_err} excepcion(es), "
                f"{n_not_found} no encontrado(s). "
                f"Revisa el proyecto en TIA Portal: los DBs "
                f"pueden haber quedado con tamano inconsistente "
                f"tras el resize de N_MAX."
            )
            logger.warning(
                f"[{ctx.plc_name}] Compilacion parcial con errores "
                f"(commit ya aplicado): {compile_result}"
            )
        else:
            n_skipped = len(data.get("skipped_unchanged", []))
            logger.info(
                f"[{ctx.plc_name}] Compilacion OK "
                f"({len(compiled)} compilados, "
                f"{n_skipped} saltados por consistentes)."
            )
    except Exception as exc:
        ctx.compile_ok = False
        ctx.compile_error = f"Excepcion durante la compilacion: {exc}"
        logger.warning(
            f"[{ctx.plc_name}] Compilacion fallo (commit ya aplicado): {exc}"
        )


async def aplicar_comentarios(ctx: DispSyncContext) -> None:
    """Stage 10 del sync: aplica los comentarios por instancia a los 6 DBs de disp.

    Flujo (replica ``apply_disp_comments`` que vivia en
    ``helpers/sync/disp_comment_sync.py``, borrado al refactorizar A.4
    para consolidarlo aqui):

      1. Validar AppState.
      2. Construir slot_maps (disp_build_slot_maps).
      3. Limpiar modified/bloques/ (defensivo).
      4. Exportar 6 DBs a exports/bloques/ (1 dispatch por DB).
      5. Copytree exports/bloques/ -> modified/bloques/.
      6. Una sola tx transaccional con los 6 imports (atomicidad).
      7. Normalizar return shape en ``ctx.comments_result``.

    Si TIA V21 falla en cualquiera de los 6 imports, rollback atomico.
    """
    from areas.alimentacion.helpers.build_cache import build_cache
    from areas.alimentacion.data.data_DispSlotMap import disp_build_slot_maps

    # ── 1. Validar AppState ──
    if not ctx.app_state.all_devices():
        warning = (
            "AppState esta vacio. Cargue primero el Excel con "
            "POST /api/v1/excel/upload."
        )
        ctx.comments_result = {
            "plc_name": ctx.plc_name,
            "success": True,
            "applied": True,
            "operations_executed": 0,
            "summary": {"disp_dbs_updated": 0, "total_ops": 0},
            "details": [],
            "warnings": [warning],
        }
        return

    # ── 2. Construir slot_maps ──
    slot_maps_data = disp_build_slot_maps(ctx.app_state, ctx.config_manager)
    slot_maps = slot_maps_data.slot_maps
    db_names = slot_maps_data.db_names
    db_array_names = slot_maps_data.db_array_names
    warnings = list(slot_maps_data.warnings)

    target_folder = ctx.config_manager.get_tia_folder_dispositivos()

    # ── 3. Limpiar modified/bloques/ ──
    # Aunque Stage 1 del sync ya limpio modified/, forzamos aqui
    # por idempotencia si este stage se invoca standalone.
    disp_ctx = build_cache(root=ctx.build_cache_root).dispositivos
    modified_bloques = disp_ctx.modified_bloques
    if modified_bloques.exists():
        shutil.rmtree(modified_bloques)
    modified_bloques.mkdir(parents=True, exist_ok=True)
    exports_bloques = disp_ctx.exports_bloques

    # ── 4. Export UNA VEZ de los 6 DBs a exports/bloques/ ──
    for hw_type, db_name in db_names.items():
        await _dispatch_async(
            ctx.tia_client,
            "export_block",
            {
                "plc_name": ctx.plc_name,
                "block_name": db_name,
                "target_dir": str(exports_bloques),
            },
        )

    # ── 5. Copytree exports/bloques/ -> modified/bloques/ ──
    if exports_bloques.exists():
        shutil.copytree(
            str(exports_bloques),
            str(modified_bloques),
            dirs_exist_ok=True,
        )

    # ── 6. Una sola tx con los 6 imports (atomicidad) ──
    operations: list[dict[str, Any]] = []
    for hw_type, db_name in db_names.items():
        slot_map = slot_maps.get(hw_type, {})
        slot_map_str: dict[str, str] = {
            str(slot): text for slot, text in slot_map.items()
        }
        db_array_name = db_array_names.get(hw_type, "")
        operations.append({
            "command": f"update_disp_comments_db_{hw_type}",
            "args": {
                "plc_name": ctx.plc_name,
                "db_name": db_name,
                "db_array_name": db_array_name,
                "slot_map": slot_map_str,
                "work_dir": str(modified_bloques),
                "target_folder": target_folder,
            },
        })

    batch_result = await _dispatch_async(
        ctx.tia_client,
        "execute_transactional_batch",
        {
            "operations": operations,
            "undo_text": "Sync disp comments",
        },
        timeout_s=600.0,
    )

    if not batch_result.get("ok"):
        raise RuntimeError(
            f"aplicar_comentarios: execute_transactional_batch fallo: "
            f"{batch_result.get('error')}"
        )

    # ── 7. Normalizar return shape ──
    inner = batch_result.get("result") or {}
    ops_executed = int(inner.get("operations_executed", 0))
    details = inner.get("details") or []

    ctx.comments_result = {
        "plc_name": ctx.plc_name,
        "success": True,
        "applied": True,
        "operations_executed": ops_executed,
        "summary": {
            "disp_dbs_updated": ops_executed,
            "total_ops": ops_executed,
        },
        "details": details,
        "warnings": warnings,
    }


async def post_preview(ctx: DispSyncContext) -> None:
    """Genera el preview post-sync para que la SPA vea 'todo en sync'.

    Reusa las 4 funciones puras del helper ``disp_generate_preview``
    (sept-2026): ``exportar_tags``, ``compute_devices``, ``compute_nmax``
    y ``build_response``. Crea un ``DispPreviewContext`` independiente
    con las mismas deps que el sync y lo ejecuta en orden. El
    ``build_response`` final popula ``ctx.post_sync_preview`` con la
    shape legacy (agregados, eliminados, renombrados, todos, nmax,
    summary).
    """
    from areas.alimentacion.helpers.disp.disp_generate_preview import (
        DispPreviewContext,
        build_response as pv_build_response,
        compute_devices as pv_compute_devices,
        compute_nmax as pv_compute_nmax,
        exportar_tags as pv_exportar_tags,
    )

    pv_ctx = DispPreviewContext(
        plc_name=ctx.plc_name,
        tia_client=ctx.tia_client,
        config_manager=ctx.config_manager,
        app_state=ctx.app_state,
        build_cache_root=ctx.build_cache_root,
    )

    try:
        await pv_exportar_tags(pv_ctx)
        await pv_compute_devices(pv_ctx)
        await pv_compute_nmax(pv_ctx)
        await pv_build_response(pv_ctx)
        ctx.post_sync_preview = pv_ctx.result
    except Exception as exc:
        logger.warning(
            f"[{ctx.plc_name}] Post-sync preview fallo "
            f"(commit ya aplicado): {exc}"
        )
        ctx.post_sync_preview = None


# ===========================================================================
# Helpers internos privados al modulo
# ===========================================================================

async def _dispatch_async(
    tia_client: Any,
    command: str,
    args: dict[str, Any],
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Envia un comando al worker OT via submit_and_wait + to_thread."""
    dispatch = partial(
        tia_client.submit_and_wait, command, args, timeout_s,
    )
    return await asyncio.to_thread(dispatch)


def _selective_table_names(config_manager: Any) -> list[str]:
    """Lista las tablas que el sync dispositivos toca (data-driven)."""
    nmax_table = config_manager.get_global_config_table_name()
    seen: set[str] = set()
    result: list[str] = []
    for hw_type in config_manager.list_hw_types_active():
        tag_table = config_manager.get_tag_table_name(hw_type)
        if tag_table and tag_table not in seen:
            seen.add(tag_table)
            result.append(tag_table)
    if nmax_table and nmax_table not in seen:
        seen.add(nmax_table)
        result.append(nmax_table)
    return result


def _compute_nmax_ops_for_apply(
    tags_base: Path,
    config_manager: Any,
    app_state: Any,
) -> list[dict[str, Any]]:
    """Calcula la lista de ops N_MAX para el handler online.

    Returns:
        Lista de ``[{"table_name": ..., "constant_name": ...,
        "new_value": int}]`` lista para el dispatch al handler
        ``commit_disp_nmax_renames_online``.
    """
    from areas.alimentacion.helpers.xml.disp_tag_table_parser import (
        SimaticMLTagParser,
    )

    nmax_folder = config_manager.get_tia_folder_nmax()
    nmax_table = config_manager.get_global_config_table_name()
    xml_path = tags_base / nmax_folder / f"{nmax_table}.xml"

    current: dict[str, int] = {}
    if xml_path.is_file():
        try:
            current = SimaticMLTagParser.parse_user_constants(xml_path)
        except Exception as e:
            logger.error(f"[N_MAX] Parse FAIL {xml_path}: {e}")

    d = app_state.dimensiones or {}
    desired: dict[str, int] = {}
    for nmax_name in config_manager.list_nmax_active():
        v = d.get(nmax_name)
        if v is None:
            v = 0
        desired[nmax_name] = int(v)

    ops: list[dict[str, Any]] = []
    for name, des_val in desired.items():
        cur_val = current.get(name)
        if cur_val is None or cur_val == des_val:
            continue
        ops.append({
            "table_name": nmax_table,
            "constant_name": name,
            "new_value": des_val,
        })
    return ops


def _resolve_tia_folder(config_manager: Any, table_key: str) -> str:
    """Resuelve la carpeta TIA donde debe guardarse el XML de ``table_key``."""
    nmax_table = config_manager.get_global_config_table_name()
    if table_key == nmax_table:
        return config_manager.get_tia_folder_nmax()
    return config_manager.get_tia_folder_dispositivos()


def _ignore_non_device_xmls(
    device_table_names: set[str],
) -> "callable":
    """Callable para ``shutil.copytree(ignore=...)``.

    Excluye los XMLs cuyo stem (``"2000_Disp_ED"`` sin ``.xml``) NO
    este en ``device_table_names``. Esto evita que el copytree de
    Stage 7 (``exports/variables/ -> modified/variables/``) copie el
    ``000_Config_Dispositivos.xml`` (tabla N_MAX online-only que NO
    debe llegar al import offline de Tx B). Si la copia lo incluyera,
    Tx B (``import_plc_tags_xml``) lo re-importaria con sus valores
    pre-commit, sobrescribiendo los N_MAX aplicados online en Tx A y
    anulando el fix sept-2026 del rollback silencioso V21.

    ``shutil.copytree`` invoca este callable UNA VEZ POR CADA
    SUBDIRECTORIO del arbol (incluida la raiz). Solo inspeccionamos
    ``files`` (los nombres del directorio actual): la recursion la hace
    ``copytree`` automaticamente. Los no-XMLs se preservan.
    """
    def _ignore(directory: str, files: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in files:
            if name.endswith(".xml"):
                stem = name[:-4]
                if stem not in device_table_names:
                    ignored.add(name)
        return ignored
    return _ignore


def _copy_and_edit_offline(
    build_cache_root: Path,
    device_changes: list[dict[str, Any]],
) -> None:
    """Stage 7 del sync: copytree filtrado exports→modified + edits.

    El copytree con filtro excluye ``000_Config_Dispositivos.xml``
    (tabla N_MAX online-only) para que Tx B no la re-importe y anule
    los N_MAX de Tx A.
    """
    from areas.alimentacion.helpers.build_cache import build_cache
    from areas.alimentacion.helpers.xml.disp_tag_table_modifier import (
        TagTableModifier,
    )

    disp_ctx = build_cache(root=build_cache_root).dispositivos
    device_table_names = {dc["table_name"] for dc in device_changes}

    # 1. Copytree filtrado exports/variables -> modified/variables.
    # El filtro es CRITICO: si copiamos la tabla N_MAX, Tx B la
    # re-importaria con sus valores pre-commit, anulando los N_MAX
    # aplicados online en Tx A.
    if disp_ctx.exports_variables.exists():
        shutil.copytree(
            disp_ctx.exports_variables,
            disp_ctx.modified_variables,
            ignore=_ignore_non_device_xmls(device_table_names),
            dirs_exist_ok=True,
        )

    # 2. Edit offline de cada tabla en modified_variables.
    for dc in device_changes:
        table_name = dc["table_name"]
        tia_folder = dc.get("tia_folder") or ""
        adds = dc.get("adds", []) or []
        removes = set(dc.get("removes", []) or [])
        xml_path = (
            disp_ctx.modified_variables
            / tia_folder
            / f"{table_name}.xml"
        )
        if not xml_path.is_file():
            matches = list(
                disp_ctx.modified_variables.rglob(f"{table_name}.xml")
            )
            if matches:
                xml_path = matches[0]
        if xml_path.is_file():
            modifier = TagTableModifier(xml_path)
            modifier.add_user_constants_by_table(table_name, adds)
            modifier.remove_user_constants(removes)
            # NO llamamos ``modifier.regenerate_root_table_id()``:
            # cambiar el ID del PlcTagTable root de ``0`` a un valor alto
            # hace que TIA Portal V21 interprete el import como CREATE
            # (no UPDATE) y reviente con ``CommitOnDispose`` al intentar
            # commit/rollback. El root debe mantener su ID original.
            if modifier.was_modified():
                modifier.save(xml_path)


def _get_affected_dbs_for_compile(config_manager: Any) -> list[str]:
    """Lista los 6 DBs de dispositivos que necesitan recompilacion."""
    result: list[str] = []
    for hw in config_manager.list_hw_types_active():
        cfg = config_manager.get_dispositivo_config(hw)
        if cfg is None:
            continue
        # Aqui queremos el NOMBRE DEL DB (``cfg.db_name``), no la
        # PlcTagTable (``cfg.tag_table``): la compilacion opera sobre
        # los DBs de array. El legacy DispSyncInstancesUseCase.
        # _get_affected_dbs_for_compile hacia lo mismo via
        # ``config.get_db_name(hw)``.
        result.append(cfg.db_name)
    return result


__all__ = [
    "DispSyncContext",
    "TIA_CONSOLIDATION_SLEEP_S",
    # 11 funciones puras (sin state machine, sin orden; eso vive en el FB)
    "exportar_tags",
    "compute_diff",
    "preparar_ops",
    "tx_a_nmax_renames",
    "wait_consolidation",
    "exportar_post_tx_a",
    "editar_xmls_offline",
    "tx_b_devices",
    "compilar_bloques",
    "aplicar_comentarios",
    "post_preview",
]