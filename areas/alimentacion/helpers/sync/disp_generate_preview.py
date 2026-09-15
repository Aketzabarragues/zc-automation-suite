"""Helper IT: genera la prevision (diff completo) de dispositivos vs PLC.

Replica paso a paso la logica del legacy
``DispSyncInstancesUseCase.generar_prevision`` (areas/alimentacion/
application/use_cases/disp_sync_instances.py:119), pero como funcion
asincrona autocontenida con kwargs explicitos:

  1. **N_MAX** (dimensiones): diff por nombre entre
     ``000_Config_Dispositivos.xml`` (TIA) y ``AppState.dimensiones``
     (Excel).
  2. **Devices** (instancias): diff por UID (valor) entre las 6 tablas
     ``2000_Disp_*`` (TIA) y ``AppState.dispositivos_*`` (Excel).
     Detecta agregados, eliminados y renombrados.

Output (shape legacy back-compat con la SPA)::

    {
      "agregados":   [{"uid", "table", "plc_tag"}],
      "eliminados":  [{"uid", "table", "plc_tag"}],
      "renombrados": [{"uid", "table", "actual", "nuevo"}],
      "todos":       [{"table", "type", "uid", "numero", "actual",
                       "nuevo", "status"}],
      "nmax":        {"current", "desired", "todos", "summary"},
      "summary":     {"agregados", "eliminados", "renombrados",
                      "sin_cambios", "total"},
    }

Restricciones arquitectonicas (.clinerules):
  - NO importa ``siemens_tia_scripting``.
  - Toda interaccion con TIA Portal pasa por ``tia_client`` (Singleton
    core, inyectable como kwarg).
  - Sin Singletons dentro del helper; todas las deps inyectadas.
  - Cero rutas hardcodeadas: las tablas PLC y los nombres de carpeta
    se leen del ``ConfigManager``.
  - El helper NO toca ``progress_tracker``; eso es responsabilidad
    del FB wrapper (``FunctionDispGenerarPreview``).
"""
from __future__ import annotations

import asyncio
import logging
import os
from functools import partial
from pathlib import Path
from typing import Any

logger = logging.getLogger("zc.areas.alimentacion.disp_generate_preview")


async def disp_generate_preview(
    plc_name: str,
    *,
    tia_client: Any,
    config_manager: Any,
    app_state: Any,
    build_cache_root: Path | None = None,
) -> dict[str, Any]:
    """Calcula el diff completo (N_MAX + devices) entre TIA y AppState.

    Args:
        plc_name: nombre del PLC destino.
        tia_client: cliente TIA (Singleton core o mock) usado para
            ``export_plc_tags_xml``.
        config_manager: ``ConfigManager`` del departamento activo.
        app_state: ``AppState`` con los dispositivos cargados del Excel.
        build_cache_root: raiz del ``BuildCache`` del area
            (``<cwd>/.build_cache`` por convencion).

    Returns:
        ``dict`` con shape legacy ``{agregados, eliminados, renombrados,
        todos, nmax, summary}``.
    """
    build_cache_root = build_cache_root or (
        Path(os.getcwd()) / ".build_cache"
    )

    # Limpiar preview/ y exportar bulk de 7 tablas selectivas.
    from areas.alimentacion.helpers.build_cache import build_cache

    disp_ctx = build_cache(root=build_cache_root).dispositivos
    disp_ctx.clean_preview()
    tags_base = disp_ctx.preview_variables

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

    # Diff de devices (CPU puro -> to_thread).
    desired_state_per_table = _build_desired_state_from_app(
        app_state, config_manager,
    )
    added_p, removed_p, renamed, base_state_per_table = await asyncio.to_thread(
        _compute_diff_readonly, tags_base, desired_state_per_table,
    )

    # Diff de N_MAX (CPU puro -> to_thread).
    nmax_block = await asyncio.to_thread(
        _extract_nmax_diff,
        tags_base, config_manager, app_state,
    )

    # ── Build response (shape legacy) ──
    agregados: list[dict[str, Any]] = [
        {"uid": uid, "table": tk, "plc_tag": td.get(uid, "")}
        for tk, td in desired_state_per_table.items()
        for uid in added_p.get(tk, []) if uid in td
    ]
    eliminados: list[dict[str, Any]] = [
        {"uid": uid, "table": tk, "plc_tag": tb.get(uid, "")}
        for tk, tb in base_state_per_table.items()
        for uid in removed_p.get(tk, []) if uid in tb
    ]
    renombrados: list[dict[str, Any]] = [
        {
            "uid": uid.split(":", 1)[1] if ":" in uid else uid,
            "table": uid.split(":", 1)[0] if ":" in uid else "",
            "actual": old,
            "nuevo": new,
        }
        for uid, (old, new) in renamed.items()
    ]

    def _type_from_table(table_key: str) -> str:
        """``2000_Disp_ED`` -> ``"ed"``, ``2000_Disp_M_VF`` -> ``"m_vf"``."""
        stem = table_key.split("_Disp_", 1)[-1]
        return stem.lower()

    todos: list[dict[str, Any]] = []
    for table_key, base in base_state_per_table.items():
        type_key = _type_from_table(table_key)
        renamed_for_table: dict[str, str] = {}
        for uid, (_old, new) in renamed.items():
            if uid.startswith(f"{table_key}:"):
                renamed_for_table[uid.split(":", 1)[1]] = new

        removed_uids = set(removed_p.get(table_key, []))

        for uid_str, plc_tag in base.items():
            try:
                numero = int(uid_str)
            except (TypeError, ValueError):
                numero = 0
            if uid_str in renamed_for_table:
                todos.append({
                    "table": table_key,
                    "type": type_key,
                    "uid": uid_str,
                    "numero": numero,
                    "actual": plc_tag,
                    "nuevo": renamed_for_table[uid_str],
                    "status": "renombrar",
                })
            elif uid_str in removed_uids:
                todos.append({
                    "table": table_key,
                    "type": type_key,
                    "uid": uid_str,
                    "numero": numero,
                    "actual": plc_tag,
                    "nuevo": None,
                    "status": "eliminar",
                })
            else:
                todos.append({
                    "table": table_key,
                    "type": type_key,
                    "uid": uid_str,
                    "numero": numero,
                    "actual": plc_tag,
                    "nuevo": plc_tag,
                    "status": "sin_cambios",
                })

    for table_key, desired in desired_state_per_table.items():
        type_key = _type_from_table(table_key)
        for uid_str in added_p.get(table_key, []):
            try:
                numero = int(uid_str)
            except (TypeError, ValueError):
                numero = 0
            todos.append({
                "table": table_key,
                "type": type_key,
                "uid": uid_str,
                "numero": numero,
                "actual": None,
                "nuevo": desired.get(uid_str, ""),
                "status": "agregar",
            })

    todos.sort(
        key=lambda r: (
            r["type"],
            r["numero"] if isinstance(r["numero"], int) else 0,
        )
    )

    return {
        "agregados": agregados,
        "eliminados": eliminados,
        "renombrados": renombrados,
        "todos": todos,
        "nmax": nmax_block,
        "summary": {
            "agregados": len(agregados),
            "eliminados": len(eliminados),
            "renombrados": len(renombrados),
            "sin_cambios": sum(
                1 for r in todos if r["status"] == "sin_cambios"
            ),
            "total": len(todos),
        },
    }


# ===========================================================================
# Helpers internos (privados al modulo)
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
    device_tables = [
        config_manager.get_tag_table_name(hw)
        for hw in config_manager.list_hw_types_active()
        if config_manager.get_tag_table_name(hw) is not None
    ]
    return [nmax_table, *device_tables]


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
        devices = getattr(app_state, attr_name, {}) or {}
        result[table_name] = {
            str(uid): plc_tag for uid, plc_tag in devices.items()
        }
    return result


def _extract_nmax_diff(
    tags_base: Path,
    config_manager: Any,
    app_state: Any,
) -> dict[str, Any]:
    """Calcula el diff de N_MAX entre el TIA (export bulk) y AppState.

    Las N_MAX son PlcUserConstant de la tabla ``000_Config_Dispositivos``
    que siempre existen en TIA (las 6 dimensiones: ED, EA, SA, V, M,
    M_VF). No se crean ni eliminan: solo se modifica su valor.
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
    else:
        logger.warning(f"[N_MAX] XML esperado no encontrado: {xml_path}")

    d = app_state.dimensiones or {}
    desired: dict[str, int] = {}
    for nmax_name in config_manager.list_nmax_active():
        v = d.get(nmax_name)
        if v is None:
            v = 0
        desired[nmax_name] = int(v)

    todos: list[dict[str, Any]] = []
    for name in desired.keys():
        cur_val = current.get(name)
        des_val = desired[name]
        if cur_val is not None and cur_val == des_val:
            status = "sin_cambios"
        else:
            status = "actualizar"
        todos.append({
            "name": name,
            "actual": cur_val,
            "nuevo": des_val,
            "status": status,
        })

    return {
        "current": current,
        "desired": desired,
        "todos": todos,
        "summary": {
            "actualizar": sum(
                1 for r in todos if r["status"] == "actualizar"
            ),
            "sin_cambios": sum(
                1 for r in todos if r["status"] == "sin_cambios"
            ),
            "total": len(todos),
        },
    }


def _compute_diff_readonly(
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


__all__ = ["disp_generate_preview"]
