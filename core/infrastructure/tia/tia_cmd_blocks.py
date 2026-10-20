"""core.infrastructure.tia.tia_cmd_blocks - comandos de bloques del PLC.

Categoria: bloques. Wrap de la API nativa ``siemens_tia_scripting``
expuesta via ``tia_client``.

Comandos expuestos:
  - ``update_block_property``: modifica la propiedad ``Name`` o ``Number``
    de un PlcBlock dentro de un proyecto TIA. Pensado para invocarse
    dentro de ``execute_transactional_batch`` (rollback atomico si rc!=0).

Restricciones:
  - NO se importan wrappers nativos aqui. Solo ``typing`` y ``logging``.
  - Doble validacion en ``update_block_property``: ``set_property`` puede
    retornar rc=0 (OK) sin aplicar el cambio (TIA V21 silent failure).
    Patron copiado de ``tia_cmd_user_consts.py``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.infrastructure.tia.tia_helpers import (
    _find_block_in_plc,
    _find_plc,
    _get_active_project,
)

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


# Whitelist de propiedades editables via set_property.
_EDITABLE_PROPERTY_NAMES: frozenset[str] = frozenset({"Name", "Number"})


def _h_update_block_property(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Modifica ``Name`` o ``Number`` de un PlcBlock dentro de un PLC.

    Args (dict ``args``):
        plc_name (str): nombre del PLC (e.g. ``"PLC_1500_01"``).
        block_name (str): nombre del bloque (e.g. ``"DB1"``). Dentro de
            un PLC los nombres de bloque son unicos, asi que basta para
            localizarlo: el handler recorre grupos y bloques comparando
            ``get_name()``.
        property_name (str): uno de ``"Name" | "Number"``.
        new_value (str | int): nuevo valor a aplicar.

    Args:
        tia_client: instancia de ``SyncTIAClient`` con ``wrapper`` ya
            atachado al portal activo.

    Returns:
        ``dict`` con ``block_name``, ``property_name`` y ``new_value``.

    Raises:
        ValueError: si ``property_name`` no esta en la whitelist o si
            ``plc_name`` / ``block_name`` faltan.
        RuntimeError: si el bloque no se encuentra, ``set_property``
            retorna ``rc != 0``, o el re-read post-set no coincide.
    """
    plc_name: str = args.get("plc_name", "")
    block_name: str = args.get("block_name", "")
    property_name: str = args.get("property_name", "")
    new_value = args.get("new_value")

    if not plc_name:
        raise ValueError("update_block_property requiere 'plc_name'.")
    if not block_name:
        raise ValueError("update_block_property requiere 'block_name'.")
    if property_name not in _EDITABLE_PROPERTY_NAMES:
        raise ValueError(
            f"update_block_property: property_name={property_name!r} "
            f"no esta en la whitelist {sorted(_EDITABLE_PROPERTY_NAMES)}."
        )

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    block = _find_block_in_plc(target_plc, block_name)

    logger.debug(
        "[update_block_property] plc=%r block=%r "
        "property=%r new_value=%r",
        plc_name, block_name, property_name, new_value,
    )

    rc = block.set_property(name=property_name, value=str(new_value))
    if rc != 0:
        raise RuntimeError(
            f"set_property retorno rc={rc} (no OK) al aplicar "
            f"{property_name}={new_value!r} en bloque {block_name!r}."
        )

    re_read_value = block.get_property(name=property_name)
    if str(re_read_value).strip() != str(new_value).strip():
        raise RuntimeError(
            f"set_property retorno 0 (OK) pero el valor real en TIA "
            f"no coincide: esperado={new_value!r}, leido={re_read_value!r}. "
            f"Posible fallo silencioso Pythonnet/TIA V21."
        )

    return {
        "block_name": block_name,
        "property_name": property_name,
        "new_value": new_value,
    }


# Mapa nombre -> handler. El registro central (tia_commands_catalog)
# importa este dict para registrar el comando en el worker.
BLOCKS_COMMANDS: dict[str, Any] = {
    "update_block_property": _h_update_block_property,
}


__all__ = [
    "BLOCKS_COMMANDS",
    "_EDITABLE_PROPERTY_NAMES",
    "_find_block_in_plc",
    "_h_update_block_property",
]
