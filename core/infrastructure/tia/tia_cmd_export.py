"""core.infrastructure.tia.tia_cmd_export - comandos de export (TIA -> disco).

Cinco comandos para exportar contenido del PLC a archivos en disco:

  - export_blocks_sd:     exporta TODOS los bloques de programa como .s7dcl.
  - export_udts_sd:       exporta los User Data Types como .s7dcl.
  - export_plc_tags_xml:  exporta tablas de tags como XML SimaticML.
  - export_block:         exporta UN bloque concreto como SimaticSD.
  - export_tag_table:     exporta UNA tabla de tags como XML.

Cada handler es una FC pura: recibe ``(args: dict, tia_client: SyncTIAClient)``
y devuelve ``dict``. Acceso a portal via ``tia_client.wrapper`` (single-threaded;
lo toca el tia-loop).

Restricciones arquitectónicas:
  - Solo lectura del PLC. Escribe archivos en disco.
  - El directorio destino se crea con ``_ensure_target_dir`` si no existe.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.infrastructure.tia.tia_helpers import (
    _ensure_target_dir,
    _export_objects_sd,
    _find_plc,
    _get_active_project,
    _safe_get_block_name,
    _safe_get_table_name,
)

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


def _h_export_blocks_sd(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta los bloques de programa del PLC como .s7dcl."""
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)
    return _export_objects_sd(target_plc, target_path, "program_blocks")


def _h_export_udts_sd(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta los User Data Types del PLC como .s7dcl."""
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)
    return _export_objects_sd(target_plc, target_path, "user_data_types")


def _h_export_plc_tags_xml(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta las tablas de variables del PLC como XML SimaticML."""
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    target_table_names = args.get("table_names")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    tag_tables = target_plc.get_plc_tag_tables()
    count = 0
    for table in tag_tables:
        if target_table_names is not None:
            name = _safe_get_table_name(table)
            if name not in target_table_names:
                continue
        table.export(
            target_directory_path=str(target_path),
            keep_folder_structure=True,
        )
        count += 1

    return {"exported_to": str(target_path), "count": count}


def _h_export_block(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta un bloque de programa como SimaticSD (manual §2.10.5)."""
    plc_name: str = args.get("plc_name", "")
    block_name: str = args.get("block_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not block_name:
        raise ValueError("Se requiere el argumento 'block_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    blocks = target_plc.get_program_blocks()
    for block in blocks:
        name = _safe_get_block_name(block)
        if name == block_name:
            block.export(
                target_directory_path=str(target_path),
                export_format="SimaticSD",
                keep_folder_structure=False,
            )
            return {"exported_to": str(target_path), "block_name": block_name}

    raise RuntimeError(
        f"Bloque '{block_name}' no encontrado en PLC '{plc_name}'."
    )


def _h_export_tag_table(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta una PlcTagTable como XML SimaticML."""
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not table_name:
        raise ValueError("Se requiere el argumento 'table_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    tag_tables = target_plc.get_plc_tag_tables()
    for table in tag_tables:
        name = _safe_get_table_name(table)
        if name == table_name:
            table.export(
                target_directory_path=str(target_path),
                keep_folder_structure=False,
            )
            return {"exported_to": str(target_path), "table_name": table_name}

    raise RuntimeError(
        f"Tabla '{table_name}' no encontrada en PLC '{plc_name}'."
    )


# Mapa nombre → handler. El registro central (tia_commands_catalog)
# importará este dict para registrar los 5 comandos en el worker.
COMMANDS: dict[str, Any] = {
    "export_blocks_sd": _h_export_blocks_sd,
    "export_udts_sd": _h_export_udts_sd,
    "export_plc_tags_xml": _h_export_plc_tags_xml,
    "export_block": _h_export_block,
    "export_tag_table": _h_export_tag_table,
}


__all__ = [
    "COMMANDS",
    "_h_export_blocks_sd",
    "_h_export_udts_sd",
    "_h_export_plc_tags_xml",
    "_h_export_block",
    "_h_export_tag_table",
]
