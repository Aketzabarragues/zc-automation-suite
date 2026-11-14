"""zc_suite.areas.alimentacion.procesos.sincronizacion — el calculo del sync.

Que cambios hay que meter en TIA para que los comentarios de los DBs de un
proceso queden como los dice el Excel: los N_MAX de la tabla del proceso y
los comentarios de los siete arrays (los seis del DB_PARAM y el ``ALM`` del
DB_ALM).

Es logica pura: no habla con el portal de TIA y no abre transacciones. El FB
que la usa es ``../funciones/procesos/sincronizar.py``.

El port de los helpers de ``main`` (``function_proc_db_sincronizar``) con los
mismos criterios:

- El apply de un array es el **mapa completo** del Excel (slot 0 incluido,
  con su ``"NO USAR"``) mas los slots de TIA que el Excel no tiene: esos se
  borran. Borrar es poner el comentario a ``""`` (``confirmar_comentarios``
  elimina el MLC); un slot cuyo comentario actual ya esta vacio no se toca.
- La vista (la preview) usa la convencion ``"."`` para "sin comentario"; el
  apply usa ``""``: si se aplicara ``"."`` literal, los slots borrados
  quedarian con un comentario visible.
- Un slot map vacio (solo el slot 0) no se aplica: no hay nada que meter.
- Los satelites de un array (``PReal_Vis``, ``Aux.PReal_ValorAnterior``...)
  reciben el **mismo** mapa que su array principal.
- Un DB que no esta en la exportacion no se aplica: se avisa y se omite.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.dispositivos.diferencias import DiffNMax
from zc_suite.simatic.sd import ResultadoArray, confirmar_comentarios_array

logger = logging.getLogger(__name__)

#: Los arrays de un proceso, en el orden de ``main``: nombre, tipo
#: (``"UDT"`` o ``"Simple"``) y el array al que pertenece (los satelites
#: reciben el mapa de su principal).
ARRAYS_PROCESO: tuple[tuple[str, str, str], ...] = (
    ("PReal", "UDT", "PReal"),
    ("PReal_Vis", "Simple", "PReal"),
    ("Aux.PReal_ValorAnterior", "Simple", "PReal"),
    ("PInt", "UDT", "PInt"),
    ("PInt_Vis", "Simple", "PInt"),
    ("Aux.PInt_ValorAnterior", "Simple", "PInt"),
)

#: La extension de los ficheros SimaticSD del DB.
EXTENSION_DCL = ".s7dcl"
EXTENSION_RES = ".s7res"


# ── localizar los SimaticSD del export ──────────────────────────────────────


def proc_localizar_db(base: Path, db: str) -> tuple[Path, Path] | None:
    """El par ``.s7dcl``/``.s7res`` de un DB dentro de un export de TIA.

    Tolera los dos layouts de export:

    - plano: ``<base>/<db>.s7dcl``.
    - con la jerarquia de carpetas del PLC: ``<base>/<carpeta>/<db>.s7dcl``.

    Args:
        base: la carpeta raiz del export.
        db: el nombre del DB, sin extension.

    Returns:
        El par ``(dcl, res)``, o ``None`` si el DB no esta en el export.
    """
    if not base.is_dir():
        return None
    directo = base / f"{db}{EXTENSION_DCL}"
    if directo.is_file():
        return (directo, directo.with_suffix(EXTENSION_RES))
    for encontrado in sorted(base.rglob(f"{db}{EXTENSION_DCL}")):
        return (encontrado, encontrado.with_suffix(EXTENSION_RES))
    return None


# ── el apply de los comentarios ─────────────────────────────────────────────


def proc_mapa_apply(
    slot_map: dict[int, str],
    actuales: dict[int, str | None],
) -> dict[int, str]:
    """El mapa que se le pasa a ``confirmar_comentarios_array``.

    Es el mapa completo del Excel (slot 0 incluido) mas los slots de TIA
    que el Excel no tiene: esos se borran (``""``). Un slot cuyo comentario
    actual ya esta vacio no se toca: borrarlo no cambiaria nada.

    Args:
        slot_map: el mapa del Excel (``{slot: comentario}``, con el slot 0).
        actuales: los comentarios actuales que TIA tiene leidos del export
            (``{slot: texto}`` o ``None`` si el DB no se pudo leer).

    Returns:
        ``{slot: comentario}`` listo para aplicar. Vacio si ``slot_map``
        solo tiene el slot 0.
    """
    if len(slot_map) <= 1:
        return {}
    mapa = {slot: str(comentario) for slot, comentario in slot_map.items()}
    for slot in sorted(actuales):
        if slot in mapa:
            continue
        if actuales[slot]:
            mapa[slot] = ""
    return mapa


def proc_arrays_para_apply(
    mapa: dict[str, dict[int, str]],
    db_param: str,
    db_alm: str,
    db_missing: list[str],
) -> dict[str, dict[str, dict[int, str]]]:
    """Los mapas de apply de cada DB, con sus arrays.

    El DB_PARAM lleva los seis arrays (PReal y PInt con sus satelites) y el
    DB_ALM lleva el ``ALM``. Un DB que falta en el PLC no se aplica y se
    avisa.

    Args:
        mapa: los slot maps del proceso, ``{"preal", "pint", "alm"}``.
        db_param: el nombre del DB_PARAM.
        db_alm: el nombre del DB_ALM.
        db_missing: los DBs que no estan en el PLC (de ``MapaProceso``).

    Returns:
        ``{"<db>": {"PReal": mapa, ...}}``.
    """
    avisos = list(db_missing)
    resultados: dict[str, dict[str, dict[int, str]]] = {}
    if db_param not in db_missing:
        resultados[db_param] = {
            "PReal": dict(mapa["preal"]),
            "PReal_Vis": dict(mapa["preal"]),
            "Aux.PReal_ValorAnterior": dict(mapa["preal"]),
            "PInt": dict(mapa["pint"]),
            "PInt_Vis": dict(mapa["pint"]),
            "Aux.PInt_ValorAnterior": dict(mapa["pint"]),
        }
    if db_alm not in db_missing:
        resultados[db_alm] = {"ALM": dict(mapa["alm"])}
    if avisos:
        logger.warning(
            "[proc sync] DBs ausentes en la exportacion, se omiten: %s",
            ", ".join(avisos),
        )
    return resultados


# ── la edicion offline ──────────────────────────────────────────────────────


def proc_confirmar_db(
    base: Path,
    db: str,
    arrays: dict[str, dict[int, str]],
    actuales: dict[str, dict[int, str | None]],
) -> int:
    """Escribe los comentarios de un DB en su export (in-place).

    Para cada array del DB se llama a ``confirmar_comentarios_array`` con
    el mapa de apply (el slot map del Excel mas los slots que se borran) y
    ``write_to_original=True``: la llamada siguiente del mismo DB acumula
    sobre los ficheros que dejo la anterior.

    Args:
        base: la carpeta del export donde vive el par del DB.
        db: el nombre del DB.
        arrays: los slot maps del Excel del DB (``proc_arrays_para_apply``).
        actuales: los comentarios actuales por array (``{array: {slot: ...}}``),
            para saber cuales de los slots de TIA hay que borrar.

    Returns:
        Cuantos arrays del DB han cambiado.
    """
    par = proc_localizar_db(base, db)
    if par is None:
        logger.warning(
            "[proc sync] No se encontro el bloque '%s' en la exportacion: "
            "sus comentarios se omiten.",
            db,
        )
        return 0
    dcl, res = par
    modificados = 0
    for array, slot_map in arrays.items():
        mapa = proc_mapa_apply(slot_map, actuales.get(array, {}))
        if not mapa:
            continue
        resultado = _confirmar(dcl, res, array, mapa)
        if resultado.injected or resultado.updated or resultado.removed:
            modificados += 1
    return modificados


def _confirmar(dcl: Path, res: Path, array: str, mapa: dict[int, str]) -> ResultadoArray:
    """La llamada a ``confirmar_comentarios_array``, con el tipo del array."""
    tipo = next((t for n, t, _ in ARRAYS_PROCESO if n == array), "Simple")
    return confirmar_comentarios_array(
        dcl,
        res,
        array,
        mapa,
        array_type=tipo,
        write_to_original=True,
    )


# ── los N_MAX ───────────────────────────────────────────────────────────────


def proc_operaciones_n_max(tabla: str, diff: DiffNMax) -> list[dict[str, Any]]:
    """Las operaciones de N_MAX que hay que aplicar en linea.

    Mismo criterio que ``disp_calcular_operaciones_n_max``: solo las
    constantes que ya existen en TIA y cuyo valor no coincide.

    Args:
        tabla: la tabla del proceso (``"<uid>_<codigo>"``).
        diff: el diff de los N_MAX (``proc_calcular_diff_n_max``).

    Returns:
        La lista de ``{"tabla", "constante", "valor"}``.
    """
    return [
        {
            "tabla": tabla,
            "constante": str(fila["name"]),
            "valor": int(fila["nuevo"]),
        }
        for fila in diff.todos
        if fila["status"] == "actualizar" and str(fila["name"]) in diff.actual
    ]
