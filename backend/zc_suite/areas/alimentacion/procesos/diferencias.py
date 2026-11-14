"""zc_suite.areas.alimentacion.procesos.diferencias — el diff de procesos.

Lo que hay en TIA frente a lo que dice el Excel, para un proceso: los
comentarios de los slots de los tres arrays (``PReal``, ``PInt``, ``ALM``) y
los N_MAX de la tabla del proceso.

Es logica pura: no habla con el portal de TIA y no abre transacciones. El FB
que la usa es ``../funciones/procesos/generar_prevision.py``.

El port de ``main`` (``helpers/proc/proc_db_generar_preview.py``) con los
mismos criterios:

- El slot ``0`` es el placeholder ``"NO USAR"``: existe en el mapa (y en TIA)
  pero **no** aparece en el diff: lo gestiona el sync, no la vista.
- Un slot del Excel que no esta en TIA (``current is None``) es un
  ``agregar`` (como ``main``: el apply lo crea, con o sin comentario).
- Un slot con ``current != desired`` es un ``renombrar``; con
  ``current == desired``, ``sin_cambios``.
- Un slot de TIA que no esta en el Excel es un ``eliminar``: su comentario se
  resetea a ``"."``. Si su comentario actual ya es ``""`` (vacio), no hay nada
  que borrar y sale como ``sin_cambios``. Un slot cuyo comentario en TIA ya
  es ``"."`` sigue saliendo como ``eliminar`` (no como ``sin_cambios``),
  como ``main``.
- Si el DB no se pudo leer (estado actual ``None``), la accion se infiere del
  deseado (``"."`` -> ``agregar``, otro -> ``renombrar``).
- El ``db_name`` de cada array es el del DB al que pertenece: ``PReal`` y
  ``PInt`` viven en el DB_PARAM y ``ALM`` en el DB_ALM. Cada array lleva sus
  ``satellite_arrays`` (los arrays satelites que se aplican con el mismo
  mapa).
- Los N_MAX se comparan por nombre canonico TIA (los ``values`` de
  ``nmax_names``): el valor actual sale del XML exportado de la tabla del
  proceso y el deseado, de la columna del proceso del Excel.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.procesos.mapa import MapaProceso
from zc_suite.simatic.ml import ParserConstantesUsuario
from zc_suite.simatic.sd import comentarios_actuales, indices_de_array

logger = logging.getLogger(__name__)

#: Los arrays de un proceso, por array: ``(nombre, slot_map, db, actual,
#: tipo, satelites)``. El orden es el de ``main``.
_TIPO_UDT = "UDT"
_TIPO_SIMPLE = "Simple"

#: Los arrays satelites de cada array principal (``main: PROC_SATELLITES_BY_ARRAY``).
SATELITES_POR_ARRAY: dict[str, tuple[str, ...]] = {
    "PReal": ("PReal_Vis", "Aux.PReal_ValorAnterior"),
    "PInt": ("PInt_Vis", "Aux.PInt_ValorAnterior"),
    "ALM": (),
}


# ── el estado actual de los arrays ──────────────────────────────────────────


def _slots_actuales(
    dcl_text: str,
    res_text: str,
    array: str,
    slot_map: dict[int, str],
    array_type: str,
) -> dict[int, str | None] | None:
    """Los comentarios ``es-ES`` actuales de un array, o ``None`` si el DB
    no se pudo leer (el par ``.s7dcl``/``.s7res`` esta vacio).

    Se leen los slots de la union de los slots del Excel y los que TIA tiene
    en el ``.s7dcl``: los que estan en TIA y no en el Excel son los que se
    marcan como ``eliminar``.
    """
    if not dcl_text or not res_text:
        return None
    slots = set(slot_map) | indices_de_array(dcl_text, array, array_type)
    return comentarios_actuales(
        res_text=res_text,
        array_name=array,
        indices=sorted(slots),
        dcl_text=dcl_text,
        array_type=array_type,
    )


# ── el diff de los comentarios ───────────────────────────────────────────────


def _slot_entry(
    slot: int,
    desired: str,
    actual: dict[int, str | None] | None,
) -> dict[str, Any]:
    """La entrada ``{current, desired, action}`` de un slot del Excel.

    Si ``actual`` es ``None`` (DB no leido) la accion se infiere del deseado.
    """
    if actual is None:
        return {
            "current": None,
            "desired": desired,
            "action": "agregar" if desired == "." else "renombrar",
        }
    current = actual.get(slot)
    if current is None:
        action = "agregar"
    elif current == desired:
        action = "sin_cambios"
    else:
        action = "renombrar"
    return {"current": current, "desired": desired, "action": action}


def _slots_a_eliminar(
    slot_map: dict[int, str],
    actual: dict[int, str | None],
) -> dict[int, dict[str, Any]]:
    """Los slots de TIA que no estan en el Excel: se eliminan.

    Un slot cuyo comentario actual ya esta vacio no se toca (``sin_cambios``).
    """
    excel_slots = set(slot_map)
    eliminados: dict[int, dict[str, Any]] = {}
    for slot in sorted(set(actual) - excel_slots):
        current = actual[slot]
        action = "sin_cambios" if current is None or current == "" else "eliminar"
        eliminados[slot] = {"current": current, "desired": None, "action": action}
    return eliminados


def proc_calcular_arrays(
    mapa: MapaProceso,
    dcl_param: str,
    res_param: str,
    dcl_alm: str,
    res_alm: str,
) -> dict[str, Any]:
    """El dict ``arrays`` con los tres arrays del proceso.

    Para cada slot, una entrada ``{current, desired, action}`` con
    ``action in {"sin_cambios", "renombrar", "agregar", "eliminar"}``.

    Args:
        mapa: el mapa del proceso (slot maps del Excel y nombres de DB).
        dcl_param: texto del ``.s7dcl`` del DB_PARAM (vacio si no se exporto).
        res_param: texto del ``.s7res`` del DB_PARAM.
        dcl_alm: texto del ``.s7dcl`` del DB_ALM.
        res_alm: texto del ``.s7res`` del DB_ALM.

    Returns:
        ``{"PReal": {...}, "PInt": {...}, "ALM": {...}}`` con ``db_name``,
        ``array_name``, ``satellite_arrays``, ``current_count``,
        ``desired_count`` y ``slot_map`` (claves de slot como ``str``).
    """
    arrays: dict[str, Any] = {}
    configuracion = (
        ("PReal", mapa.preal, mapa.db_param_name, dcl_param, res_param, _TIPO_UDT),
        ("PInt", mapa.pint, mapa.db_param_name, dcl_param, res_param, _TIPO_UDT),
        ("ALM", mapa.alm, mapa.db_alm_name, dcl_alm, res_alm, _TIPO_SIMPLE),
    )
    for array, slot_map, db_name, dcl, res, array_type in configuracion:
        actual = _slots_actuales(dcl, res, array, slot_map, array_type)
        slot_map_serializado: dict[str, dict[str, Any]] = {}
        for slot, desired in slot_map.items():
            if slot == 0:
                continue
            entry = _slot_entry(slot, desired, actual)
            slot_map_serializado[str(slot)] = entry
        if actual is not None:
            slot_map_serializado.update(
                {
                    str(slot): entry
                    for slot, entry in _slots_a_eliminar(slot_map, actual).items()
                }
            )
        arrays[array] = {
            "db_name": db_name,
            "array_name": array,
            "satellite_arrays": list(SATELITES_POR_ARRAY.get(array, ())),
            "current_count": len(actual) if actual is not None else 0,
            "desired_count": len(slot_map),
            "slot_map": slot_map_serializado,
        }
    return arrays


def proc_resumen(arrays: dict[str, Any]) -> dict[str, int]:
    """El resumen agregado de los arrays: total de slots y cuenta por accion.

    Returns:
        ``{total, agregados, renombrados, eliminados, sin_cambios}``.
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


# ── el diff del N_MAX ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DiffNMax:
    """El diff de los N_MAX de un proceso entre lo deseado (Excel) y lo que
    hay (TIA).

    Attributes:
        tabla: nombre de la tabla del proceso (``"100_CPR"``).
        actual: los valores de TIA (``{}`` si falta el XML),
            ``{nombre_TIA: valor}``.
        deseado: los valores del Excel, ``{nombre_TIA: valor}``.
        todos: lista de ``{kind, name, actual, nuevo, status}`` por N_MAX.
        resumen: ``{actualizar, sin_cambios, total}``.
        xml_ausente: ``True`` si el XML no existia.
    """

    tabla: str
    actual: dict[str, int]
    deseado: dict[str, int]
    todos: list[dict[str, Any]] = field(default_factory=list)
    resumen: dict[str, int] = field(default_factory=dict)
    xml_ausente: bool = False


def _leer_n_max_del_xml(ruta_xml: Path) -> tuple[dict[str, int], str | None]:
    """Lee un XML plano con los N_MAX y devuelve ``(valores, error)``.

    Devuelve ``({}, mensaje)`` si el XML falta o no se puede parsear.
    """
    if not ruta_xml.is_file():
        return {}, f"El XML de los N_MAX no esta en la exportacion de TIA: {ruta_xml}"
    try:
        valores = ParserConstantesUsuario.leer_constantes(ruta_xml)
        return dict(valores), None
    except Exception as exc:
        logger.error("[N_MAX proc] No se pudo parsear %s: %s", ruta_xml, exc)
        return {}, f"no se pudo parsear: {exc}"


def proc_calcular_diff_n_max(
    tabla: str,
    nmax_names: dict[str, str],
    nmax_deseado: dict[str, int],
    ruta_xml: Path,
) -> DiffNMax:
    """El diff de los N_MAX de un proceso, entre el Excel y el XML de TIA.

    Los N_MAX son constantes de la tabla del proceso. El nombre canonico es
    ``<uid>_N_MAX_<SUFIXO>`` (los ``values`` de ``nmax_names``) y el valor
    deseado es la columna del proceso del Excel (``nmax_deseado``).

    Args:
        tabla: nombre de la tabla del proceso (``"100_CPR"``).
        nmax_names: ``{sufijo: nombre_TIA}`` del proceso (de ``mapa.py``).
        nmax_deseado: ``{sufijo: valor}`` del Excel (de ``mapa.py``).
        ruta_xml: ruta al XML plano exportado de TIA.

    Returns:
        El ``DiffNMax`` con ``actual``, ``deseado``, ``todos`` y ``resumen``.
    """
    actual_crudo, error = _leer_n_max_del_xml(ruta_xml)
    if error is not None:
        deseado = {
            nmax_names[k]: int(nmax_deseado[k])
            for k in nmax_names
            if k in nmax_deseado
        }
        return DiffNMax(
            tabla=tabla,
            actual={},
            deseado=deseado,
            todos=[],
            resumen={
                "actualizar": 0,
                "sin_cambios": len(deseado),
                "total": len(deseado),
            },
            xml_ausente=True,
        )

    # Filtrar los N_MAX del XML por los NOMBRES TIA del config (los values de
    # ``nmax_names``), no por los sufijos: la tabla del proceso solo contiene
    # sus propias constantes.
    nombres_tia = set(nmax_names.values())
    actual = {
        nombre: int(valor)
        for nombre, valor in actual_crudo.items()
        if nombre in nombres_tia
    }
    deseado = {
        nmax_names[k]: int(nmax_deseado[k])
        for k in nmax_names
        if k in nmax_deseado
    }

    todos: list[dict[str, Any]] = []
    for kind, name in nmax_names.items():
        cur_val = actual.get(name)
        des_val = deseado.get(name, 0)
        status = (
            "sin_cambios"
            if cur_val is not None and int(cur_val) == int(des_val)
            else "actualizar"
        )
        todos.append(
            {
                "kind": kind,
                "name": name,
                "actual": cur_val,
                "nuevo": des_val,
                "status": status,
            }
        )

    return DiffNMax(
        tabla=tabla,
        actual=actual,
        deseado=deseado,
        todos=todos,
        resumen={
            "actualizar": sum(1 for fila in todos if fila["status"] == "actualizar"),
            "sin_cambios": sum(1 for fila in todos if fila["status"] == "sin_cambios"),
            "total": len(todos),
        },
        xml_ausente=False,
    )
