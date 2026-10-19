"""core.infrastructure.tia.tia_cmd_export - comandos de export (TIA -> disco).

Tres comandos que aceptan ``1`` o ``N`` elementos via ``*_names``
(whitelist opcional; ``None`` = todos):

  - export_blocks:  exporta bloques de programa como .s7dcl.
  - export_udts:    exporta los User Data Types como .s7dcl.
  - export_tables:  exporta tablas de tags como XML SimaticML.

Cada handler es una FC pura: recibe ``(args: dict, tia_client: SyncTIAClient)``
y devuelve ``dict``. Acceso a portal via ``tia_client.wrapper`` (single-threaded;
lo toca el tia-loop).

Cada handler conoce su ``objects_iter`` (que ``get_xxx()`` llamar a TIA) y su
``export_kwargs`` (que formato pasar al wrapper TIA). El bucle de filtrado +
export vive inline en cada handler; ~17 lineas identicas entre los 3 (mismo
patron de "filtrar por whitelist + llamar a ``obj.export(**kwargs)``"), aceptadas
conscientemente para mantener cada handler self-contained sin helper comun.

Restricciones arquitectónicas:
  - Solo lectura del PLC. Escribe archivos en disco.
  - El directorio destino se crea con ``_ensure_target_dir`` si no existe.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.infrastructure.tia.tia_helpers import (
    _ensure_target_dir,
    _find_plc,
    _get_active_project,
    _safe_get_block_name,
    _safe_get_table_name,
)

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


def _h_export_blocks(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta bloques de programa del PLC como SimaticSD.

    Args (en ``args``):
        plc_name (str): nombre del PLC.
        target_dir (str): directorio destino (absoluto).
        block_names (list[str] | None, opcional): whitelist de nombres.
            ``None`` o ausente = exportar TODOS. Match exacto, case-sensitive.
        keep_folder_structure (bool, opcional, default ``False``):
            ``True`` preserva la jerarquia TIA; ``False`` (default retro-compat)
            exporta FLAT.
    """
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    block_names = args.get("block_names")
    keep_folder_structure: bool = args.get("keep_folder_structure", False)

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not target_dir:
        raise ValueError("Se requiere el argumento 'target_dir'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    wanted = None
    if block_names is not None:
        wanted = {str(n).strip() for n in block_names if n}

    exported_names: list[str] = []
    for obj in target_plc.get_program_blocks():
        name = _safe_get_block_name(obj)
        if not name:
            continue
        if wanted is not None and name not in wanted:
            continue
        obj.export(
            target_directory_path=str(target_path),
            export_format="SimaticSD",
            keep_folder_structure=keep_folder_structure,
        )
        exported_names.append(name)

    skipped_names = sorted(wanted - set(exported_names)) if wanted is not None else []
    return {
        "exported_to": str(target_path),
        "count": len(exported_names),
        "exported_names": exported_names,
        "skipped_names": skipped_names,
    }


def _h_export_udts(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta los User Data Types del PLC como SimaticSD.

    Args (en ``args``):
        plc_name (str): nombre del PLC.
        target_dir (str): directorio destino (absoluto).
        udt_names (list[str] | None, opcional): whitelist de nombres.
            ``None`` o ausente = exportar TODOS.
        keep_folder_structure (bool, opcional, default ``False``): ver
            ``_h_export_blocks``.
    """
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    udt_names = args.get("udt_names")
    keep_folder_structure: bool = args.get("keep_folder_structure", False)

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not target_dir:
        raise ValueError("Se requiere el argumento 'target_dir'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    wanted = None
    if udt_names is not None:
        wanted = {str(n).strip() for n in udt_names if n}

    exported_names: list[str] = []
    for obj in target_plc.get_user_data_types():
        name = _safe_get_block_name(obj)
        if not name:
            continue
        if wanted is not None and name not in wanted:
            continue
        obj.export(
            target_directory_path=str(target_path),
            export_format="SimaticSD",
            keep_folder_structure=keep_folder_structure,
        )
        exported_names.append(name)

    skipped_names = sorted(wanted - set(exported_names)) if wanted is not None else []
    return {
        "exported_to": str(target_path),
        "count": len(exported_names),
        "exported_names": exported_names,
        "skipped_names": skipped_names,
    }


def _h_export_tables(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta las tablas de variables del PLC como XML SimaticML.

    Args (en ``args``):
        plc_name (str): nombre del PLC.
        target_dir (str): directorio destino (absoluto).
        table_names (list[str] | None, opcional): whitelist de nombres.
            ``None`` o ausente = exportar TODAS.
        keep_folder_structure (bool, opcional, default ``False``): ver
            ``_h_export_blocks``.

    Las PlcTagTables no aceptan ``export_format``; el wrapper TIA escribe
    XML directamente.
    """
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    table_names = args.get("table_names")
    keep_folder_structure: bool = args.get("keep_folder_structure", False)

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not target_dir:
        raise ValueError("Se requiere el argumento 'target_dir'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    wanted = None
    if table_names is not None:
        wanted = {str(n).strip() for n in table_names if n}

    exported_names: list[str] = []
    for table in target_plc.get_plc_tag_tables():
        name = _safe_get_table_name(table)
        if not name:
            continue
        if wanted is not None and name not in wanted:
            continue
        table.export(
            target_directory_path=str(target_path),
            keep_folder_structure=keep_folder_structure,
        )
        exported_names.append(name)

    skipped_names = sorted(wanted - set(exported_names)) if wanted is not None else []
    return {
        "exported_to": str(target_path),
        "count": len(exported_names),
        "exported_names": exported_names,
        "skipped_names": skipped_names,
    }


# Mapa nombre → handler. El registro central (tia_commands_catalog)
# importará este dict para registrar los 3 comandos en el worker.
COMMANDS: dict[str, Any] = {
    "export_blocks": _h_export_blocks,
    "export_udts": _h_export_udts,
    "export_tables": _h_export_tables,
}


__all__ = [
    "COMMANDS",
    "_h_export_blocks",
    "_h_export_udts",
    "_h_export_tables",
]