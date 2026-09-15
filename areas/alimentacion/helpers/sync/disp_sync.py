"""Helper IT: sincronizacion transaccional de dispositivos vs PLC.

Replica la logica completa de
``DispSyncInstancesUseCase.ejecutar_transaccion`` (areas/alimentacion/
application/use_cases/disp_sync_instances.py:336) como funcion
asincrona autocontenida con kwargs explicitos. Las 11 etapas siguen
el orden del legacy:

  1.  export_diff              -> clean modified/ + export 7 tablas.
  2.  compute_diff             -> diff read-only (CPU en to_thread).
  3.  prepare_xml              -> ops NMAX + device_changes para apply.
  4.  tx_a_nmax_renames        -> dispatch ``commit_disp_nmax_renames_online``
                                   (online puro, abre/cierra su tx TIA).
  5.  wait_consolidation       -> sleep 2s para que TIA consolide.
  6.  export_post_tx_a         -> releer XMLs post-Tx A.
  7.  copy_and_edit            -> copytree filtrado + TagTableModifier.
  8.  tx_b_devices             -> dispatch ``commit_disp_devices_offline``
                                   (offline puro, abre/cierra su tx TIA).
  9.  compile_blocks           -> dispatch ``compile_blocks`` (fuera de tx).
  10. apply_comentarios_disp   -> reusa ``apply_disp_comments`` de A.4
                                   (6 dispatches separados por hw_type).
  11. post_preview             -> reusa ``disp_generate_preview`` de A.5
                                   para que la SPA vea "todo en sync".

Output (shape legacy back-compat con la SPA)::

    {
      "success":         True,
      "message":         str,
      "operations":      int,
      "n_max_updates":   int,
      "post_sync_preview": dict | None,
      "compile_ok":      bool,
      "compile_error":   str | None,
      "comments_sync":   dict,
    }

Restricciones arquitectonicas (.clinerules):
  - NO importa ``siemens_tia_scripting``.
  - Toda interaccion con TIA Portal pasa por ``tia_client`` (Singleton
    core, inyectable como kwarg).
  - Sin Singletons dentro del helper; todas las deps inyectadas.
  - Cero rutas hardcodeadas; todo via ConfigManager.
  - El helper NO toca ``progress_tracker``; eso es responsabilidad
    del FB wrapper (``FunctionDispSincronizarDispositivos``).
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from functools import partial
from pathlib import Path
from typing import Any

logger = logging.getLogger("zc.areas.alimentacion.disp_sync")


# Sincronizacion con TIA V21: tras un commit online, TIA tarda ~2s en
# consolidar internamente. Sin esta espera, el re-export post-Tx A puede
# leer XMLs en estado inconsistente y provocar el rollback silencioso.
TIA_CONSOLIDATION_SLEEP_S: float = 2.0


async def disp_sync(
    plc_name: str,
    *,
    tia_client: Any,
    config_manager: Any,
    app_state: Any,
    build_cache_root: Path | None = None,
) -> dict[str, Any]:
    """Ejecuta la sincronizacion transaccional completa (11 etapas).

    Args:
        plc_name: nombre del PLC destino.
        tia_client: cliente TIA (Singleton core o mock).
        config_manager: ``ConfigManager`` del departamento activo.
        app_state: ``AppState`` con los dispositivos cargados del Excel.
        build_cache_root: raiz del ``BuildCache`` del area.

    Returns:
        ``dict`` con shape legacy ``{success, message, operations,
        n_max_updates, post_sync_preview, compile_ok, compile_error,
        comments_sync}``.
    """
    from areas.alimentacion.helpers.build_cache import build_cache
    from areas.alimentacion.helpers.sync.disp_comment_sync import (
        apply_disp_comments,
    )
    from areas.alimentacion.helpers.sync.disp_generate_preview import (
        disp_generate_preview,
    )

    build_cache_root = build_cache_root or (
        Path(os.getcwd()) / ".build_cache"
    )
    disp_ctx = build_cache(root=build_cache_root).dispositivos

    # ── Stage 1: export_diff ──
    # Limpieza: modified/ se borra (modified_variables + modified_bloques)
    # pero exports/ se preserva (snapshot de auditoria pre-commit).
    disp_ctx.clean()
    tags_base = disp_ctx.modified_variables

    selective_tables = _selective_table_names(config_manager)
    await _dispatch_async(
        tia_client,
        "export_plc_tags_xml",
        {
            "plc_name": plc_name,
            "target_dir": str(tags_base),
            "table_names": selective_tables,
        },
    )

    # ── Stage 2: compute_diff ──
    desired_state_per_table = _build_desired_state_from_app(
        app_state, config_manager,
    )
    (
        added_per_table,
        removed_per_table,
        renamed_per_table,
        _base_state_per_table,
    ) = await asyncio.to_thread(
        _compute_diff_readonly_for_sync,
        tags_base, desired_state_per_table,
    )

    # ── Stage 3: prepare_xml ──
    nmax_ops = _compute_nmax_ops_for_apply(
        tags_base, config_manager, app_state,
    )

    # Device changes: lista de {table_name, adds: [...], removes: [...]}.
    device_changes: list[dict[str, Any]] = []
    for table_key in selective_tables:
        if table_key == config_manager.get_global_config_table_name():
            continue  # N_MAX no es device change.
        adds = [
            {"uid": uid, "plc_tag": desired_state_per_table[table_key][uid]}
            for uid in added_per_table.get(table_key, [])
            if uid in desired_state_per_table[table_key]
        ]
        removes = [
            {"uid": uid}
            for uid in removed_per_table.get(table_key, [])
        ]
        if adds or removes:
            device_changes.append({
                "table_name": table_key,
                "adds": adds,
                "removes": removes,
            })

    # ── Stage 4: Tx A (online puro: N_MAX + renames) ──
    if nmax_ops or renamed_per_table:
        nmax_result = await _dispatch_async(
            tia_client,
            "commit_disp_nmax_renames_online",
            {
                "plc_name": plc_name,
                "nmax_ops": nmax_ops,
                "renames": [
                    {
                        "table": uid.split(":", 1)[0],
                        "current_value": uid.split(":", 1)[1],
                        "new_name": new,
                    }
                    for uid, (_old, new) in renamed_per_table.items()
                ],
                "work_dir": str(tags_base),
            },
            timeout_s=120.0,
        )
        if not nmax_result.get("ok"):
            raise RuntimeError(
                f"Tx A (N_MAX renames) fallo: {nmax_result.get('error')}"
            )
    else:
        nmax_result = {
            "success": True,
            "operations_executed": 0,
            "details": [],
        }

    # ── Stage 5: wait_consolidation ──
    await asyncio.to_thread(time.sleep, TIA_CONSOLIDATION_SLEEP_S)

    # ── Stage 6: export_post_tx_a ──
    await _dispatch_async(
        tia_client,
        "export_plc_tags_xml",
        {
            "plc_name": plc_name,
            "target_dir": str(tags_base),
            "table_names": selective_tables,
        },
    )

    # ── Stage 7: copy_and_edit ──
    # Re-edita los XMLs con los nuevos adds/removes post-Tx A.
    await asyncio.to_thread(
        _apply_xml_edits_offline,
        tags_base, device_changes, config_manager,
    )

    # ── Stage 8: Tx B (offline puro: import devices) ──
    if device_changes:
        devices_result = await _dispatch_async(
            tia_client,
            "commit_disp_devices_offline",
            {
                "plc_name": plc_name,
                "device_changes": device_changes,
                "modified_dir": str(tags_base),
                "undo_text": "Sync devices",
            },
            timeout_s=180.0,
        )
        if not devices_result.get("ok"):
            raise RuntimeError(
                f"Tx B (devices offline) fallo: {devices_result.get('error')}"
            )
    else:
        devices_result = {
            "success": True,
            "operations_executed": 0,
            "details": [],
        }

    # Componer el shape legacy que esperan los callers.
    result = {
        "success": True,
        "operations_executed": (
            nmax_result.get("operations_executed", 0)
            + devices_result.get("operations_executed", 0)
        ),
        "details": (
            nmax_result.get("details", [])
            + devices_result.get("details", [])
        ),
    }

    # ── Stage 9: compile_blocks (fuera de tx) ──
    affected_dbs = _get_affected_dbs_for_compile(config_manager)
    compile_ok = True
    compile_error = None
    try:
        compile_result = await _dispatch_async(
            tia_client,
            "compile_blocks",
            {"plc_name": plc_name, "block_names": affected_dbs},
            timeout_s=120.0,
        )
        if not compile_result.get("ok"):
            compile_ok = False
            compile_error = compile_result.get("error", "compile_blocks fallo")
        else:
            data = compile_result.get("result") or {}
            compiled = data.get("compiled", [])
            errors = data.get("errors", [])
            any_had_errors = any(c.get("had_errors") for c in compiled)
            if any_had_errors or errors:
                compile_ok = False
                n_had = sum(1 for c in compiled if c.get("had_errors"))
                n_err = len(errors)
                n_not_found = len(data.get("not_found", []))
                compile_error = (
                    f"TIA reporta errores de compilacion: "
                    f"{n_had} bloque(s) con errores, "
                    f"{n_err} excepcion(es), "
                    f"{n_not_found} no encontrado(s). "
                    f"Revisa el proyecto en TIA Portal: los DBs "
                    f"pueden haber quedado con tamano inconsistente "
                    f"tras el resize de N_MAX."
                )
                logger.warning(
                    f"[{plc_name}] Compilacion parcial con errores "
                    f"(commit ya aplicado): {compile_result}"
                )
            else:
                n_skipped = len(data.get("skipped_unchanged", []))
                logger.info(
                    f"[{plc_name}] Compilacion OK "
                    f"({len(compiled)} compilados, "
                    f"{n_skipped} saltados por consistentes)."
                )
    except Exception as exc:
        compile_ok = False
        compile_error = f"Excepcion durante la compilacion: {exc}"
        logger.warning(
            f"[{plc_name}] Compilacion fallo (commit ya aplicado): {exc}"
        )

    # ── Stage 10: apply_comentarios_disp (reusa helper de A.4) ──
    comments_result = await apply_disp_comments(
        plc_name=plc_name,
        app_state=app_state,
        config_manager=config_manager,
        build_cache_root=build_cache_root,
        tia_client=tia_client,
    )

    # ── Stage 11: post_sync_preview ──
    try:
        post_sync_preview = await disp_generate_preview(
            plc_name=plc_name,
            tia_client=tia_client,
            config_manager=config_manager,
            app_state=app_state,
            build_cache_root=build_cache_root,
        )
    except Exception as exc:
        logger.warning(
            f"[{plc_name}] Post-sync preview fallo "
            f"(commit ya aplicado): {exc}"
        )
        post_sync_preview = None

    return {
        "success": True,
        "message": f"Inyeccion completada. Detalles: {result['details']}",
        "operations": result["operations_executed"],
        "n_max_updates": len(nmax_ops),
        "post_sync_preview": post_sync_preview,
        "compile_ok": compile_ok,
        "compile_error": compile_error,
        "comments_sync": comments_result,
    }


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
    seen: set[str] = set()
    result: list[str] = []
    for hw_type in config_manager.list_hw_types_active():
        tag_table = config_manager.get_tag_table_name(hw_type)
        if tag_table and tag_table not in seen:
            seen.add(tag_table)
            result.append(tag_table)
    nmax_table = config_manager.get_global_config_table_name()
    if nmax_table and nmax_table not in seen:
        seen.add(nmax_table)
        result.append(nmax_table)
    return result


def _build_desired_state_from_app(
    app_state: Any,
    config_manager: Any,
) -> dict[str, dict[str, str]]:
    """Construye ``{tag_table: {uid: plc_tag}}`` desde el AppState."""
    result: dict[str, dict[str, str]] = {}
    for hw in config_manager.list_hw_types_active():
        cfg = config_manager.get_dispositivo_config(hw)
        if cfg is None:
            continue
        # ``DispositivoTIAConfig`` es un dataclass (atributos, NO keys).
        table_name = cfg.tag_table
        attr_name = config_manager.get_app_state_attr_for(hw)
        if attr_name is None:
            continue
        # ``dispositivos_<hw>`` son listas de dataclasses ``DispED/EA/SA/V/M/M_VF``
        # (atributos ``numero`` y ``plc_tag``), no dicts. Iteramos la lista.
        devices = getattr(app_state, attr_name, []) or []
        table_dict: dict[str, str] = {}
        for device in devices:
            numero = int(getattr(device, "numero", 0) or 0)
            plc_tag = str(getattr(device, "plc_tag", "") or "")
            if numero > 0 and plc_tag:
                table_dict[str(numero)] = plc_tag
        if table_dict:
            result[table_name] = table_dict
    return result


def _compute_diff_readonly_for_sync(
    tags_base: Path,
    desired_state_per_table: dict[str, dict[str, str]],
) -> tuple[
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, tuple[str, str]],
    dict[str, dict[str, str]],
]:
    """Calcula el diff de devices en modo read-only (no modifica XML)."""
    from core.infrastructure.tia.tia_export_paths import XmlTarget
    from areas.alimentacion.helpers.xml.disp_tag_table_modifier import (
        TagTableModifier,
    )

    base_state_per_table: dict[str, dict[str, str]] = {}
    for table_key in desired_state_per_table.keys():
        try:
            xml_path = XmlTarget(tags_base, table_key).path
        except FileNotFoundError:
            continue
        modifier = TagTableModifier(xml_path)
        table_constants: dict[str, str] = {}
        for value_str, plc_tag in (
            modifier.read_user_constants_with_uids().items()
        ):
            if value_str and plc_tag:
                table_constants[value_str] = plc_tag
        if table_constants:
            base_state_per_table[table_key] = table_constants

    added_per_table: dict[str, list[str]] = {}
    removed_per_table: dict[str, list[str]] = {}
    renamed_per_table: dict[str, tuple[str, str]] = {}

    for table_key, desired in desired_state_per_table.items():
        base = base_state_per_table.get(table_key, {})
        base_values = set(base.keys())
        desired_values = set(desired.keys())
        added = sorted(desired_values - base_values)
        removed = sorted(base_values - desired_values)
        renamed: dict[str, tuple[str, str]] = {}
        for uid in base_values & desired_values:
            if base[uid] != desired[uid]:
                renamed[f"{table_key}:{uid}"] = (base[uid], desired[uid])
        if added:
            added_per_table[table_key] = added
        if removed:
            removed_per_table[table_key] = removed
        renamed_per_table.update(renamed)

    return (
        added_per_table,
        removed_per_table,
        renamed_per_table,
        base_state_per_table,
    )


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


def _apply_xml_edits_offline(
    tags_base: Path,
    device_changes: list[dict[str, Any]],
    config_manager: Any,
) -> None:
    """Edita los XMLs offline con los adds/removes post-Tx A (Stage 7)."""
    from areas.alimentacion.helpers.xml.disp_tag_table_modifier import (
        TagTableModifier,
    )

    for dc in device_changes:
        table_name = dc["table_name"]
        adds = dc.get("adds", []) or []
        removes = set(dc.get("removes", []) or [])
        tia_folder = _resolve_tia_folder(config_manager, table_name)
        xml_path = tags_base / tia_folder / f"{table_name}.xml"
        if not xml_path.is_file():
            matches = list(tags_base.rglob(f"{table_name}.xml"))
            if matches:
                xml_path = matches[0]
        if xml_path.is_file():
            modifier = TagTableModifier(xml_path)
            modifier.add_user_constants_by_table(table_name, adds)
            modifier.remove_user_constants(removes)
            modifier.regenerate_root_table_id()
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


__all__ = ["disp_sync", "TIA_CONSOLIDATION_SLEEP_S"]
