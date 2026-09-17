"""Helper IT: genera el preview (diff read-only) de comentarios de un
proceso vs TIA Portal (DB_PARAM + DB_ALM).

Funciones puras independientes. Cada función toma un
``ProcPreviewContext`` por argumento y muta sus campos con el
resultado de su trabajo.

Este módulo **no contiene state machine**. La orquestación de las
funciones (orden, dependencias entre etapas, mapeo a steps del FB)
vive exclusivamente en
``areas/alimentacion/functions/function_ProcGenerarPreview.py``.
Aqui solo estan las funciones puras y la forma del estado
compartido (``ProcPreviewContext``).

Output (shape legacy back-compat con la SPA)::

    {
      "proc_uid":           int,
      "proc_codigo":        str,
      "precondiciones_ok":  bool,
      "missing_blocks":     list[str],
      "db_param_name":      str,
      "db_alm_name":        str,
      "table_name":         str,
      "arrays": {
        "PReal": {"db_name", "array_name", "satellite_arrays",
                  "current_count", "desired_count", "slot_map"},
        "PInt":  {...},
        "ALM":   {...},
      },
      "summary":    {"total", "agregados", "renombrados",
                     "eliminados", "sin_cambios"},
      "nmax":       {"current", "desired", "todos", "summary"},
      "warnings":   list[str],
    }

Restricciones arquitectonicas (.clinerules):
  - NO importa ``siemens_tia_scripting``.
  - Toda interaccion con TIA Portal pasa por ``tia_client`` (gateway
    asincrono, inyectable como kwarg).
  - Sin Singletons dentro del helper; todas las deps inyectadas.
  - Cero rutas hardcodeadas: rutas y carpetas se leen del
    ``ConfigManager`` y del ``build_cache``.
  - El helper NO toca ``progress_tracker``; eso es responsabilidad
    del FB wrapper (``FunctionProcGenerarPreview``).
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

from areas.alimentacion.helpers.tia.dispatch_async import dispatch_async


logger = logging.getLogger("zc.areas.alimentacion.proc_generate_preview")


# ===========================================================================
# Contexto mutable (estado compartido entre las funciones del helper)
# ===========================================================================

@dataclass
class ProcPreviewContext:
    """Estado compartido entre las funciones de ``proc_generate_preview``.

    Cada funcion toma un ``ProcPreviewContext`` por argumento, lee las
    deps inyectadas y los resultados de funciones previas, y muta los
    campos que representan resultados de su trabajo. El FB
    ``FunctionProcGenerarPreview`` instancia uno y lo reusa entre sus 6
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

    # ── Resultado de proc_check_state ──
    excel_loaded: bool = True

    # ── Resultado de proc_check_blocks ──
    bloques_loaded: bool = True

    # ── Resultado de proc_build_slot_maps ──
    slot_map: Any = None  # DataProcSlotMap o None
    slot_map_error: str | None = None

    # ── Resultado de proc_compute_nmax ──
    nmax_block: dict[str, Any] = field(default_factory=dict)

    # ── Resultado de proc_export_and_diff ──
    preal_current: "dict[int, str | None] | None" = None
    pint_current: "dict[int, str | None] | None" = None
    alm_current: "dict[int, str | None] | None" = None
    export_error: str | None = None

    # ── Resultado de proc_compose_response (shape legacy final) ──
    result: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# 5 funciones puras/async (cada una muta ``ctx``; sin state machine aqui)
# ===========================================================================

def proc_check_state(ctx: ProcPreviewContext) -> None:
    """Valida que ``AppState.excel_cache`` esta cargado.

    Si no lo esta, marca ``ctx.excel_loaded = False``. El FB
    inspecciona este flag para devolver el shape de error
    correspondiente (``precondiciones_ok=False``,
    ``missing_blocks=[...]``) en ``proc_compose_response``.
    """
    if ctx.app_state is None or ctx.app_state.excel_cache is None:
        ctx.excel_loaded = False
        return
    ctx.excel_loaded = True


def proc_check_blocks(ctx: ProcPreviewContext) -> None:
    """Valida que el cache de bloques del PLC esta disponible.

    Distinguimos 2 casos de "sin cache":
      1. ``bloques_cache is None`` -> el PLC nunca ha sido escaneado.
      2. ``bloques_cache`` existe pero esta vacio -> estado valido
         pero improbable; el FB lo marca como ``missing_blocks``
         via el slot_map resultante.

    Aqui solo marcamos el flag ``bloques_loaded``; la logica de
    "missing blocks concretos" vive en ``proc_build_slot_maps``.
    """
    ctx.bloques_loaded = ctx.bloques_cache is not None


def proc_build_slot_maps(ctx: ProcPreviewContext) -> None:
    """Cruza Excel + ``DataBloqueCache`` via ``proc_build_slot_maps``.

    Si la operacion lanza ``RuntimeError`` (p. ej. uid no existe en
    el Excel, o PLC sin bloques), captura la excepcion y la deja en
    ``ctx.slot_map_error`` para que ``proc_compose_response`` la
    muestre al operario. NO abortamos: el helper siempre deja el
    ``ctx`` en estado consistente (slot_map o error, nunca ambos).
    """
    if not ctx.excel_loaded or not ctx.bloques_loaded:
        # Si ya fallaron checks previos, skip.
        return
    from areas.alimentacion.data.data_ProcSlotMap import proc_build_slot_maps
    try:
        ctx.slot_map = proc_build_slot_maps(
            ctx.app_state, ctx.config_manager, ctx.proc_uid, ctx.bloques_cache
        )
        ctx.slot_map_error = None
    except RuntimeError as exc:
        ctx.slot_map = None
        ctx.slot_map_error = str(exc)


async def proc_compute_nmax(ctx: ProcPreviewContext) -> None:
    """Lee los N_MAX del proceso (cards SOLO VISUALES para la SPA).

    Convencion del operario (2026-09-02): las PlcUserConstant N_MAX de
    un proceso viven en la **tabla del proceso** (``<uid>_<codigo>``,
    p. ej. ``100_CPR``), en la carpeta TIA ``003_Procesos/``. NO en
    la tabla ``000_Config_Dispositivos``.

    Compara el desired (de ``DataProcSlotMap.nmax``, ``len()`` de las
    listas filtradas del Excel) contra el current (exportando la
    tabla del proceso con ``tia_client.export_plc_tags_xml`` y
    parseando con ``SimaticMLTagParser.parse_user_constants``).

    Mismo shape que el ``nmax_block`` de Dispositivos:
    ``{"current", "desired", "todos", "summary"}``.

    Si el config no aporta ``procesos.n_max_suffixes`` o no hay
    slot_map (fase previa fallo), devuelve un bloque vacio. Si el
    export falla, emite un warning y devuelve ``current={}`` sin
    abortar el preview.
    """
    if ctx.slot_map is None or ctx.slot_map_error is not None:
        ctx.nmax_block = _empty_nmax_block()
        return

    nmax_names = ctx.slot_map.nmax_names
    nmax_desired = ctx.slot_map.nmax
    if not nmax_names or not nmax_desired:
        ctx.nmax_block = _empty_nmax_block()
        return

    from areas.alimentacion.helpers.build_cache import build_cache
    from areas.alimentacion.helpers.xml.disp_tag_table_parser import (
        SimaticMLTagParser,
    )
    from core.infrastructure.tia.tia_export_paths import XmlTarget

    target_dir = build_cache(root=ctx.build_cache_root).procesos.preview_variables
    table_name = ctx.slot_map.table_name
    plc_name = ctx.bloques_cache.plc_name if ctx.bloques_cache else ""

    current: dict[str, int] = {}
    try:
        await dispatch_async(
            ctx.tia_client,
            "export_plc_tags_xml",
            {
                "plc_name": plc_name,
                "target_dir": str(target_dir),
                "table_names": [table_name],
            },
            timeout_s=120.0,
        )
        try:
            xml_path = XmlTarget(target_dir, table_name).path
            current = SimaticMLTagParser.parse_user_constants(xml_path)
        except FileNotFoundError:
            logger.warning(
                f"[N_MAX procesos] XML esperado no encontrado en "
                f"{target_dir} para tabla {table_name}."
            )
    except Exception as exc:
        logger.warning(
            f"[N_MAX procesos] export/parse fallo: {exc}. "
            f"Devolviendo current={{}} para no romper la SPA."
        )
        current = {}

    todos: list[dict[str, Any]] = []
    for kind, name in nmax_names.items():
        cur_val = current.get(name)
        des_val = nmax_desired.get(kind, 0)
        if cur_val is not None and int(cur_val) == int(des_val):
            status = "sin_cambios"
        else:
            status = "actualizar"
        todos.append({
            "kind": kind,
            "name": name,
            "actual": cur_val,
            "nuevo": des_val,
            "status": status,
        })

    ctx.nmax_block = {
        "current": {nmax_names[k]: v for k, v in current.items()
                    if k in nmax_names},
        "desired": {nmax_names[k]: nmax_desired[k] for k in nmax_names
                    if k in nmax_desired},
        "todos": todos,
        "summary": {
            "actualizar": sum(1 for r in todos if r["status"] == "actualizar"),
            "sin_cambios": sum(1 for r in todos if r["status"] == "sin_cambios"),
            "total": len(todos),
        },
    }


async def proc_export_and_diff(ctx: ProcPreviewContext) -> None:
    """Exporta los 2 DBs del proceso y lee los ``es-ES`` actuales.

    Stages internos:
      1. Exporta ``DB_PARAM`` y ``DB_ALM`` a
         ``<build_cache>/procesos/preview/bloques/``. Esto puede
         tardar 1-3 min en PLCs grandes.
      2. Crea un ``ProcCommentUpdater`` por DB (sin slot_map, solo
         para usar ``read_current_comments``) y consulta el
         ``es-ES`` actual de cada slot.
      3. Mutua ``ctx.preal_current``, ``ctx.pint_current`` y
         ``ctx.alm_current``.

    Si el export falla (TIA no responde, permisos, etc.), NO
    abortamos: devolvemos ``current=None`` para todos los arrays y
    emitimos un warning via ``ctx.export_error``. El operario ve que
    algo fallo pero el preview sigue siendo util (al menos sabe que
    slots quiere actualizar).
    """
    if ctx.slot_map is None or ctx.slot_map_error is not None:
        return

    from areas.alimentacion.helpers.build_cache import build_cache
    from areas.alimentacion.helpers.simatic_sd.simatic_sd_proc_comment_updater import (
        ProcCommentUpdater,
    )
    from core.infrastructure.tia.tia_export_paths import SdPair

    work_dir = build_cache(root=ctx.build_cache_root).procesos.preview_bloques
    plc_name = (
        ctx.bloques_cache.plc_name
        if ctx.bloques_cache is not None
        else ""
    )
    if not plc_name:
        ctx.export_error = "DataBloqueCache sin plc_name; no se puede exportar."
        logger.warning(ctx.export_error)
        return

    try:
        # 1. Exportar los 2 DBs (secuencial; export_block no es
        # thread-safe a nivel del wrapper .NET).
        await dispatch_async(
            ctx.tia_client,
            "export_block",
            {
                "plc_name": plc_name,
                "block_name": ctx.slot_map.db_param_name,
                "target_dir": str(work_dir),
            },
            timeout_s=120.0,
        )
        await dispatch_async(
            ctx.tia_client,
            "export_block",
            {
                "plc_name": plc_name,
                "block_name": ctx.slot_map.db_alm_name,
                "target_dir": str(work_dir),
            },
            timeout_s=120.0,
        )

        # 2. Leer los comentarios actuales de cada array. Creamos 2
        # updaters en modo solo-lectura (sin slot_map ni array_name
        # de instancia, porque cada read_current_comments recibe su
        # propio array_name por parametro).
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

        # Slots a leer: los del Excel + los que tienen asignacion
        # en el ``.s7dcl`` (slots de TIA no en el Excel -> "eliminar"
        # en el preview). Si el ``.s7dcl`` no existe, ``find_array_slots``
        # devuelve set() y solo se leen los del Excel (modo degradado).
        preal_slots = (
            set(ctx.slot_map.preal.keys()) | updater_param.find_array_slots("PReal")
        )
        pint_slots = (
            set(ctx.slot_map.pint.keys()) | updater_param.find_array_slots("PInt")
        )
        alm_slots = (
            set(ctx.slot_map.alm.keys()) | updater_alm.find_array_slots("ALM")
        )
        ctx.preal_current = updater_param.read_current_comments(
            sorted(preal_slots), "PReal"
        )
        ctx.pint_current = updater_param.read_current_comments(
            sorted(pint_slots), "PInt"
        )
        ctx.alm_current = updater_alm.read_current_comments(
            sorted(alm_slots), "ALM"
        )
        ctx.export_error = None
    except Exception as exc:
        logger.warning(
            f"proc_export_and_diff fallo: {exc}. Devolviendo "
            f"current=None para todos los slots."
        )
        ctx.preal_current = None
        ctx.pint_current = None
        ctx.alm_current = None
        ctx.export_error = str(exc)


def proc_compose_response(ctx: ProcPreviewContext) -> None:
    """Compone el ``ctx.result`` con el shape legacy de la SPA.

    Inspecciona los flags del ctx (excel_loaded, bloques_loaded,
    slot_map_error, slot_map.missing_blocks) para decidir el shape:

      - Sin Excel -> respuesta vacia + missing_blocks con hint.
      - Sin bloques -> respuesta vacia + missing_blocks con hint.
      - slot_map error -> respuesta vacia + missing_blocks con error.
      - Missing blocks en PLC -> respuesta vacia + missing_blocks
        concretos del slot_map.
      - Happy path -> arrays completos + nmax + warnings.
      - Export fallido (current=None) -> happy path con warnings
        adicionales (el operario ve que algo fallo pero el preview
        sigue siendo util).

    Esta funcion es la UNICA del helper que escribe ``ctx.result``.
    El FB la llama al final y vuelca ``ctx.result`` a ``self.result``.
    """
    empty_summary = {
        "total": 0, "agregados": 0, "renombrados": 0,
        "eliminados": 0, "sin_cambios": 0,
    }

    if not ctx.excel_loaded:
        ctx.result = {
            "proc_uid": ctx.proc_uid,
            "precondiciones_ok": False,
            "missing_blocks": [
                "AppState no tiene Excel cargado. Cargue el Excel con "
                "POST /api/v1/excel/upload."
            ],
            "arrays": {},
            "summary": dict(empty_summary),
            "warnings": [],
        }
        return

    if not ctx.bloques_loaded:
        ctx.result = {
            "proc_uid": ctx.proc_uid,
            "precondiciones_ok": False,
            "missing_blocks": [
                "Cache de bloques del PLC no disponible. "
                "Selecciona el PLC en el sidebar y espera al "
                "escaneo de bloques (1-3 min en PLCs grandes)."
            ],
            "arrays": {},
            "summary": dict(empty_summary),
            "warnings": [],
        }
        return

    if ctx.slot_map is None or ctx.slot_map_error is not None:
        ctx.result = {
            "proc_uid": ctx.proc_uid,
            "precondiciones_ok": False,
            "missing_blocks": [
                ctx.slot_map_error or "Error construyendo slot maps"
            ],
            "arrays": {},
            "summary": dict(empty_summary),
            "warnings": [],
        }
        return

    if ctx.slot_map.missing_blocks:
        ctx.result = {
            "proc_uid": ctx.proc_uid,
            "proc_codigo": _extract_codigo(ctx.slot_map.db_param_name),
            "precondiciones_ok": False,
            "missing_blocks": ctx.slot_map.missing_blocks,
            "db_param_name": ctx.slot_map.db_param_name,
            "db_alm_name": ctx.slot_map.db_alm_name,
            "table_name": ctx.slot_map.table_name,
            "arrays": {},
            "summary": dict(empty_summary),
            "warnings": ctx.slot_map.warnings,
        }
        return

    # Happy path: compose arrays + summary, merge warnings.
    arrays = _compose_arrays_internal(
        ctx.slot_map, ctx.preal_current, ctx.pint_current, ctx.alm_current
    )
    summary = _compute_summary_internal(arrays)
    warnings = list(ctx.slot_map.warnings)
    if ctx.export_error:
        warnings.append(f"Export fallo: {ctx.export_error}. current=None.")

    ctx.result = {
        "proc_uid": ctx.proc_uid,
        "proc_codigo": _extract_codigo(ctx.slot_map.db_param_name),
        "precondiciones_ok": True,
        "missing_blocks": [],
        "db_param_name": ctx.slot_map.db_param_name,
        "db_alm_name": ctx.slot_map.db_alm_name,
        "table_name": ctx.slot_map.table_name,
        "arrays": arrays,
        "summary": summary,
        "nmax": ctx.nmax_block,
        "warnings": warnings,
    }


# ===========================================================================
# Internals puras (no mutan ctx; reciben los datos como args)
# ===========================================================================

def _empty_nmax_block() -> dict[str, Any]:
    """Shape de nmax_block cuando no hay config o falla el slot_map."""
    return {
        "current": {},
        "desired": {},
        "todos": [],
        "summary": {
            "actualizar": 0, "sin_cambios": 0, "total": 0,
        },
    }


def _extract_codigo(db_param_name: str) -> str:
    """Extrae el ``codigo`` del nombre de DB (``DB53100_CPR_PARAM``
    -> ``"CPR"``). Devuelve ``""`` si el formato no encaja."""
    parts = db_param_name.split("_")
    if len(parts) >= 2:
        return parts[1]
    return ""


def _compose_arrays_internal(
    slot_map: Any,
    preal_current: "dict[int, str | None] | None",
    pint_current: "dict[int, str | None] | None",
    alm_current: "dict[int, str | None] | None",
) -> dict[str, Any]:
    """Compone el dict ``arrays`` con los 3 arrays del proceso.

    Para cada slot, generamos una entrada ``{current, desired,
    action}`` con ``action in {"sin_cambios", "renombrar",
    "agregar", "eliminar"}``.

    Slots del Excel (``slot_map_dict``):
      - Si se pasan los mapas ``*_current``: ``current`` es el
        ``es-ES`` real de TIA y ``action``:
          - ``"agregar"`` si el slot no existe en TIA (``current
            is None``) -> el apply lo creara.
          - ``"renombrar"`` si ``current != desired``.
          - ``"sin_cambios"`` si ``current == desired``.
      - Si los mapas son ``None`` (export degradado): ``action``
        se infiere del desired (``"."`` -> "agregar", otro ->
        "renombrar").

    Slots de TIA NO en el Excel (``current_dict - slot_map_dict``):
      - Caso "eliminar". El slot existe en TIA con un comentario
        historico pero el operario no lo tiene en su Excel
        (p. ej. compactado de 60 slots donde el Excel solo trae
        los 20 que el operario quiere gestionar). El apply
        resetea el comentario a ``"."`` (convencion TIA "sin
        comentario"). Si el current es ``""`` (ya vacio),
        ``action = "sin_cambios"``.
    """
    arrays: dict[str, Any] = {}
    satellites_by_array = slot_map.satellites_by_array
    for arr_name, slot_map_dict, db_name, current_dict in (
        ("PReal", slot_map.preal, slot_map.db_param_name, preal_current),
        ("PInt", slot_map.pint, slot_map.db_param_name, pint_current),
        ("ALM", slot_map.alm, slot_map.db_alm_name, alm_current),
    ):
        satellites = satellites_by_array.get(arr_name.lower(), ())
        slot_map_serialized: dict[str, Any] = {}
        # Slots del Excel: comparar desired vs current.
        for slot, desired in slot_map_dict.items():
            if current_dict is not None:
                current = current_dict.get(slot)
                if current is None:
                    action = "agregar"
                elif current == desired:
                    action = "sin_cambios"
                else:
                    action = "renombrar"
            else:
                current = None
                action = "agregar" if desired == "." else "renombrar"
            slot_map_serialized[str(slot)] = {
                "current": current,
                "desired": desired,
                "action": action,
            }
        # Slots de TIA NO en el Excel: "eliminar".
        if current_dict is not None:
            excel_slots = set(slot_map_dict.keys())
            tia_slots = set(current_dict.keys())
            to_remove = sorted(tia_slots - excel_slots)
            for slot in to_remove:
                current = current_dict[slot]
                if current is None or current == "":
                    # Slot vacio en TIA, no hay nada que borrar.
                    action = "sin_cambios"
                else:
                    action = "eliminar"
                slot_map_serialized[str(slot)] = {
                    "current": current,
                    "desired": None,
                    "action": action,
                }
        arrays[arr_name] = {
            "db_name": db_name,
            "array_name": arr_name,
            "satellite_arrays": satellites,
            "current_count": len(current_dict) if current_dict is not None else 0,
            "desired_count": len(slot_map_dict),
            "slot_map": slot_map_serialized,
        }
    return arrays


def _compute_summary_internal(arrays: dict[str, Any]) -> dict[str, int]:
    """Suma el total de slots y cuenta por tipo de accion.

    Shape del dict (alineado con ``sync_dispositivos_instances``):
    ``agregados``, ``renombrados``, ``eliminados``, ``sin_cambios``,
    ``total``.
    """
    total = 0
    agregados = 0
    renombrados = 0
    eliminados = 0
    sin_cambios = 0
    for arr in arrays.values():
        for entry in arr.get("slot_map", {}).values():
            total += 1
            action = entry.get("action")
            if action == "agregar":
                agregados += 1
            elif action == "renombrar":
                renombrados += 1
            elif action == "eliminar":
                eliminados += 1
            elif action == "sin_cambios":
                sin_cambios += 1
    return {
        "total": total,
        "agregados": agregados,
        "renombrados": renombrados,
        "eliminados": eliminados,
        "sin_cambios": sin_cambios,
    }


# Nota: ``dispatch_async`` se importa arriba desde
# ``areas.alimentacion.helpers.tia.dispatch_async``. Antes vivia
# duplicado aqui (4 copias en total: 2 disp + 2 proc); ahora vive
# como helper compartido.


__all__ = ["ProcPreviewContext", "proc_check_state", "proc_check_blocks",
           "proc_build_slot_maps", "proc_compute_nmax",
           "proc_export_and_diff", "proc_compose_response"]
