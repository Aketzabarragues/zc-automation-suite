"""Builder de slot_maps para comentarios por instancia de DBs de procesos.

Une los datos de AppState (columna ``comentario_db`` de
``ParamRealPLC`` / ``ParamIntPLC`` / ``AlarmaPLC``) con la
configuración TIA y la cache de bloques del PLC para producir el
mapping ``{slot: texto}`` por array (PReal, PInt, ALM) que el
caso de uso envía al worker.

Es el hermano "procesos" de ``slot_map_builder.py`` (que cubre los
6 DBs de dispositivos ED/EA/SA/V/M/M_VF con slot 0 fijo
"NO USAR"). Las diferencias son:
  - **Sin slot 0.** Los arrays de proceso empiezan en 1.
  - **Parametrizado por array.** Recibe un único ``array_name`` por
    llamada (no un ``hw_type``).
  - **3 arrays** por proceso (PReal, PInt, ALM) en lugar de 1.
  - **Cruza con BloqueCache** (no con ConfigManager) para verificar
    que el DB/tabla existen en el PLC. Faltan → ``missing_blocks``
    poblado, NO aborta (la SPA muestra el aviso y NO abre la vista
    de diff).

Restricción arquitectónica (``.clinerules`` §1): este módulo es
OFFLINE; no importa ``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from areas.alimentacion.infrastructure.sd.proc_comment_updater import (
    strip_enclosing_quotes,
)
from core.application.state import AppState
from core.infrastructure.config_manager import ConfigManager
from core.models.bloque_cache import BloqueCache
from core.models.bloque_plc import BloquePLC


_logger = logging.getLogger(__name__)


# Texto que se escribe cuando ``comentario_db`` está vacío (convención
# TIA "sin comentario"; ver ``DispCommentUpdater._EMPTY_TEXT``).
_EMPTY_TEXT: str = "."


@dataclass(frozen=True)
class ProcesoSlotMap:
    """Slot maps y metadatos TIA para un proceso.

    Attributes:
        preal: ``{slot: comentario}`` para ``PReal[1..N]``. Vacío si
               no hay parámetros reales o si ``missing_blocks`` está
               poblado.
        pint: ``{slot: comentario}`` para ``PInt[1..N]``. Vacío si
               no hay parámetros enteros o si ``missing_blocks`` está
               poblado.
        alm: ``{slot: comentario}`` para ``ALM[1..N]``. Vacío si no
               hay alarmas o si ``missing_blocks`` está poblado.
        db_param_name: nombre canónico del DB de parámetros
                       (``"DB<num_db>_<codigo>_PARAM"``).
        db_alm_name: nombre canónico del DB de alarmas
                     (``"DB<num_db>_<codigo>_ALM"``).
        table_name: nombre canónico de la tabla de variables
                    (``"<uid>_<codigo>"``).
        nmax: ``{kind: desired_int}`` con los valores DESEADOS de
              las PlcUserConstant N_MAX del proceso, donde
              ``kind ∈ {"preal", "pint", "alm"}``. Cada valor es el
              ``len()`` de la lista filtrada por proceso del Excel
              (``len(excel.parametros_real where codigo == proc.codigo)``
              para ``preal``, etc.). El nombre COMPLETO de la
              PlcUserConstant se computa en el use case como
              ``f"{proc.uid}_N_MAX_{suffix}"`` con el sufijo del
              config. Vacío si el departamento no define
              ``procesos.n_max_suffixes``.
        nmax_names: ``{kind: full_name}`` con los nombres completos
                    ya computados (``"100_N_MAX_PREAL"``, etc.). Vacío
                    si el config no aporta sufijos.
        missing_blocks: lista de mensajes describiendo los bloques
                        ausentes en el ``BloqueCache``. Vacía si
                        todo está presente.
        warnings: lista de warnings no fatales (p. ej. ``num_db``
                  fallback al ``proc.uid`` cuando la lista de
                  parámetros está vacía).
    """

    preal: dict[int, str] = field(default_factory=dict)
    pint: dict[int, str] = field(default_factory=dict)
    alm: dict[int, str] = field(default_factory=dict)
    db_param_name: str = ""
    db_alm_name: str = ""
    table_name: str = ""
    nmax: dict[str, int] = field(default_factory=dict)
    nmax_names: dict[str, str] = field(default_factory=dict)
    missing_blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── Helpers internos ────────────────────────────────────────────────────


def _resolve_num_db(
    parametros: list,  # Iterable[ParamRealPLC | ParamIntPLC | AlarmaPLC]
    codigo: str,
    proc_field: str,
    proc_value: str,
    proc_uid: int,
    warnings: list[str],
    kind_label: str,
) -> int:
    """Resuelve el ``num_db`` a usar para nombrar el DB de un proceso.

    Política:
      - Toma la primera fila que cumple el filtro (codigo ==
        proc.codigo o proceso == proc.nombre según ``kind_label``).
      - Si la lista está vacía, **fallback documentado**:
        ``num_db = proc.uid`` con warning. Esto preserva la
        convención legacy donde el DB PARAM se nombraba con
        ``3000 + uid`` cuando no había filas explícitas en el Excel.
    """
    if proc_field == "codigo":
        filtered = [p for p in parametros if getattr(p, "codigo", "") == codigo]
    else:
        filtered = [
            p for p in parametros if getattr(p, "proceso", "") == proc_value
        ]
    if filtered:
        return int(getattr(filtered[0], "num_db", 0) or 0)
    # Fallback.
    msg = (
        f"Proceso uid={proc_uid} ({kind_label}): no hay filas en el Excel; "
        f"se usa num_db={proc_uid} como fallback (convención legacy)."
    )
    warnings.append(msg)
    _logger.warning(msg)
    return proc_uid


def _build_slot_map(
    parametros: list, proc_field: str, proc_value: str, warnings: list[str]
) -> dict[int, str]:
    """Construye ``{i+1: comentario_db}`` 1-based.

    Política de comentarios vacíos: si ``comentario_db`` es "" o
    ``None``, se mapea a ``"."`` (convención TIA "sin comentario")
    con warning al logger.
    """
    if proc_field == "codigo":
        filtered = [p for p in parametros if getattr(p, "codigo", "") == proc_value]
    else:
        filtered = [
            p for p in parametros if getattr(p, "proceso", "") == proc_value
        ]
    slot_map: dict[int, str] = {}
    for i, p in enumerate(filtered):
        comentario = str(getattr(p, "comentario_db", "") or "")
        # Si el operario pega el comentario del Excel con comillas
        # envolventes por error (p. ej. ``'COMPACTO - FIJOS - '``),
        # las quitamos aquí. Si no, el diff diría "renombrar" siempre
        # que el desired (Excel) tenga comillas y el current (TIA)
        # no — un falso positivo. La misma limpieza se hace en el
        # lado TIA (``ProcesoCommentUpdater._build_mlc_text_map``)
        # y en el apply (``_sanitize_comment_text``).
        comentario = strip_enclosing_quotes(comentario)
        if not comentario.strip():
            _logger.warning(
                f"Parámetro sin comentario_db (Excel vacío); "
                f"se mapea a '.' (índice {i + 1})."
            )
            comentario = _EMPTY_TEXT
        slot_map[i + 1] = comentario
    return slot_map


# ── API pública ──────────────────────────────────────────────────────────


def build_proceso_slot_maps(
    app_state: AppState,
    config_manager: ConfigManager,
    proc_uid: int,
    bloques_cache: BloqueCache,
) -> ProcesoSlotMap:
    """Cruza Excel + BloqueCache + config para producir los slot maps.

    Raises:
        RuntimeError: si ``app_state.excel_cache`` es ``None`` o si
                      ``proc_uid`` no está en ``excel_cache.procesos``.
                      Mensaje accionable: "Cargue primero el Excel
                      con POST /api/v1/excel/upload" o
                      "El proceso {uid} no está en el Excel cargado".

    Política de precondiciones:
      - Si falta alguno de los 3 bloques (DB_PARAM, DB_ALM, tabla)
        en el ``BloqueCache``, la función añade el nombre a
        ``missing_blocks`` y retorna con los 3 dicts vacíos
        (NO lanza). La SPA pinta el aviso y bloquea la vista de diff.
    """
    excel_cache = app_state.excel_cache
    if excel_cache is None:
        raise RuntimeError(
            "excel_cache está vacío. Cargue primero el Excel con "
            "POST /api/v1/excel/upload."
        )

    # Buscar el proceso por uid.
    proc = None
    for p in excel_cache.procesos:
        if int(p.uid) == int(proc_uid):
            proc = p
            break
    if proc is None:
        raise RuntimeError(
            f"El proceso con uid={proc_uid} no está en el Excel cargado. "
            "Recargue el Excel o seleccione otro proceso."
        )

    warnings: list[str] = []

    # Nombres canónicos TIA.
    num_db_param = _resolve_num_db(
        list(excel_cache.parametros_real),
        codigo=proc.codigo,
        proc_field="codigo",
        proc_value=proc.codigo,
        proc_uid=proc_uid,
        warnings=warnings,
        kind_label="PReal/PInt",
    )
    db_param_name = f"DB{num_db_param}_{proc.codigo}_PARAM"

    num_db_alm = _resolve_num_db(
        list(excel_cache.alarmas),
        codigo=proc.codigo,
        proc_field="proceso",
        proc_value=proc.nombre,
        proc_uid=proc_uid,
        warnings=warnings,
        kind_label="ALM",
    )
    db_alm_name = f"DB{num_db_alm}_{proc.codigo}_ALM"

    table_name = f"{proc_uid}_{proc.codigo}"

    # Verificar precondiciones contra el BloqueCache.
    missing_blocks: list[str] = []
    if BloquePLC.normalize_name(db_param_name) not in bloques_cache.blocks:
        missing_blocks.append(f"DB de parámetros: {db_param_name}")
    if BloquePLC.normalize_name(db_alm_name) not in bloques_cache.blocks:
        missing_blocks.append(f"DB de alarmas: {db_alm_name}")
    if BloquePLC.normalize_name(table_name) not in bloques_cache.tag_tables:
        missing_blocks.append(f"Tabla de variables: {table_name}")

    if missing_blocks:
        # NO abortamos: devolvemos el slot map con missing_blocks
        # poblado y los 3 dicts vacíos. La SPA pinta el aviso.
        return ProcesoSlotMap(
            preal={}, pint={}, alm={},
            db_param_name=db_param_name,
            db_alm_name=db_alm_name,
            table_name=table_name,
            missing_blocks=missing_blocks,
            warnings=warnings,
        )

    # Precondiciones OK: cruzamos Excel → slot maps.
    preal = _build_slot_map(
        list(excel_cache.parametros_real),
        proc_field="codigo",
        proc_value=proc.codigo,
        warnings=warnings,
    )
    pint = _build_slot_map(
        list(excel_cache.parametros_int),
        proc_field="codigo",
        proc_value=proc.codigo,
        warnings=warnings,
    )
    alm = _build_slot_map(
        list(excel_cache.alarmas),
        proc_field="proceso",
        proc_value=proc.nombre,
        warnings=warnings,
    )

    # N_MAX deseados (solo visual, no se aplican en el commit actual).
    # Cada N_MAX se computa como el nº de filas del Excel para este
    # proceso, y el nombre completo de la PlcUserConstant se deriva
    # del uid del proceso + el sufijo del config
    # (``f"{proc.uid}_N_MAX_{suffix}"``).
    suffixes = config_manager.get_proc_nmax_suffixes()
    nmax_desired: dict[str, int] = {}
    nmax_names: dict[str, str] = {}
    if suffixes:
        nmax_desired["preal"] = len(preal)
        nmax_desired["pint"] = len(pint)
        nmax_desired["alm"] = len(alm)
        for kind, suffix in suffixes.items():
            nmax_names[kind] = f"{proc_uid}_N_MAX_{suffix}"

    return ProcesoSlotMap(
        preal=preal,
        pint=pint,
        alm=alm,
        db_param_name=db_param_name,
        db_alm_name=db_alm_name,
        table_name=table_name,
        nmax=nmax_desired,
        nmax_names=nmax_names,
        missing_blocks=missing_blocks,
        warnings=warnings,
    )


__all__ = ["ProcesoSlotMap", "build_proceso_slot_maps"]
