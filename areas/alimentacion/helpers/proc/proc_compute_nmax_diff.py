"""Helper puro: diff de N_MAX para el sync de procesos.

Calcula las ops de N_MAX que el handler ``commit_user_constants_online``
aplicara a la **tabla de variables del proceso** (``slot_map.table_name``
= ``f"{proc_uid}_{proc.codigo}"``) cuando el usuario quiere que TIA
redimensione los DBs PARAM / ALM antes del sync de comentarios.

reescritura despues del bug N_MAX diff=0 en produccion. La
version anterior copio el patron de ``disp_compute_nmax_diff`` que lee
la tabla global ``000_Config_Dispositivos`` (tabla de dispositivos),
pero los N_MAX de proc viven en la tabla del PROCESO por convencion
del operario (2026-09-02, validado en ``proc_generate_preview.py``).

Forma del retorno:
    [{"table_name": str, "constant_name": str, "new_value": int}, ...]

 (correccion): si la tabla del proceso NO esta exportada en
``tags_base`` (ej. el operario lanzo el commit sin hacer preview antes),
el helper lanza ``RuntimeError`` en lugar de retornar ``[]``. Razon: si
no tenemos estado actual fiable, no debemos fabricar ops basados en
``current={}`` (que produciria diffs espurios cuando desired != 0).
El FB atrapa el error y aborta con un mensaje accionable ("ejecuta
el preview antes del commit").

El FB que lo consume despacha SIEMPRE el handler (``sync_nmax`` es
incondicional) con la lista resultante (puede ser ``[]`` si desired ==
current; es distinto de "no se puede verificar").
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def proc_compute_nmax_diff(
    tags_base: Path,
    proc_uid: int,
    slot_map: Any,
) -> list[dict[str, Any]]:
    """Difiere los N_MAX del proceso contra el estado exportado de TIA.

    Args:
        tags_base: Carpeta donde TIA (via preview) exporto la tabla de
            variables del proceso. Tipicamente
            ``build_cache.procesos.preview_variables``.
        proc_uid: UID del proceso (para mensajes accionables de error).
        slot_map: ``DataProcSlotMap`` con:
          - ``table_name``: nombre canonico de la tabla del proceso.
          - ``nmax``: dict ``{kind: int}`` de desired (lo que dice el Excel).
            Tipicamente ``{"preal": N, "pint": M, "alm": K}``.
          - ``nmax_names``: dict ``{kind: str}`` con los nombres completos
            en TIA. Tipicamente
            ``{"preal": "100_N_MAX_PREAL", "pint": "100_N_MAX_PINT", ...}``.

    Returns:
        Lista de ops listas para ``commit_user_constants_online``.
        Lista vacia si todos los N_MAX ya coinciden con el estado
        exportado.

    Raises:
        RuntimeError: Si ``slot_map`` es None o ``table_name`` vacio,
            si no hay ``nmax_names`` en config, o si el XML de la tabla
            no existe en ``tags_base`` (preview no se ejecuto o tabla
            ausente en TIA).
    """
    from core.helpers.simatic_ml import PlcUserConstantParser

    # ── Fail-fast ──
    if slot_map is None:
        raise RuntimeError(
            "proc_compute_nmax_diff: slot_map es None. El step "
            "'build_slot_maps_commit' no se ejecuto (o fallo)."
        )
    table_name = getattr(slot_map, "table_name", "") or ""
    if not table_name:
        raise RuntimeError(
            f"proc_compute_nmax_diff: slot_map.table_name vacio. "
            f"¿proc_uid={proc_uid} existe en AppState?"
        )
    nmax_names: dict[str, str] = (
        getattr(slot_map, "nmax_names", {}) or {}
    )
    if not nmax_names:
        raise RuntimeError(
            f"proc_compute_nmax_diff: config_manager no aporta "
            f"procesos.n_max_suffixes para proc_uid={proc_uid}. "
            f"Revisa config/defaults.py."
        )

    # Usamos ``XmlTarget`` en vez del lookup directo ``tags_base /
    # f"{table}.xml"``. Razon: TIA Portal V21, con
    # ``keep_folder_structure=True`` (configurado en
    # ``tia_helpers.py:328``), deposita el .xml en un subdirectorio
    # ``Tags/`` (no en la raiz). El preview usa ``XmlTarget`` (busca
    # primero directo y luego con ``rglob``) — el sync debe usar la
    # misma abstraccion para no diverger.
    from core.infrastructure.tia.tia_export_paths import XmlTarget

    try:
        xml_path = XmlTarget(tags_base, table_name).path
    except FileNotFoundError:
        # Mensaje con dos hints: el path "esperado" directo Y el
        # tags_base para que el operario vea donde mirar.
        raise RuntimeError(
            f"Tabla de variables del proceso {proc_uid} no exportada: "
            f"{tags_base}/{table_name}.xml (ni directo ni con rglob). "
            f"Ejecuta POST /api/v1/procesos/sync/preview antes del "
            f"commit, o revisa que el PLC tenga la tabla {table_name}."
        )

    # ── Parse current ──
    try:
        current: dict[str, int] = PlcUserConstantParser.parse_user_constants(
            xml_path
        )
    except Exception as e:
        raise RuntimeError(
            f"proc_compute_nmax_diff: parseo de {xml_path} fallo: {e!r}. "
            f"¿XML corrupto o sin permisos de lectura?"
        ) from e

    # ── Diff: desired = slot_map.nmax[kind], current = current[nmax_names[kind]] ──
    nmax_desired: dict[str, int] = (
        getattr(slot_map, "nmax", {}) or {}
    )
    ops: list[dict[str, Any]] = []
    for kind, desired_val in nmax_desired.items():
        full_name = nmax_names.get(kind)
        if not full_name:
            logger.warning(
                f"[proc][N_MAX] kind={kind!r} sin nmax_name declarado. "
                f"Se ignora."
            )
            continue
        cur_val = current.get(full_name)
        desired_int = int(desired_val)
        if cur_val is not None and int(cur_val) == desired_int:
            continue   # sin cambios
        ops.append({
            "table_name": table_name,
            "constant_name": full_name,
            "new_value": desired_int,
        })
    return ops
