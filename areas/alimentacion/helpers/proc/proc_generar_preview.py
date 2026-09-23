"""Helpers puros del FB ``function_proc_db_generar_preview`` y del sync.

Funciones sin estado compartido que el FB y su sync invocan para
componer el resultado del preview. Ninguna muta el
``ProcPreviewContext``: reciben los datos como argumentos y devuelven
dataclasses/dicts/valores.

Convencion F11: los helpers puros del area viven en
``areas/alimentacion/helpers/<dominio>/`` (no dentro del FB). Esto
permite tests unitarios focalizados y reutilizacion desde otros FBs
del mismo dominio (en particular, desde
``function_proc_db_sincronizar._stage_8_post_preview``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.helpers.simatic_ml import PlcUserConstantParser
from core.helpers.simatic_sd import find_array_slots, read_current_comments


def empty_nmax_block() -> dict[str, Any]:
    """Shape de nmax_block cuando no hay config o falla el slot_map."""
    return {
        "current": {},
        "desired": {},
        "todos": [],
        "summary": {
            "actualizar": 0, "sin_cambios": 0, "total": 0,
        },
    }


def extract_codigo(db_param_name: str) -> str:
    """Extrae el ``codigo`` del nombre de DB (``DB53100_CPR_PARAM``
    -> ``"CPR"``). Devuelve ``""`` si el formato no encaja."""
    parts = db_param_name.split("_")
    if len(parts) >= 2:
        return parts[1]
    return ""


def compose_arrays(
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


def compute_summary(arrays: dict[str, Any]) -> dict[str, int]:
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


@dataclass(frozen=True)
class NmaxDiff:
    """Resultado del diff de N_MAX entre desired (Excel/AppState) y base (TIA).

    Atributos:
        table_name: nombre de la tabla del proceso (``"100_CPR"``).
        current: valores del TIA (``{}`` si XML falta).
        desired: valores del Excel (keys = nombres TIA canonicos).
        todos: lista de ``{kind, name, actual, nuevo, status}`` por N_MAX.
        summary: ``{actualizar, sin_cambios, total}``.
        missing_xml: True si el XML no existia.
    """

    table_name: str
    current: dict[str, int]
    desired: dict[str, int]
    todos: list[dict[str, Any]]
    summary: dict[str, int]
    missing_xml: bool = False


def _read_nmax_xml(xml_path: Path) -> tuple[dict[str, int], str | None]:
    """Lee un XML FLAT con N_MAX de un proceso y devuelve ``(values, error)``.

    Devuelve ``({}, "XML no encontrado...")`` si el XML falta,
    o ``({}, "parse fail: ...")`` si revienta.
    """
    import logging

    if not xml_path.is_file():
        return {}, f"XML de N_MAX no encontrado en TIA export: {xml_path}"
    try:
        values = PlcUserConstantParser.parse_user_constants(xml_path)
        return dict(values), None
    except Exception as exc:
        logging.getLogger(__name__).error(
            f"[N_MAX proc] Parse FAIL {xml_path}: {exc}"
        )
        return {}, f"parse fail: {exc}"


def compute_nmax_diff_for_proc(
    table_name: str,
    nmax_names: dict[str, str],
    nmax_desired: dict[str, int],
    xml_path: Path,
) -> NmaxDiff:
    """Calcula el diff de N_MAX de un proceso entre Excel y TIA.

    Args:
        table_name: nombre de la tabla del proceso (``"100_CPR"``).
        nmax_names: mapping ``kind -> nombre TIA canonico``
            (ej: ``{"preal": "100_N_MAX_PREAL"}``).
        nmax_desired: mapping ``kind -> valor deseado del Excel``
            (ej: ``{"preal": 30}``).
        xml_path: ruta al XML FLAT de la tabla del proceso exportada de TIA.

    Returns:
        ``NmaxDiff`` con ``current``/``desired`` (keys = nombres TIA),
        ``todos`` con ``{kind, name, actual, nuevo, status}``, y
        ``summary`` ``{actualizar, sin_cambios, total}``.
    """
    raw_current, error_message = _read_nmax_xml(xml_path)
    missing_xml = error_message is not None

    if missing_xml:
        desired_filtered: dict[str, int] = {
            nmax_names[k]: int(nmax_desired[k])
            for k in nmax_names if k in nmax_desired
        }
        return NmaxDiff(
            table_name=table_name,
            current={},
            desired=desired_filtered,
            todos=[],
            summary={
                "actualizar": 0,
                "sin_cambios": len(desired_filtered),
                "total": len(desired_filtered),
            },
            missing_xml=True,
        )

    current_filtered: dict[str, int] = {
        nmax_names[k]: int(v)
        for k, v in raw_current.items()
        if k in nmax_names
    }
    desired_filtered = {
        nmax_names[k]: int(nmax_desired[k])
        for k in nmax_names if k in nmax_desired
    }

    todos: list[dict[str, Any]] = []
    for kind, name in nmax_names.items():
        cur_val = current_filtered.get(name)
        des_val = desired_filtered.get(name, 0)
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

    return NmaxDiff(
        table_name=table_name,
        current=current_filtered,
        desired=desired_filtered,
        todos=todos,
        summary={
            "actualizar": sum(1 for r in todos if r["status"] == "actualizar"),
            "sin_cambios": sum(1 for r in todos if r["status"] == "sin_cambios"),
            "total": len(todos),
        },
        missing_xml=False,
    )


__all__ = [
    "NmaxDiff",
    "empty_nmax_block",
    "extract_codigo",
    "compose_arrays",
    "compute_proc_slot_diff",
    "compute_summary",
    "compute_nmax_diff_for_proc",
]


def compute_proc_slot_diff(
    slot_map: Any,
    dcl_param_text: str,
    res_param_text: str,
    dcl_alm_text: str,
    res_alm_text: str,
) -> tuple[
    "dict[int, str | None] | None",
    "dict[int, str | None] | None",
    "dict[int, str | None] | None",
]:
    """Lee los comentarios ``es-ES`` de los 3 arrays del proceso desde los .s7dcl/.s7res.

    Para cada array (PReal, PInt, ALM) se leen los slots que devuelve
    ``read_current_comments`` sobre la union de:
      - los slots del Excel (del ``slot_map``).
      - los slots que ``find_array_slots`` detecta en el ``.s7dcl``
        (slots de TIA no en el Excel -> "eliminar" en el preview).

    Args:
        slot_map: ``DataProcSlotMap`` con los slots del Excel por array.
        dcl_param_text: texto del ``.s7dcl`` de DB_PARAM (vacio si DB fallo).
        res_param_text: texto del ``.s7res`` de DB_PARAM (vacio si DB fallo).
        dcl_alm_text: texto del ``.s7dcl`` de DB_ALM (vacio si DB fallo).
        res_alm_text: texto del ``.s7res`` de DB_ALM (vacio si DB fallo).

    Returns:
        Tupla ``(preal_current, pint_current, alm_current)``. Cada
        elemento es:
          - ``dict[int, str | None]`` cuando su DB se exporto OK.
          - ``None`` cuando su DB fallo (modo degradado). El caller
            debe emitir warning y continuar.
    """
    preal_current: "dict[int, str | None] | None" = None
    pint_current: "dict[int, str | None] | None" = None
    alm_current: "dict[int, str | None] | None" = None

    if dcl_param_text and res_param_text:
        preal_slots = (
            set(slot_map.preal.keys())
            | find_array_slots(dcl_param_text, "PReal", "UDT")
        )
        pint_slots = (
            set(slot_map.pint.keys())
            | find_array_slots(dcl_param_text, "PInt", "UDT")
        )
        preal_current = read_current_comments(
            res_param_text, "PReal", sorted(preal_slots),
            dcl_param_text, "UDT",
        )
        pint_current = read_current_comments(
            res_param_text, "PInt", sorted(pint_slots),
            dcl_param_text, "UDT",
        )

    if dcl_alm_text and res_alm_text:
        alm_slots = (
            set(slot_map.alm.keys())
            | find_array_slots(dcl_alm_text, "ALM", "Simple")
        )
        alm_current = read_current_comments(
            res_alm_text, "ALM", sorted(alm_slots),
            dcl_alm_text, "Simple",
        )

    return preal_current, pint_current, alm_current
