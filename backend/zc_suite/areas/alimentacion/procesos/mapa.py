"""zc_suite.areas.alimentacion.procesos.mapa — el mapa de slots de un proceso.

Los nombres canonicos TIA, los mapas de slots por array y los N_MAX de un
proceso, cruzando el Excel con el escaneo del PLC.

Es logica pura: no habla con el portal de TIA y no abre transacciones. El FB
que la usa es ``../funciones/procesos/generar_prevision.py``.

El port de ``main`` (``areas/alimentacion/data/data_proc_slot_map.py``) con
los mismos criterios:

- ``DB_PARAM`` es ``DB<num_db>_<codigo>_PARAM`` y ``DB_ALM`` es
  ``DB<num_db>_<codigo>_ALM``. El ``num_db`` sale de la **primera** fila que
  pasa el filtro (comparacion exacta, sin ``strip``): ``ParametrosReales``
  con ese ``codigo`` para el DB de parametros y ``Alarmas`` con ese
  ``proceso == nombre`` para el DB de alarmas. El DB_PARAM **solo** mira a
  ``ParametrosReales`` (como ``main``), aunque PInt comparta ese DB.
- Sin filas que pasen el filtro, ``num_db = uid`` del proceso (convencion
  legacy) y un aviso.
- La tabla de variables del proceso es ``<uid>_<codigo>``.
- Cada slot map empieza en ``0`` con el placeholder ``"NO USAR"``: las
  filas con ``numero <= 0`` se descartan y las demas se numeran ``1..N`` en
  el orden del Excel.
- El ``comentario_db`` vacio se mapea a ``"."`` (convencion TIA "sin
  comentario") y se avisa por el logger.
- Los N_MAX son constantes de la tabla del proceso: el nombre es
  ``<uid>_N_MAX_<SUFIXO>`` (los sufijos salen del config) y el valor es la
  **columna del proceso** del Excel (``preal``, ``pint``, ``alarmas``,
  ``alm_hmi``), no el numero de filas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: El comentario del placeholder del slot 0: no se usa.
COMENTARIO_SLOT_CERO = "NO USAR"

#: El comentario TIA de "sin comentario": el slot se borra con el.
COMENTARIO_VACIO = "."

#: Los sufijos de N_MAX del config y la columna del proceso que los alimenta.
#: El orden es el de las tarjetas de N_MAX.
N_MAX_PROCESO: tuple[tuple[str, str, str], ...] = (
    ("preal", "PREAL", "preal"),
    ("pint", "PINT", "pint"),
    ("alm", "ALM", "alarmas"),
    ("alm_hmi", "ALM_HMI", "alm_hmi"),
)


@dataclass(frozen=True)
class MapaProceso:
    """Los slot maps y metadatos TIA de un proceso.

    Attributes:
        preal: ``{slot: comentario}`` del array ``PReal`` (1-based). Vacio
            sin filas del Excel o sin tabla en el PLC.
        pint: ``{slot: comentario}`` del array ``PInt``.
        alm: ``{slot: comentario}`` del array ``ALM``.
        db_param_name: nombre canonico del DB de parametros
            (``"DB<num_db>_<codigo>_PARAM"``).
        db_alm_name: nombre canonico del DB de alarmas
            (``"DB<num_db>_<codigo>_ALM"``).
        table_name: nombre canonico de la tabla de variables
            (``"<uid>_<codigo>"``).
        nmax: ``{sufijo: valor_deseado}`` con los N_MAX del Excel.
        nmax_names: ``{sufijo: nombre_TIA}`` (``"<uid>_N_MAX_<SUFIXO>"``).
        table_present: ``True`` si la tabla esta en el escaneo.
        db_missing: los DBs (DB_PARAM / DB_ALM) que no estan en el escaneo.
        missing_blocks: mensajes de los bloques ausentes. Vacio si todo
            esta presente.
        warnings: avisos no fatales.
    """

    preal: dict[int, str] = field(default_factory=dict)
    pint: dict[int, str] = field(default_factory=dict)
    alm: dict[int, str] = field(default_factory=dict)
    db_param_name: str = ""
    db_alm_name: str = ""
    table_name: str = ""
    nmax: dict[str, int] = field(default_factory=dict)
    nmax_names: dict[str, str] = field(default_factory=dict)
    table_present: bool = True
    db_missing: list[str] = field(default_factory=list)
    missing_blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── el num_db y los nombres ─────────────────────────────────────────────────


def _num_db_de(
    filas: list[dict[str, Any]],
    campo: str,
    valor: str,
    proc_uid: int,
    etiqueta: str,
    warnings: list[str],
) -> int:
    """El ``num_db`` de la primera fila que pasa el filtro.

    El filtro es una comparacion exacta (sin ``strip``), como ``main``.
    Sin filas que pasen el filtro, ``num_db = uid`` del proceso
    (convencion legacy) y un aviso.
    """
    filtradas = [
        fila for fila in filas if str(fila.get(campo, "") or "") == valor
    ]
    if filtradas:
        return int(filtradas[0].get("num_db", 0) or 0)
    msg = (
        f"Proceso uid={proc_uid} ({etiqueta}): no hay filas en el Excel; "
        f"se usa num_db={proc_uid} como fallback (convencion legacy)."
    )
    warnings.append(msg)
    logger.warning(msg)
    return proc_uid


def _nombres(
    proceso: dict[str, Any],
    preal_filas: list[dict[str, Any]],
    alarmas: list[dict[str, Any]],
    proc_uid: int,
    warnings: list[str],
) -> tuple[str, str, str]:
    """Los nombres canonicos TIA: DB_PARAM, DB_ALM y la tabla.

    El ``num_db`` del DB_PARAM sale **solo** de ``ParametrosReales`` (como
    ``main``), aunque PInt comparta ese mismo DB.
    """
    codigo = str(proceso.get("codigo", "") or "")
    nombre = str(proceso.get("nombre", "") or "")

    num_db_param = _num_db_de(
        preal_filas,
        campo="codigo",
        valor=codigo,
        proc_uid=proc_uid,
        etiqueta="PReal/PInt",
        warnings=warnings,
    )
    num_db_alm = _num_db_de(
        alarmas,
        campo="proceso",
        valor=nombre,
        proc_uid=proc_uid,
        etiqueta="ALM",
        warnings=warnings,
    )
    return (
        f"DB{num_db_param}_{codigo}_PARAM",
        f"DB{num_db_alm}_{codigo}_ALM",
        f"{proc_uid}_{codigo}",
    )


# ── los mapas de slots ───────────────────────────────────────────────────────


def _mapa_de_slots(
    filas: list[dict[str, Any]],
    campo: str,
    valor: str,
) -> dict[int, str]:
    """El mapa ``{0: "NO USAR", 1..N: comentario}`` de un array.

    El slot ``0`` es el placeholder ``"NO USAR"`` (estandar ``disp_*``).
    Las filas con ``numero <= 0`` se descartan (la macro del operario
    genera la fila "NO USAR" con ``Numero=0``) y las demas se numeran
    ``1..N`` en el orden del Excel. El ``comentario_db`` vacio se mapea a
    ``"."`` con aviso al logger.
    """
    filtradas = [
        fila for fila in filas if str(fila.get(campo, "") or "") == valor
    ]
    filtradas = [
        fila for fila in filtradas if int(fila.get("numero", 0) or 0) > 0
    ]
    mapa: dict[int, str] = {0: COMENTARIO_SLOT_CERO}
    for i, fila in enumerate(filtradas):
        comentario = str(fila.get("comentario_db", "") or "")
        if not comentario.strip():
            logger.warning(
                "Parametro sin comentario_db (Excel vacio); "
                f"se mapea a '.' (indice {i + 1})."
            )
            comentario = COMENTARIO_VACIO
        mapa[i + 1] = comentario
    return mapa


# ── los N_MAX ────────────────────────────────────────────────────────────────


def _nmax_de(
    proceso: dict[str, Any],
    proc_uid: int,
    sufijos: dict[str, str],
) -> tuple[dict[str, int], dict[str, str]]:
    """Los N_MAX del proceso: valores del Excel y nombres TIA.

    El valor es la **columna del proceso** del Excel, no el numero de filas:
    dimensionar el array por ``len(slot_map)`` desfasaba N_MAX cuando el
    Excel tenia filas extra o cambios en el conteo.
    """
    valores: dict[str, int] = {}
    nombres: dict[str, str] = {}
    for sufijo, _columna_default, columna in N_MAX_PROCESO:
        sufijo_config = sufijos.get(sufijo)
        if sufijo_config is None:
            continue
        valores[sufijo] = int(proceso.get(columna, 0) or 0)
        nombres[sufijo] = f"{proc_uid}_N_MAX_{sufijo_config}"
    return valores, nombres


# ── la presencia en el PLC ───────────────────────────────────────────────────


def _normalizar(nombre: str) -> str:
    """El nombre de un bloque o tabla sin distinguir mayusculas."""
    return nombre.strip().upper()


def _presencia(
    db_param_name: str,
    db_alm_name: str,
    table_name: str,
    bloques: list[dict[str, Any]],
    tablas: list[dict[str, Any]],
) -> tuple[bool, list[str], list[str]]:
    """Cruza los nombres con el escaneo.

    Returns:
        La tupla ``(table_present, db_missing, missing_blocks)``.
    """
    nombres_bloques = {_normalizar(str(b.get("nombre", ""))) for b in bloques}
    nombres_tablas = {_normalizar(str(t.get("nombre", ""))) for t in tablas}

    table_present = _normalizar(table_name) in nombres_tablas
    db_missing: list[str] = []
    if _normalizar(db_param_name) not in nombres_bloques:
        db_missing.append(db_param_name)
    if _normalizar(db_alm_name) not in nombres_bloques:
        db_missing.append(db_alm_name)

    missing_blocks: list[str] = []
    if not table_present:
        missing_blocks.append(f"Tabla de variables: {table_name}")
    if db_param_name in db_missing:
        missing_blocks.append(f"DB de parametros: {db_param_name}")
    if db_alm_name in db_missing:
        missing_blocks.append(f"DB de alarmas: {db_alm_name}")
    return table_present, db_missing, missing_blocks


# ── la API publica ───────────────────────────────────────────────────────────


def proc_nombres(
    proceso: dict[str, Any],
    preal_filas: list[dict[str, Any]],
    alarmas: list[dict[str, Any]],
    proc_uid: int,
    warnings: list[str] | None = None,
) -> tuple[str, str, str]:
    """Los nombres canonicos TIA del proceso: DB_PARAM, DB_ALM y la tabla.

    El ``num_db`` del DB_PARAM sale solo de ``ParametrosReales`` (como
    ``main``), aunque PInt comparta ese mismo DB.

    Args:
        proceso: la fila del proceso del Excel (``codigo``, ``nombre``...).
        preal_filas: las filas de ``ParametrosReales`` del Excel.
        alarmas: las filas de ``Alarmas`` del Excel.
        proc_uid: el ``uid`` del proceso.
        warnings: la lista de avisos que se anade el fallback de ``num_db``.

    Returns:
        La tupla ``(db_param, db_alm, tabla)``.
    """
    avisos = warnings if warnings is not None else []
    return _nombres(proceso, preal_filas, alarmas, proc_uid, avisos)


def proc_mapa_de_slots(
    preal_filas: list[dict[str, Any]],
    pint_filas: list[dict[str, Any]],
    alm_filas: list[dict[str, Any]],
    codigo: str,
    nombre: str,
) -> dict[str, dict[int, str]]:
    """Los mapas de slots del proceso, por array.

    Args:
        preal_filas: las filas de ``ParametrosReales`` del Excel.
        pint_filas: las filas de ``ParametrosEnteros`` del Excel.
        alm_filas: las filas de ``Alarmas`` del Excel.
        codigo: el ``codigo`` del proceso (filtro de PReal y PInt).
        nombre: el ``nombre`` del proceso (filtro de ALM).

    Returns:
        ``{"preal": {slot: comentario}, "pint": {...}, "alm": {...}}``.
    """
    return {
        "preal": _mapa_de_slots(preal_filas, "codigo", codigo),
        "pint": _mapa_de_slots(pint_filas, "codigo", codigo),
        "alm": _mapa_de_slots(alm_filas, "proceso", nombre),
    }


def proc_nmax(
    proceso: dict[str, Any],
    proc_uid: int,
    sufijos: dict[str, str],
) -> tuple[dict[str, int], dict[str, str]]:
    """Los N_MAX del proceso: valores del Excel y nombres TIA.

    Args:
        proceso: la fila del proceso del Excel (``preal``, ``pint``,
            ``alarmas``, ``alm_hmi``...).
        proc_uid: el ``uid`` del proceso.
        sufijos: los sufijos de N_MAX del config
            (``procesos.sufijos_nmax``).

    Returns:
        La tupla ``(valores, nombres)``.
    """
    return _nmax_de(proceso, proc_uid, sufijos)


def proc_construir_mapa(
    proceso: dict[str, Any],
    preal_filas: list[dict[str, Any]],
    pint_filas: list[dict[str, Any]],
    alm_filas: list[dict[str, Any]],
    sufijos: dict[str, str],
    bloques: list[dict[str, Any]],
    tablas: list[dict[str, Any]],
) -> MapaProceso:
    """Cruza el Excel y el escaneo para producir el mapa de un proceso.

    Args:
        proceso: la fila del proceso del Excel.
        preal_filas: las filas de ``ParametrosReales`` del Excel.
        pint_filas: las filas de ``ParametrosEnteros`` del Excel.
        alm_filas: las filas de ``Alarmas`` del Excel.
        sufijos: los sufijos de N_MAX del config
            (``procesos.sufijos_nmax``).
        bloques: los bloques del escaneo (``{"nombre", ...}``).
        tablas: las tablas del escaneo (``{"nombre", ...}``).

    Returns:
        El ``MapaProceso`` con los nombres, los slot maps, los N_MAX y la
        presencia en el PLC.
    """
    proc_uid = int(proceso.get("uid", 0) or 0)
    codigo = str(proceso.get("codigo", "") or "")
    nombre = str(proceso.get("nombre", "") or "")

    warnings: list[str] = []
    db_param, db_alm, tabla = _nombres(
        proceso, preal_filas, alm_filas, proc_uid, warnings
    )
    slots = proc_mapa_de_slots(preal_filas, pint_filas, alm_filas, codigo, nombre)
    table_present, db_missing, missing_blocks = _presencia(
        db_param, db_alm, tabla, bloques, tablas
    )

    # Sin tabla no hay N_MAX ni slot maps: el FB de sync aborta antes.
    if not table_present:
        return MapaProceso(
            db_param_name=db_param,
            db_alm_name=db_alm,
            table_name=tabla,
            table_present=False,
            db_missing=list(db_missing),
            missing_blocks=missing_blocks,
            warnings=warnings,
        )

    nmax, nmax_names = _nmax_de(proceso, proc_uid, sufijos)

    return MapaProceso(
        preal=slots["preal"],
        pint=slots["pint"],
        alm=slots["alm"],
        db_param_name=db_param,
        db_alm_name=db_alm,
        table_name=tabla,
        nmax=nmax,
        nmax_names=nmax_names,
        table_present=True,
        db_missing=list(db_missing),
        missing_blocks=missing_blocks,
        warnings=warnings,
    )


def proc_precondiciones_ok(mapa: MapaProceso) -> bool:
    """``True`` si el proceso se puede sincronizar.

    Falta la tabla, o faltan **los dos** DBs, y no se puede aplicar nada.
    Falta un DB solo y se sigue: el sync omite ese DB.
    """
    if not mapa.table_present:
        return False
    faltan_ambos = (
        mapa.db_param_name in mapa.db_missing
        and mapa.db_alm_name in mapa.db_missing
    )
    return not faltan_ambos


def proc_falta_db(mapa: MapaProceso, db: str) -> str:
    """El mensaje de un DB ausente en el PLC.

    Usado por el sync y por la prevision para que el operario vea el mismo
    texto en ambos lados.
    """
    if db == mapa.db_param_name:
        kind = "parametros"
    elif db == mapa.db_alm_name:
        kind = "alarmas"
    else:
        kind = "?"
    return f"DB de {kind} no existe en el PLC; se omite esa sincronizacion: {db}"
