"""Builder de slot_maps para comentarios por instancia de DBs de procesos.

Une los datos de AppState (columna ``comentario_db`` de
``ParamRealPLC`` / ``ParamIntPLC`` / ``AlarmaPLC``) con la
configuraciÃ³n TIA y la cache de bloques del PLC para producir el
mapping ``{slot: texto}`` por array (PReal, PInt, ALM) que el
caso de uso envÃ­a al worker.

Es el hermano "procesos" de ``disp_slot_map_builder.py`` (que cubre los
6 DBs de dispositivos ED/EA/SA/V/M/M_VF con slot 0 fijo
"NO USAR"). Las diferencias son:
  - **Sin slot 0.** Los arrays de proceso empiezan en 1.
  - **Parametrizado por array.** Recibe un Ãºnico ``array_name`` por
    llamada (no un ``hw_type``).
  - **3 arrays** por proceso (PReal, PInt, ALM) en lugar de 1.
  - **Cruza con DataBloqueCache** (no con ConfigManager) para verificar
    que el DB/tabla existen en el PLC. Faltan â†’ ``missing_blocks``
    poblado, NO aborta (la SPA muestra el aviso y NO abre la vista
    de diff).

RestricciÃ³n arquitectÃ³nica (``.clinerules`` Â§1): este mÃ³dulo es
OFFLINE; no importa ``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from areas.alimentacion.helpers.sd.proc_comment_updater import (
    strip_enclosing_quotes,
)
from core.runtime.app_state import AppState
from core.infrastructure.config.config_manager import ConfigManager
from core.infrastructure.tia.tia_export_paths import EMPTY_TEXT
from core.data.data_block_cache import DataBloqueCache
from core.data.data_block_plc import DataBloquePLC


_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcSlotMap:
    """Slot maps y metadatos TIA para un proceso.

    Attributes:
        preal: ``{slot: comentario}`` para ``PReal[1..N]``. VacÃ­o si
               no hay parÃ¡metros reales o si ``missing_blocks`` estÃ¡
               poblado.
        pint: ``{slot: comentario}`` para ``PInt[1..N]``. VacÃ­o si
               no hay parÃ¡metros enteros o si ``missing_blocks`` estÃ¡
               poblado.
        alm: ``{slot: comentario}`` para ``ALM[1..N]``. VacÃ­o si no
               hay alarmas o si ``missing_blocks`` estÃ¡ poblado.
        db_param_name: nombre canÃ³nico del DB de parÃ¡metros
                       (``"DB<num_db>_<codigo>_PARAM"``).
        db_alm_name: nombre canÃ³nico del DB de alarmas
                     (``"DB<num_db>_<codigo>_ALM"``).
        table_name: nombre canÃ³nico de la tabla de variables
                    (``"<uid>_<codigo>"``).
        nmax: ``{kind: desired_int}`` con los valores DESEADOS de
              las PlcUserConstant N_MAX del proceso, donde
              ``kind âˆˆ {"preal", "pint", "alm"}``. Cada valor es el
              ``len()`` de la lista filtrada por proceso del Excel
              (``len(excel.parametros_real where codigo == proc.codigo)``
              para ``preal``, etc.). El nombre COMPLETO de la
              PlcUserConstant se computa en el use case como
              ``f"{proc.uid}_N_MAX_{suffix}"`` con el sufijo del
              config. VacÃ­o si el departamento no define
              ``procesos.n_max_suffixes``.
        nmax_names: ``{kind: full_name}`` con los nombres completos
                    ya computados (``"100_N_MAX_PREAL"``, etc.). VacÃ­o
                    si el config no aporta sufijos.
        missing_blocks: lista de mensajes describiendo los bloques
                        ausentes en el ``DataBloqueCache``. VacÃ­a si
                        todo estÃ¡ presente.
        warnings: lista de warnings no fatales (p. ej. ``num_db``
                  fallback al ``proc.uid`` cuando la lista de
                  parÃ¡metros estÃ¡ vacÃ­a).
    """

    preal: dict[int, str] = field(default_factory=dict)
    pint: dict[int, str] = field(default_factory=dict)
    alm: dict[int, str] = field(default_factory=dict)
    db_param_name: str = ""
    db_alm_name: str = ""
    table_name: str = ""
    # Subcarpeta TIA de cada DB dentro de "Bloques de programa"
    # (relativa al root del PLC, con ``\\`` como separator, e.g.
    # ``"ZC_Plantillas\\50010_ProcesoEstandar\\53010_Parametros"``).
    # Se extrae del ``DataBloquePLC.ruta`` cacheado al escanear TIA. Si
    # la cache no tiene la ruta (escaneo fallido), queda ``""`` y el
    # worker escribe los archivos a la raÃ­z de ``exports/`` (legacy).
    # Ver `DataBloqueCacheManager` y la fix del bug de reimport del
    # 2026-09-07 (TIA requiere misma estructura de carpetas para
    # reconciliar el bloque por nombre y hacer UPDATE).
    param_subpath: str = ""
    alm_subpath: str = ""
    nmax: dict[str, int] = field(default_factory=dict)
    nmax_names: dict[str, str] = field(default_factory=dict)
    missing_blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# â”€â”€ Helpers internos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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

    PolÃ­tica:
      - Toma la primera fila que cumple el filtro (codigo ==
        proc.codigo o proceso == proc.nombre segÃºn ``kind_label``).
      - Si la lista estÃ¡ vacÃ­a, **fallback documentado**:
        ``num_db = proc.uid`` con warning. Esto preserva la
        convenciÃ³n legacy donde el DB PARAM se nombraba con
        ``3000 + uid`` cuando no habÃ­a filas explÃ­citas en el Excel.
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
        f"se usa num_db={proc_uid} como fallback (convenciÃ³n legacy)."
    )
    warnings.append(msg)
    _logger.warning(msg)
    return proc_uid


def _build_slot_map(
    parametros: list, proc_field: str, proc_value: str, warnings: list[str]
) -> dict[int, str]:
    """Construye ``{i+1: comentario_db}`` 1-based.

    PolÃ­tica de comentarios vacÃ­os: si ``comentario_db`` es "" o
    ``None``, se mapea a ``"."`` (convenciÃ³n TIA "sin comentario")
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
        # las quitamos aquÃ­. Si no, el diff dirÃ­a "renombrar" siempre
        # que el desired (Excel) tenga comillas y el current (TIA)
        # no â€” un falso positivo. La misma limpieza se hace en el
        # lado TIA (``ProcCommentUpdater._build_mlc_text_map``)
        # y en el apply (``_sanitize_comment_text``).
        comentario = strip_enclosing_quotes(comentario)
        if not comentario.strip():
            _logger.warning(
                f"ParÃ¡metro sin comentario_db (Excel vacÃ­o); "
                f"se mapea a '.' (Ã­ndice {i + 1})."
            )
            comentario = EMPTY_TEXT
        slot_map[i + 1] = comentario
    return slot_map


# â”€â”€ API pÃºblica â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def proc_build_slot_maps(
    app_state: AppState,
    config_manager: ConfigManager,
    proc_uid: int,
    bloques_cache: DataBloqueCache,
) -> ProcSlotMap:
    """Cruza Excel + DataBloqueCache + config para producir los slot maps.

    Raises:
        RuntimeError: si ``app_state.excel_cache`` es ``None`` o si
                      ``proc_uid`` no estÃ¡ en ``excel_cache.procesos``.
                      Mensaje accionable: "Cargue primero el Excel
                      con POST /api/v1/excel/upload" o
                      "El proceso {uid} no estÃ¡ en el Excel cargado".

    PolÃ­tica de precondiciones:
      - Si falta alguno de los 3 bloques (DB_PARAM, DB_ALM, tabla)
        en el ``DataBloqueCache``, la funciÃ³n aÃ±ade el nombre a
        ``missing_blocks`` y retorna con los 3 dicts vacÃ­os
        (NO lanza). La SPA pinta el aviso y bloquea la vista de diff.
    """
    excel_cache = app_state.excel_cache
    if excel_cache is None:
        raise RuntimeError(
            "excel_cache estÃ¡ vacÃ­o. Cargue primero el Excel con "
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
            f"El proceso con uid={proc_uid} no estÃ¡ en el Excel cargado. "
            "Recargue el Excel o seleccione otro proceso."
        )

    warnings: list[str] = []

    # Nombres canÃ³nicos TIA.
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

    # Verificar precondiciones contra el DataBloqueCache.
    missing_blocks: list[str] = []
    if DataBloquePLC.normalize_name(db_param_name) not in bloques_cache.blocks:
        missing_blocks.append(f"DB de parÃ¡metros: {db_param_name}")
    if DataBloquePLC.normalize_name(db_alm_name) not in bloques_cache.blocks:
        missing_blocks.append(f"DB de alarmas: {db_alm_name}")
    if DataBloquePLC.normalize_name(table_name) not in bloques_cache.tag_tables:
        missing_blocks.append(f"Tabla de variables: {table_name}")

    # Extraer la subcarpeta TIA de cada DB del ``DataBloqueCache``. TIA
    # Portal V21 requiere que el archivo se reimporte en la MISMA
    # ruta donde ya existe el bloque; si lo importamos a la raÃ­z,
    # falla con "object with the name already exists" (validado
    # 2026-09-07). La ruta se cachea al escanear TIA en
    # ``DataBloquePLC.ruta`` (jerarquÃ­a con ``\\`` separator). Si la
    # cache estÃ¡ vacÃ­a o el valor es ``""`` (no se pudo escanear
    # la ruta), dejamos el subpath como ``""`` y el worker cae al
    # comportamiento legacy (raÃ­z de ``exports/``).
    def _extract_subpath(key: str) -> str:
        val = bloques_cache.blocks.get(key, "")
        # Tests legacy pueden pasar un string directamente como
        # valor (atajo en lugar de un ``DataBloquePLC`` completo).
        if isinstance(val, str):
            return val
        return getattr(val, "ruta", "")

    param_key = DataBloquePLC.normalize_name(db_param_name)
    param_subpath = _extract_subpath(param_key)
    alm_key = DataBloquePLC.normalize_name(db_alm_name)
    alm_subpath = _extract_subpath(alm_key)

    if missing_blocks:
        # NO abortamos: devolvemos el slot map con missing_blocks
        # poblado y los 3 dicts vacÃ­os. La SPA pinta el aviso.
        return ProcSlotMap(
            preal={}, pint={}, alm={},
            db_param_name=db_param_name,
            db_alm_name=db_alm_name,
            table_name=table_name,
            param_subpath=param_subpath,
            alm_subpath=alm_subpath,
            missing_blocks=missing_blocks,
            warnings=warnings,
        )

    # Precondiciones OK: cruzamos Excel â†’ slot maps.
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
    # Cada N_MAX se computa como el nÂº de filas del Excel para este
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

    return ProcSlotMap(
        preal=preal,
        pint=pint,
        alm=alm,
        db_param_name=db_param_name,
        db_alm_name=db_alm_name,
        table_name=table_name,
        param_subpath=param_subpath,
        alm_subpath=alm_subpath,
        nmax=nmax_desired,
        nmax_names=nmax_names,
        missing_blocks=missing_blocks,
        warnings=warnings,
    )


__all__ = ["ProcSlotMap", "proc_build_slot_maps"]
