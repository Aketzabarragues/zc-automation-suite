"""core.infrastructure.tia.tia_cmd_inspect - comandos de inspección (read-only).

Cinco comandos para leer info del proyecto / PLC / bloques sin modificar nada:

  - ping:            health check rapido (devuelve el PID del portal).
  - list_blocks:     nombres de bloques de programa de un PLC.
  - list_plcs:       lista de PLCs del proyecto activo.
  - get_project_info: propiedades basicas del proyecto (name, path, author...).
  - scan_blocks:     escaneo completo (bloques + tag tables + UDTs) de un PLC.

Cada handler es una FC pura: recibe ``(args: dict, tia_client: SyncTIAClient)``
y devuelve ``dict``. Acceso a portal via ``tia_client.wrapper`` (single-threaded;
lo toca el tia-loop).

Restricciones arquitectónicas:
  - Solo lectura. NO modifica nada en TIA Portal.
  - NO hace logging de args (puede contener paths sensibles).
  - Las propiedades que lanzan (PermissionDenied, EncodingError) se omiten
    del payload en lugar de tumbar el handler (dict parcial).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from core.data.data_block_plc import DataBloquePLC
from core.infrastructure.tia.tia_helpers import (
    _find_plc,
    _get_active_project,
    _safe_get_block_name,
    _safe_get_block_path,
    _safe_get_table_name,
    _safe_short_designation,
)

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


def _h_ping(args: dict, tia_client: "SyncTIAClient") -> dict:  # noqa: ARG001
    """Verifica si TIA Portal sigue activo.

    Returns:
        ``{"pid": <int>}`` si responde. RuntimeError si no hay portal.
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError("No hay portal attached")
    pid = portal.get_process_id()
    return {"pid": int(pid)}


def _h_list_blocks(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Lista los nombres de bloques de programa de un PLC."""
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    folder_path: str = args.get("folder_path") or ""

    target_plc = _find_plc(project, plc_name)
    blocks = target_plc.get_program_blocks(folder_path=folder_path)
    names = [block.get_name() for block in blocks]
    return {"blocks": names, "plc_name": plc_name}


def _h_list_plcs(args: dict, tia_client: "SyncTIAClient") -> dict:  # noqa: ARG001
    """Lista los PLCs del proyecto activo.

    Returns:
        ``{"plcs": [{"name": str, "short_designation": str | None}, ...]}``.
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    plcs = project.get_plcs()
    result = [
        {"name": plc.get_name(), "short_designation": _safe_short_designation(plc)}
        for plc in plcs
    ]
    return {"plcs": result}


def _h_get_project_info(args: dict, tia_client: "SyncTIAClient") -> dict:  # noqa: ARG001
    """Propiedades basicas del proyecto TIA activo (siempre primitivos).

    Si una property lanza (PermissionDenied, EncodingError), se omite del
    payload en vez de tumbar el handler: dict parcial.
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)

    def _safe_get(name: str) -> Any:
        try:
            return project.get_property(name=name)
        except Exception:
            return None

    result: dict[str, Any] = {"name": _safe_get("Name")}

    for prop_name, out_key in (
        ("Path", "path"),
        ("Author", "author"),
        ("CreationTime", "creation_time"),
        ("LastModified", "last_modified"),
        ("LastModifiedBy", "last_modified_by"),
        ("Version", "version"),
    ):
        value = _safe_get(prop_name)
        if value is None:
            continue
        # Normalizar a primitivo: datetime/DateTime .NET -> ISO 8601 string.
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        result[out_key] = value

    return result


# ---------------------------------------------------------------------------
# Helper privado del modulo: recorrido recursivo de bloques
# ---------------------------------------------------------------------------
def _scan_block_group_recursive(group_or_blocks: Any) -> list[dict]:
    """Recorre recursivamente un grupo o coleccion de bloques -> DTOs dict.

    Returns:
        Lista de dicts con shape DataBloquePLC.to_dict(). Bloques con
        nombre inaccesible (UnicodeDecodeError) se omiten.
    """
    blocks_iter: list = []
    try:
        if hasattr(group_or_blocks, "get_blocks"):
            blocks_iter = list(group_or_blocks.get_blocks() or [])
        elif hasattr(group_or_blocks, "Blocks"):
            blocks_iter = list(group_or_blocks.Blocks or [])
        elif hasattr(group_or_blocks, "__iter__"):
            blocks_iter = list(group_or_blocks)
    except Exception:
        blocks_iter = []

    out: list[dict] = []
    for block in blocks_iter:
        nombre = _safe_get_block_name(block)
        if not nombre:
            continue
        ruta = _safe_get_block_path(block)
        tipo = DataBloquePLC.detect_tipo(nombre)
        match = re.match(r"^(DB|FB|FC|OB|UDT)(\d+)", nombre, re.IGNORECASE)
        numero = int(match.group(2)) if match else 0
        out.append(
            DataBloquePLC(
                nombre=str(nombre),
                numero=numero,
                tipo=tipo,
                ruta=ruta,
            ).to_dict()
        )

    groups: list = []
    try:
        if hasattr(group_or_blocks, "get_groups"):
            groups = list(group_or_blocks.get_groups() or [])
        elif hasattr(group_or_blocks, "Groups"):
            groups = list(group_or_blocks.Groups or [])
    except Exception:
        groups = []

    for sub in groups:
        out.extend(_scan_block_group_recursive(sub))

    return out


def _h_scan_blocks(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Escanea bloques, tag tables y UDTs de un PLC.

    Returns:
        ``{"plc_name": str, "blocks": [...], "tag_tables": [...], "udts": [...], "scanned_at": str}``
    """
    plc_name: str = args.get("plc_name", "")
    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    # Bloques: recorrido recursivo.
    program_blocks = target_plc.get_program_blocks()
    blocks_list = _scan_block_group_recursive(program_blocks)

    # Tag tables: defensivo; si TIA falla, log warning y seguimos.
    tag_tables_objs: list = []
    try:
        tag_tables_objs = list(target_plc.get_plc_tag_tables() or [])
    except Exception as exc:
        logger.warning(
            "No se pudieron listar PlcTagTables del PLC '%s': %s",
            plc_name, exc,
        )

    from core.data.data_block_plc import DataBloquePLC  # local import para no tocar top-level

    tag_tables_list: list[dict] = []
    for table in tag_tables_objs:
        nombre = _safe_get_table_name(table)
        if not nombre:
            continue
        ruta = _safe_get_block_path(table)
        tag_tables_list.append(
            DataBloquePLC(
                nombre=str(nombre),
                numero=0,
                tipo="OTHER",
                ruta=ruta,
            ).to_dict()
        )

    # UDTs: coleccion distinta de program_blocks.
    udts_list: list[dict] = []
    try:
        user_data_types = target_plc.get_user_data_types()
        udts_list = _scan_block_group_recursive(user_data_types)
    except Exception as exc:
        logger.warning(
            "No se pudieron listar User Data Types del PLC '%s': %s",
            plc_name, exc,
        )
        udts_list = []

    return {
        "plc_name": plc_name,
        "blocks": blocks_list,
        "tag_tables": tag_tables_list,
        "udts": udts_list,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


# Mapa nombre → handler. El registro central (tia_commands_catalog)
# importará este dict para registrar los 5 comandos en el worker.
COMMANDS: dict[str, Any] = {
    "ping": _h_ping,
    "list_blocks": _h_list_blocks,
    "list_plcs": _h_list_plcs,
    "get_project_info": _h_get_project_info,
    "scan_blocks": _h_scan_blocks,
}


__all__ = [
    "COMMANDS",
    "_h_ping",
    "_h_list_blocks",
    "_h_list_plcs",
    "_h_get_project_info",
    "_h_scan_blocks",
]
