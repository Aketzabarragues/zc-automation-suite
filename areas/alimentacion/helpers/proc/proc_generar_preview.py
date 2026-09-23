"""Helpers puros del FB ``function_proc_db_generar_preview``.

Funciones sin estado compartido que el FB invoca en sus stages para
componer el resultado del preview. Ninguna muta el ``ProcPreviewContext``:
reciben los datos como argumentos y devuelven dicts/valores.

Convencion F11: los helpers puros del area viven en
``areas/alimentacion/helpers/<dominio>/`` (no dentro del FB). Esto
permite tests unitarios focalizados y reutilizacion desde otros FBs
del mismo dominio.
"""
from __future__ import annotations

from typing import Any


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


__all__ = ["empty_nmax_block", "extract_codigo", "compose_arrays", "compute_summary"]
