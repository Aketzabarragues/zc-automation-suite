"""core.infrastructure.tia.tia_cmd_export - comandos de export (TIA -> disco).

Tres comandos unificados (FASE 2.6) que aceptan ``1`` o ``N`` elementos via
``*_names`` (whitelist opcional; ``None`` = todos):

  - export_blocks:  exporta bloques de programa como .s7dcl.
  - export_udts:    exporta los User Data Types como .s7dcl.
  - export_tables:  exporta tablas de tags como XML SimaticML.

Cinco legacy coexisten durante la migración y se borran en commit 12
(tras migrar los FBs consumidores en commits 5-11):
  - export_blocks_sd:     plural sin filtro (legacy, sin consumidores).
  - export_udts_sd:       plural sin filtro (legacy, sin consumidores).
  - export_plc_tags_xml:  plural con ``table_names`` opcional (legacy, usado).
  - export_block:         singular (legacy, usado por 6 FBs del area).
  - export_tag_table:     singular (legacy, sin consumidores).

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
    """Exporta los bloques de programa del PLC como .s7dcl.

    Args (en ``args``):
        plc_name (str): nombre del PLC.
        target_dir (str): directorio destino.
        keep_folder_structure (bool, opcional, default ``True``): si
            ``True``, conserva la jerarquia de subcarpetas del PLC en
            TIA (e.g. ``<target>/2000_Dispositivos/<obj>.s7dcl``). Si
            ``False``, exporta FLAT a ``<target>/<obj>.s7dcl``.
    """
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    keep_folder_structure: bool = args.get("keep_folder_structure", True)

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
    return _export_objects_sd(
        target_plc, target_path, "program_blocks",
        keep_folder_structure=keep_folder_structure,
    )


def _h_export_udts_sd(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta los User Data Types del PLC como .s7dcl.

    Args (en ``args``):
        plc_name (str): nombre del PLC.
        target_dir (str): directorio destino.
        keep_folder_structure (bool, opcional, default ``True``): ver
            ``_h_export_blocks_sd``.
    """
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    keep_folder_structure: bool = args.get("keep_folder_structure", True)

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
    return _export_objects_sd(
        target_plc, target_path, "user_data_types",
        keep_folder_structure=keep_folder_structure,
    )


def _h_export_plc_tags_xml(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta las tablas de variables del PLC como XML SimaticML.

    LEGACY FASE 2.6: se borrara en commit 12 tras la migracion de los 5
    FBs del area que aun lo usan (disp_generar_preview, entidades_*,
    proc_db_*). Reemplazado por ``_h_export_tables`` (plural con
    ``table_names`` whitelist opcional; mismo comportamiento).

    Args (en ``args``):
        plc_name (str): nombre del PLC.
        target_dir (str): directorio destino.
        table_names (list[str], opcional): si se pasa, filtra las
            tablas a exportar por nombre.
        keep_folder_structure (bool, opcional, default ``True``): si
            ``True``, conserva la jerarquia de subcarpetas del PLC en
            TIA (e.g. ``<target>/2000_Dispositivos/<tabla>.xml``). Si
            ``False``, exporta FLAT a ``<target>/<tabla>.xml`` (util
            para preview FLAT donde la info de grupo esta en
            ``config.json``).
    """
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    target_table_names = args.get("table_names")
    keep_folder_structure: bool = args.get("keep_folder_structure", True)

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
            keep_folder_structure=keep_folder_structure,
        )
        count += 1

    return {"exported_to": str(target_path), "count": count}


def _h_export_block(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta un bloque de programa como SimaticSD (manual §2.10.5).

    LEGACY FASE 2.6: se borrara en commit 12 tras la migracion de los 6
    FBs del area que aun lo usan (disp_sincronizar, entidades_*,
    proc_db_*). Reemplazado por ``_h_export_blocks`` (plural con
    ``block_names`` whitelist opcional). No usar en codigo nuevo.

    Args (en ``args``):
        plc_name (str): nombre del PLC.
        block_name (str): nombre del bloque.
        target_dir (str): directorio destino.
        keep_folder_structure (bool, opcional, default ``False``): si
            ``True``, conserva la jerarquia de subcarpetas del PLC en
            TIA (e.g. ``<target>/2000_Dispositivos/<DB>.s7dcl``). Si
            ``False`` (default retro-compat), exporta FLAT a
            ``<target>/<DB>.s7dcl``.
    """
    plc_name: str = args.get("plc_name", "")
    block_name: str = args.get("block_name", "")
    target_dir: str = args.get("target_dir", "")
    keep_folder_structure: bool = args.get("keep_folder_structure", False)

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
                keep_folder_structure=keep_folder_structure,
            )
            return {"exported_to": str(target_path), "block_name": block_name}

    raise RuntimeError(
        f"Bloque '{block_name}' no encontrado en PLC '{plc_name}'."
    )


def _h_export_tag_table(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta una PlcTagTable como XML SimaticML.

    Args (en ``args``):
        plc_name (str): nombre del PLC.
        table_name (str): nombre de la tabla.
        target_dir (str): directorio destino.
        keep_folder_structure (bool, opcional, default ``False``): si
            ``True``, conserva la jerarquia de subcarpetas del PLC en
            TIA. Si ``False`` (default retro-compat), exporta FLAT a
            ``<target>/<tabla>.xml``.
    """
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    target_dir: str = args.get("target_dir", "")
    keep_folder_structure: bool = args.get("keep_folder_structure", False)

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
                keep_folder_structure=keep_folder_structure,
            )
            return {"exported_to": str(target_path), "table_name": table_name}

    raise RuntimeError(
        f"Tabla '{table_name}' no encontrada en PLC '{plc_name}'."
    )


# ---------------------------------------------------------------------------
# Handlers unificados (FASE 2.6 commit 1)
# ---------------------------------------------------------------------------
# Reemplazan a los 5 legacy de arriba. Cada uno:
#   - Conoce su ``objects_iter`` (que get_xxx() llamar) y su ``export_kwargs``
#     (que formato pasar al wrapper TIA). El bucle de filtrado + export
#     vive inline (mismo patron en los 3; ~17 lineas identicas aceptadas
#     conscientemente para mantener self-contained).
#   - Acepta ``block_names``/``udt_names``/``table_names`` como whitelist
#     opcional. ``None`` (o ausente) = exportar TODOS los del PLC.
#   - Match exacto por nombre, case-sensitive (retro-compat con el singular
#     legacy ``export_block``).
#   - Retorna shape: ``{exported_to, count, exported_names, skipped_names}``.


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
# importará este dict para registrar los 8 comandos (3 nuevos + 5 legacy)
# en el worker durante la migración. Los legacy se borran todos en commit 12
# (consolidado: tras migrar los 6 FBs del area que los consumen en commits 5-11).
COMMANDS: dict[str, Any] = {
    # Legacy (FASE 2.6 commit 12: borrar los 5).
    "export_blocks_sd": _h_export_blocks_sd,
    "export_udts_sd": _h_export_udts_sd,
    "export_plc_tags_xml": _h_export_plc_tags_xml,
    "export_block": _h_export_block,
    "export_tag_table": _h_export_tag_table,
    # Nuevos unificados (FASE 2.6 commit 1).
    "export_blocks": _h_export_blocks,
    "export_udts": _h_export_udts,
    "export_tables": _h_export_tables,
}


__all__ = [
    "COMMANDS",
    "_h_export_blocks_sd",
    "_h_export_udts_sd",
    "_h_export_plc_tags_xml",
    "_h_export_block",
    "_h_export_tag_table",
    "_h_export_blocks",
    "_h_export_udts",
    "_h_export_tables",
]
