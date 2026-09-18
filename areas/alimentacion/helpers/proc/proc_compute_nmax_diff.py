"""Helper puro: diff de N_MAX para el sync de procesos.

Calcula las ops de N_MAX que el handler ``commit_user_constants_online``
aplicara a la tabla ``000_Config_Dispositivos`` cuando el usuario quiere
que TIA redimensione los DBs PARAM / ALM antes del sync de comentarios.

Replica el patron de ``disp_compute_nmax_diff`` (en
``helpers/disp/disp_Sincronizar.py::_compute_nmax_ops_for_apply``) con la
unica diferencia de que proc NO renombra constantes (solo cambia valor).

Forma del retorno:
    [{"table_name": str, "constant_name": str, "new_value": int}, ...]

Si no hay diff, retorna ``[]``. Esto es importante porque el FB que lo
consume dispatchea SIEMPRE el handler (``sync_nmax`` es incondicional),
aun con ``nmax_ops=[]``. TIA no aplicara cambios pero el flujo se
ejecutara igual (cumple requisito: "aunque sea el mismo, siempre editar
por si acaso").

Sept-2026: helper extraido a modulo aparte (antes vivia inline en
``function_ProcSincronizar``) para tener test unitario sin necesidad del
worker OT.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def proc_compute_nmax_diff(
    tags_base: Path,
    config_manager: Any,
    app_state: Any,
) -> list[dict[str, Any]]:
    """Difiere las N_MAX activas contra el estado deseado del AppState.

    Args:
        tags_base: Carpeta raiz ``.build_cache/alimentacion/preview/variables/``
            (o equivalente) donde TIA exporto el ``.xml`` de la tabla de
            variables.
        config_manager: Proveedor con ``get_global_config_table_name()`` y
            ``get_tia_folder_nmax()`` y ``list_nmax_active()``.
        app_state: Singleton con ``.dimensiones`` (dict[str, int]).

    Returns:
        Lista de ops listas para ``commit_user_constants_online``.
        Vacia si todos los N_MAX ya coinciden con el AppState.
    """
    # Import local: ``disp_tag_table_parser`` es del modulo disp, pero el
    # parser XML es generico (lee cualquier tabla de variables de TIA).
    from areas.alimentacion.helpers.xml.disp_tag_table_parser import (
        SimaticMLTagParser,
    )

    nmax_folder = config_manager.get_tia_folder_nmax()
    nmax_table = config_manager.get_global_config_table_name()
    xml_path = tags_base / nmax_folder / f"{nmax_table}.xml"

    current: dict[str, int] = {}
    if xml_path.is_file():
        try:
            current = SimaticMLTagParser.parse_user_constants(xml_path)
        except Exception as e:
            logger.error(f"[proc][N_MAX] Parse FAIL {xml_path}: {e}")

    d = app_state.dimensiones or {}
    desired: dict[str, int] = {}
    for nmax_name in config_manager.list_nmax_active():
        v = d.get(nmax_name)
        if v is None:
            v = 0
        desired[nmax_name] = int(v)

    ops: list[dict[str, Any]] = []
    for name, des_val in desired.items():
        cur_val = current.get(name)
        if cur_val is None or cur_val == des_val:
            continue
        ops.append({
            "table_name": nmax_table,
            "constant_name": name,
            "new_value": des_val,
        })
    return ops
