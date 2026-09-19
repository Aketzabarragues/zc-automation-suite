"""Helper IT: genera el preview (diff read-only) de dispositivos vs PLC.

Funciones puras independientes. Cada función toma un
``DispPreviewContext`` por argumento y muta sus campos con el
resultado de su trabajo.

Este módulo **no contiene state machine**. La orquestación de las 4
funciones (orden, dependencias entre etapas, mapeo a steps del FB) vive
exclusivamente en ``areas/alimentacion/functions/
function_DispGenerarPreview.py``. Aqui solo estan las funciones puras
y la forma del estado compartido (``DispPreviewContext``).

Las 4 funciones siguen el orden del legacy:

  1.  ``exportar_tags``   -> clean preview/ + export 7 tablas.
  2.  ``compute_devices`` -> diff read-only devices (CPU en to_thread).
  3.  ``compute_nmax``    -> diff read-only N_MAX (CPU en to_thread).
  4.  ``build_response``  -> shape legacy con ``agregados, eliminados,
                              renombrados, todos, nmax, summary``.

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
  - El helper NO contiene state machine (orden, mapping, dispatch);
    eso vive en el FB.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.helpers.tia import dispatch_async


logger = logging.getLogger("zc.areas.alimentacion.disp_generate_preview")


# ===========================================================================
# Contexto mutable (estado compartido entre las 4 funciones)
# ===========================================================================

@dataclass
class DispPreviewContext:
    """Estado compartido entre las 4 funciones de ``disp_generate_preview``.

    Cada funcion toma un ``DispPreviewContext`` por argumento, lee las
    deps inyectadas y los resultados de funciones previas, y muta los
    campos que representan resultados de su trabajo. El FB
    ``FunctionDispGenerarPreview`` instancia uno y lo reusa entre sus 4
    ticks para que los resultados intermedios esten disponibles para
    las funciones posteriores.
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

    # ── Resultados de compute_devices ──
    desired_state_per_table: dict[str, dict[str, str]] = field(default_factory=dict)
    added_per_table: dict[str, list[str]] = field(default_factory=dict)
    removed_per_table: dict[str, list[str]] = field(default_factory=dict)
    renamed_per_table: dict[str, tuple[str, str]] = field(default_factory=dict)
    base_state_per_table: dict[str, dict[str, str]] = field(default_factory=dict)

    # ── Resultados de compute_nmax ──
    nmax_block: dict[str, Any] = field(default_factory=dict)

    # ── Resultado de build_response (shape legacy final) ──
    result: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# 4 funciones puras (cada una muta ``ctx``; sin state machine aqui)
# ===========================================================================

async def exportar_tags(ctx: DispPreviewContext) -> None:
    """Limpia preview/ y exporta las tablas selectivas al snapshot."""
    from areas.alimentacion.helpers.build_cache import build_cache

    disp_ctx = build_cache(root=ctx.build_cache_root).dispositivos
    disp_ctx.clean_preview()
    ctx.tags_base = disp_ctx.preview_variables
    ctx.selective_tables = _selective_table_names(ctx.config_manager)
    logger.debug(f"workdir (preview): {ctx.tags_base}")
    await dispatch_async(
        ctx.tia_client,
        "export_plc_tags_xml",
        {
            "plc_name": ctx.plc_name,
            "target_dir": str(ctx.tags_base),
            "table_names": ctx.selective_tables,
        },
    )


async def compute_devices(ctx: DispPreviewContext) -> None:
    """Calcula el diff de devices entre los XMLs exportados y AppState."""
    assert ctx.tags_base is not None, (
        "compute_devices requiere exportar_tags previo"
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
        _compute_diff_readonly, ctx.tags_base, ctx.desired_state_per_table,
    )


async def compute_nmax(ctx: DispPreviewContext) -> None:
    """Calcula el diff de N_MAX entre el TIA (export bulk) y AppState."""
    assert ctx.tags_base is not None, (
        "compute_nmax requiere exportar_tags previo"
    )
    ctx.nmax_block = await asyncio.to_thread(
        _extract_nmax_diff,
        ctx.tags_base, ctx.config_manager, ctx.app_state,
    )


async def build_response(ctx: DispPreviewContext) -> None:
    """Compone la shape legacy final con todos los resultados intermedios."""
    agregados: list[dict[str, Any]] = [
        {"uid": uid, "table": tk, "plc_tag": td.get(uid, "")}
        for tk, td in ctx.desired_state_per_table.items()
        for uid in ctx.added_per_table.get(tk, []) if uid in td
    ]
    eliminados: list[dict[str, Any]] = [
        {"uid": uid, "table": tk, "plc_tag": tb.get(uid, "")}
        for tk, tb in ctx.base_state_per_table.items()
        for uid in ctx.removed_per_table.get(tk, []) if uid in tb
    ]
    renombrados: list[dict[str, Any]] = [
        {
            "uid": uid.split(":", 1)[1] if ":" in uid else uid,
            "table": uid.split(":", 1)[0] if ":" in uid else "",
            "actual": old,
            "nuevo": new,
        }
        for uid, (old, new) in ctx.renamed_per_table.items()
    ]

    def _type_from_table(table_key: str) -> str:
        """``2000_Disp_ED`` -> ``"ed"``, ``2000_Disp_M_VF`` -> ``"m_vf"``."""
        stem = table_key.split("_Disp_", 1)[-1]
        return stem.lower()

    todos: list[dict[str, Any]] = []
    for table_key, base in ctx.base_state_per_table.items():
        type_key = _type_from_table(table_key)
        renamed_for_table: dict[str, str] = {}
        for uid, (_old, new) in ctx.renamed_per_table.items():
            if uid.startswith(f"{table_key}:"):
                renamed_for_table[uid.split(":", 1)[1]] = new

        removed_uids = set(ctx.removed_per_table.get(table_key, []))

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

    for table_key, desired in ctx.desired_state_per_table.items():
        type_key = _type_from_table(table_key)
        for uid_str in ctx.added_per_table.get(table_key, []):
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

    ctx.result = {
        "agregados": agregados,
        "eliminados": eliminados,
        "renombrados": renombrados,
        "todos": todos,
        "nmax": ctx.nmax_block,
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

# Nota: ``dispatch_async`` se importa arriba desde
# ``core.helpers.tia.dispatch_async``. Antes vivia
# duplicado aqui (4 copias en total: 2 disp + 2 proc); ahora vive
# como helper compartido para que cualquier modulo del area lo use.


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
        # API generica del AppState (data-driven, no ligada a
        # alimentacion). Tras la limpieza de las state extensions
        # legacy (commit 1513ac1) ya no existen properties
        # ``dispositivos_<hw>``; ``get_devices(hw)`` es la unica fuente
        # de verdad (``set_devices`` lo alimenta al subir el Excel).
        devices = app_state.get_devices(hw) if hasattr(app_state, "get_devices") else []
        table_dict: dict[str, str] = {}
        for device in devices:
            numero = int(getattr(device, "numero", 0) or 0)
            plc_tag = str(getattr(device, "plc_tag", "") or "")
            if numero > 0 and plc_tag:
                table_dict[str(numero)] = plc_tag
        if table_dict:
            result[table_name] = table_dict
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
    from core.helpers.simatic_ml import PlcUserConstantParser

    nmax_folder = config_manager.get_tia_folder_nmax()
    nmax_table = config_manager.get_global_config_table_name()
    xml_path = tags_base / nmax_folder / f"{nmax_table}.xml"

    current: dict[str, int] = {}
    if xml_path.is_file():
        try:
            current = PlcUserConstantParser.parse_user_constants(xml_path)
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
    from core.helpers.simatic_ml import PlcUserConstantModifier

    base_state_per_table: dict[str, dict[str, str]] = {}
    for table_key in desired_state_per_table.keys():
        try:
            xml_path = XmlTarget(tags_base, table_key).path
        except FileNotFoundError:
            continue
        modifier = PlcUserConstantModifier(xml_path)
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


__all__ = [
    "DispPreviewContext",
    # 4 funciones puras (sin state machine, sin orden; eso vive en el FB)
    "exportar_tags",
    "compute_devices",
    "compute_nmax",
    "build_response",
]