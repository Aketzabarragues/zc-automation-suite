"""core.infrastructure.tia.tia_handlers - modulo transitorio de re-exports.

Los 26 comandos del subsistema TIA se han migrado a ``core.infrastructure.tia.
tia_cmd_*`` (un archivo por categoria). Este modulo se mantiene temporalmente
para no romper los 25+ callers que importan ``_h_*`` desde aqui.

Categorias (cada una en su archivo):
  - lifecycle: core/infrastructure/tia/tia_cmd_lifecycle.py
                (attach_portal, detach_portal, open_new_portal)
  - project:   core/infrastructure/tia/tia_cmd_project.py
                (open_project, save_project, close_project)
  - inspect:   core/infrastructure/tia/tia_cmd_inspect.py
                (ping, list_plcs, list_blocks, get_project_info, scan_blocks)
  - compile:   core/infrastructure/tia/tia_cmd_compile.py
                (compile_plc, compile_blocks)
  - export:    core/infrastructure/tia/tia_cmd_export.py
                (export_block, export_blocks_sd, export_udts_sd,
                 export_plc_tags_xml, export_tag_table)
  - import:    core/infrastructure/tia/tia_cmd_import_.py
                (import_block, import_blocks_sd, import_plc_tags_xml,
                 import_tag_table)
  - user_consts: core/infrastructure/tia/tia_cmd_user_consts.py
                (get_user_constants, delete_user_constant,
                 update_user_constant_value, update_user_constant_name)
  - batch:     core/infrastructure/tia/tia_cmd_batch.py
                (execute_transactional_batch)

Este modulo se eliminara en el commit 10 del refactor de greenfield.
"""
from __future__ import annotations

# Re-exports para compatibilidad con callers legacy.
from core.infrastructure.tia.tia_cmd_lifecycle import (  # noqa: F401
    _h_attach_portal,
    _h_detach_portal,
    _h_open_new_portal,
)
from core.infrastructure.tia.tia_cmd_project import (  # noqa: F401
    _h_open_project,
    _h_save_project,
    _h_close_project,
)
from core.infrastructure.tia.tia_cmd_inspect import (  # noqa: F401
    _h_ping,
    _h_list_blocks,
    _h_list_plcs,
    _h_get_project_info,
    _h_scan_blocks,
)
from core.infrastructure.tia.tia_cmd_compile import (  # noqa: F401
    _h_compile_plc,
    _h_compile_blocks,
)
from core.infrastructure.tia.tia_cmd_export import (  # noqa: F401
    _h_export_blocks_sd,
    _h_export_udts_sd,
    _h_export_plc_tags_xml,
    _h_export_block,
    _h_export_tag_table,
)
from core.infrastructure.tia.tia_cmd_import_ import (  # noqa: F401
    _h_import_blocks_sd,
    _h_import_plc_tags_xml,
    _h_import_tag_table,
    _h_import_block,
)
from core.infrastructure.tia.tia_cmd_user_consts import (  # noqa: F401
    _h_get_user_constants,
    _h_delete_user_constant,
    _h_update_user_constant_value,
    _h_update_user_constant_name,
)
from core.infrastructure.tia.tia_cmd_batch import (  # noqa: F401
    _h_execute_transactional_batch,
    _TRANSACTION_FORBIDDEN_COMMANDS,
)
from core.infrastructure.tia.tia_commands_catalog import (  # noqa: F401
    register_all_commands,
)

import json as _json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import TYPE_CHECKING, Any  # noqa: E402

from core.infrastructure.tia.tia_helpers import (  # noqa: E402
    _ensure_target_dir,
    _export_objects_sd,
    _find_plc,
    _find_plc_tag_table,
    _get_active_project,
    _safe_get_block_name,
    _safe_get_block_path,
    _safe_get_table_name,
    _safe_short_designation,
)

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


# ---------------------------------------------------------------------------
# Handlers de ciclo de vida (migrados a tia_cmd_lifecycle.py).
# Los re-exports arriba preservan compat con callers legacy hasta el commit 10.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Handlers de proyecto (migrados a tia_cmd_project.py).
# Los re-exports arriba preservan compat con callers legacy hasta el commit 10.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Handlers de inspeccion (migrados a tia_cmd_inspect.py + _scan_block_group_recursive
# como privada del modulo).
# Los re-exports arriba preservan compat con callers legacy hasta el commit 10.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Handlers de compilacion
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Handlers de compilacion (migrados a tia_cmd_compile.py).
# Los re-exports arriba preservan compat con callers legacy hasta el commit 10.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Handlers de export (migrados a tia_cmd_export.py).
# Los re-exports arriba preservan compat con callers legacy hasta el commit 10.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Handlers de import (migrados a tia_cmd_import_.py).
# Los re-exports arriba preservan compat con callers legacy hasta el commit 10.
# Importante: el fix critico de ``target_folder_path=""`` (TIA V21) se
# preserva en el nuevo modulo.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Handlers de constantes de usuario (N_MAX) (migrados a tia_cmd_user_consts.py).
# Los re-exports arriba preservan compat con callers legacy hasta el commit 10.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Handler transaccional (migrado a tia_cmd_batch.py).
# Los re-exports arriba preservan compat con callers legacy hasta el commit 10.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Registry (delegado en tia_commands_catalog.py).
# El shim ``register_core_commands`` se preserva por compat hasta el commit 10.
# ---------------------------------------------------------------------------
def register_core_commands(target: "SyncTIAClient") -> None:  # noqa: ARG001
    """Shim de compat: delega en ``tia_commands_catalog.register_all_commands``.

    Mantenido hasta el commit 10 para no romper callers legacy. Tras ese
    commit, este shim desaparece junto con ``tia_handlers.py``.
    """
    from core.infrastructure.tia.tia_commands_catalog import register_all_commands
    register_all_commands(target)
