"""core.infrastructure.tia.tia_commands_catalog - registro central de comandos.

Punto unico de verdad sobre que comandos expone el worker OT y como
registrarlos en un ``SyncTIAClient``. Reemplaza al antiguo
``register_core_commands`` que vivia en ``tia_handlers.py``.

Catalogo actual (26 comandos core + N comandos del area):

  -  3 lifecycle:        attach_portal, detach_portal, open_new_portal
  -  3 project:          open_project, save_project, close_project
  -  5 inspect:          ping, list_plcs, list_blocks, get_project_info, scan_blocks
  -  2 compile:          compile_plc, compile_blocks
  -  5 export:           export_blocks_sd, export_udts_sd, export_plc_tags_xml,
                          export_block, export_tag_table
  -  4 import:           import_blocks_sd, import_plc_tags_xml, import_tag_table,
                          import_block
  -  4 user_consts:      get_user_constants, delete_user_constant,
                          update_user_constant_value, update_user_constant_name
  -  1 batch:            execute_transactional_batch

Las areas aportan comandos adicionales via ``AreaSpec.contributes_tia_commands``
(registrados en su propio modulo, no en este catalogo).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.infrastructure.tia.tia_cmd_batch import COMMANDS as BATCH_COMMANDS
from core.infrastructure.tia.tia_cmd_compile import COMMANDS as COMPILE_COMMANDS
from core.infrastructure.tia.tia_cmd_export import COMMANDS as EXPORT_COMMANDS
from core.infrastructure.tia.tia_cmd_import_ import COMMANDS as IMPORT_COMMANDS
from core.infrastructure.tia.tia_cmd_inspect import COMMANDS as INSPECT_COMMANDS
from core.infrastructure.tia.tia_cmd_lifecycle import COMMANDS as LIFECYCLE_COMMANDS
from core.infrastructure.tia.tia_cmd_project import COMMANDS as PROJECT_COMMANDS
from core.infrastructure.tia.tia_cmd_user_consts import (
    COMMANDS as USER_CONSTS_COMMANDS,
)

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient


# Fuente unica de verdad: union de los 8 catalogos por categoria.
CATALOGO: dict[str, Any] = {
    **LIFECYCLE_COMMANDS,    # 3
    **PROJECT_COMMANDS,      # 3
    **INSPECT_COMMANDS,      # 5
    **COMPILE_COMMANDS,      # 2
    **EXPORT_COMMANDS,       # 5
    **IMPORT_COMMANDS,       # 4
    **USER_CONSTS_COMMANDS,  # 4
    **BATCH_COMMANDS,        # 1
}


def register_all_commands(client: "SyncTIAClient") -> None:
    """Carga los 26 comandos core en ``client._handlers``.

    Llamado desde ``tia_loop.start_tia_loop()`` en el arranque del worker.
    Si un comando ya esta registrado, ``register_command()`` lanza
    ValueError (dejado para que el caller decida si reinstancia o ignora).

    Las areas que aportan comandos adicionales los registran aparte via
    ``AreaSpec.contributes_tia_commands`` (no en este catalogo).
    """
    for name, handler in CATALOGO.items():
        client.register_command(name, handler)


__all__ = ["CATALOGO", "register_all_commands"]
