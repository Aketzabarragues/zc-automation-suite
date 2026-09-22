"""core.infrastructure.tia.tia_cmd_import_ - comandos de import (disco -> PLC).

Cuatro comandos para importar contenido del disco al PLC:

  - import_blocks_sd:      importa MUCHOS bloques .s7dcl al PLC.
  - import_plc_tags_xml:   importa tablas de tags como XML SimaticML.
  - import_tag_table:      importa UNA tabla de tags como XML.
  - import_block:          importa UN bloque .s7dcl al PLC.

Cada handler es una FC pura: recibe ``(args: dict, tia_client: SyncTIAClient)``
y devuelve ``dict``. Acceso a portal via ``tia_client.wrapper`` (single-threaded;
lo toca el tia-loop).

Restricciones arquitectónicas:
  - Solo escritura: importa archivos al PLC.
  - REGLAS CRITICAS TIA V21 (preservar siempre):
    ``import_blocks`` / ``import_plc_tags`` tienen la firma
    ``(import_root_directory: str, target_folder_path: Optional[str] = None)``.
    Pasar ``target_folder_path=""`` (string vacio) hace que TIA NO haga
    match UPDATE de bloques pre-existentes; en su lugar intenta CREATE y
    falla con "Import failed because an object with the name X already
    exists". Patron: si el caller no pasa un ``target_folder`` no vacio,
    NO pasamos el argumento y dejamos que TIA use su default (``None`` =
    escanea recursivo, hace match UPDATE por nombre preservando el subpath).
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from core.infrastructure.tia.tia_helpers import (
    _find_plc,
    _find_plc_tag_table,
    _get_active_project,
)

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


def _h_import_blocks_sd(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa bloques .s7dcl desde el disco al PLC (manual §2.2.23).

    CUIDADO: ``import_blocks`` tiene la firma
    ``import_blocks(import_root_directory: str, target_folder_path: Optional[str] = None)``
    (default = ``None``, NO string vacio). Pasar ``target_folder_path=""``
    (string vacio) hace que TIA V21 NO haga match UPDATE de bloques
    pre-existentes (replica el árbol de carpetas del PLC dentro del
    ``import_root_directory``); en su lugar intenta CREATE y falla con
    "Import failed because an object with the name X already exists".
    Validado en VM: el mismo directorio que importa OK con script
    standalone (``plc.import_blocks(import_root_directory=...)`` sin
    pasar ``target_folder_path``) falla cuando el handler pasa
    ``""``. Solucion: si el caller no pasa un ``target_folder`` no
    vacio, NO pasamos el argumento y dejamos que TIA use su default
    (``None`` = escanea recursivo, hace match UPDATE por nombre de
    bloque preservando la ruta relativa).

    Reproducido del bug en sept-2026: el handler original hacia
    ``args.get("target_folder") or ""`` y siempre pasaba el argumento
    a TIA, lo que rompia el ``Crear proceso desde plantilla`` (el FB
    ``proc_process_crear_aplicar`` de alimentacion que llama a este
    handler con ``target_folder`` omitido sufria el mismo problema
    que ``import_block`` (singular) antes de su fix en el docstring
    de arriba). Replicamos el patron de ``_h_import_block`` para
    arreglarlo.
    """
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder_raw = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(
            f"El directorio de importacion no existe o no es accesible: "
            f"'{import_dir}'."
        )

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    if target_folder_raw:
        target_plc.import_blocks(
            import_root_directory=import_dir,
            target_folder_path=target_folder_raw,
        )
    else:
        target_plc.import_blocks(import_root_directory=import_dir)
    return {"imported_from": import_dir}


def _h_import_plc_tags_xml(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa PlcTagTables en formato XML al PLC (manual §2.2.24).

    Misma regla que ``_h_import_blocks_sd`` sobre
    ``target_folder_path``: si el caller no lo pasa, NO se envia a
    TIA (default = ``None``, escaneo recursivo con match UPDATE por
    nombre preservando el subpath). Pasar ``""`` rompe el match
    UPDATE en V21. Patron identico al fix aplicado a
    ``_h_import_block`` y ``_h_import_blocks_sd``.
    """
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder_raw = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(
            f"El directorio de importacion no existe o no es accesible: "
            f"'{import_dir}'."
        )

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    if target_folder_raw:
        target_plc.import_plc_tags(
            import_root_directory=import_dir,
            target_folder_path=target_folder_raw,
        )
    else:
        target_plc.import_plc_tags(import_root_directory=import_dir)
    return {"imported_from": import_dir}


def _h_import_tag_table(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa una PlcTagTable (XML) desde disco al PLC (manual §2.2.24)."""
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder: str = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(f"El directorio no existe: '{import_dir}'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_plc.import_plc_tags(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return {"imported_from": import_dir}


def _h_import_block(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa un bloque (.s7dcl) desde disco al PLC (manual §2.2.23).

    CUIDADO: ``import_blocks`` tiene la firma
    ``import_blocks(import_root_directory: str, target_folder_path: Optional[str] = None)``
    (default = ``None``, NO string vacio). Pasar ``target_folder_path=""``
    (string vacio) hace que TIA V21 NO haga match UPDATE de bloques
    pre-existentes (replica el árbol de carpetas del PLC dentro del
    ``import_root_directory``); en su lugar intenta CREATE y falla con
    "Import failed because an object with the name X already exists".
    Validado en VM: el mismo directorio que importa OK con script
    standalone (``plc.import_blocks(import_root_directory=...)`` sin
    pasar ``target_folder_path``) falla cuando el handler pasa
    ``""``. Solucion: si el caller no pasa un ``target_folder`` no
    vacio, NO pasamos el argumento y dejamos que TIA use su default
    (``None`` = escanea recursivo, hace match UPDATE por nombre de
    bloque preservando la ruta relativa).
    """
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder_raw = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(f"El directorio no existe: '{import_dir}'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    if target_folder_raw:
        target_plc.import_blocks(
            import_root_directory=import_dir,
            target_folder_path=target_folder_raw,
        )
    else:
        target_plc.import_blocks(import_root_directory=import_dir)
    return {"imported_from": import_dir}


# Mapa nombre → handler. El registro central (tia_commands_catalog)
# importará este dict para registrar los 4 comandos en el worker.
COMMANDS: dict[str, Any] = {
    "import_blocks_sd": _h_import_blocks_sd,
    "import_plc_tags_xml": _h_import_plc_tags_xml,
    "import_tag_table": _h_import_tag_table,
    "import_block": _h_import_block,
}


__all__ = [
    "COMMANDS",
    "_h_import_blocks_sd",
    "_h_import_plc_tags_xml",
    "_h_import_tag_table",
    "_h_import_block",
]
