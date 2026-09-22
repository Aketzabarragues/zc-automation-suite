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
# Handlers de constantes de usuario (N_MAX)
# ---------------------------------------------------------------------------
def _h_get_user_constants(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Devuelve {value_str: name} de las PlcUserConstant de una tabla.

    Solo incluye constantes cuyo Value es parseable como int.
    """
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    table = _find_plc_tag_table(target_plc, table_name)

    result: dict[str, str] = {}
    for constant in table.get_user_constants():
        raw_value = constant.get_property(name="Value")
        try:
            int_value = int(str(raw_value).strip())
        except (TypeError, ValueError):
            continue
        name = constant.get_property(name="Name")
        result[str(int_value)] = str(name)
    return {"constants": result}


def _h_delete_user_constant(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Borra una PlcUserConstant (manual §2.34.4)."""
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    constant_name: str = args.get("constant_name", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not constant_name:
        raise ValueError("Se requiere el argumento 'constant_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    table = _find_plc_tag_table(target_plc, table_name)

    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == constant_name:
            constant.delete()
            return {"deleted": True, "constant": constant_name}

    raise RuntimeError(
        f"Constante '{constant_name}' no encontrada en tabla '{table_name}'."
    )


def _h_update_user_constant_value(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Actualiza el valor de una PlcUserConstant (N_MAX) (manual §2.28).

    Doble validacion: set_property puede retornar !=0 sin lanzar
    excepcion en TIA V21. Tambien relee para confirmar que el valor
    real coincide (set_property puede retornar 0 OK sin aplicar cambio).
    """
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    constant_name: str = args.get("constant_name", "")
    new_value: int = args.get("new_value", 0)

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not constant_name:
        raise ValueError("Se requiere el argumento 'constant_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    table = _find_plc_tag_table(target_plc, table_name)

    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == constant_name:
            rc = constant.set_property(name="Value", value=str(new_value))
            if rc != 0:
                raise RuntimeError(
                    f"N_MAX '{constant_name}' en tabla '{table_name}': "
                    f"TIA rechazo la modificacion (codigo de retorno {rc}). "
                    f"Valor intentado: '{new_value}'."
                )
            actual = constant.get_property(name="Value")
            if str(actual).strip() != str(new_value).strip():
                raise RuntimeError(
                    f"N_MAX '{constant_name}' en tabla '{table_name}': "
                    f"set_property retorno 0 (OK) pero el valor real en TIA "
                    f"es '{actual}', no '{new_value}'. Posible fallo "
                    f"silencioso de Pythonnet/TIA V21."
                )
            return {"updated": True, "constant": constant_name, "value": new_value}

    raise RuntimeError(
        f"Constante '{constant_name}' no encontrada en tabla '{table_name}'."
    )


def _h_update_user_constant_name(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Renombra una PlcUserConstant (manual §2.28).

    Doble validacion analog a update_user_constant_value.
    """
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    current_name: str = args.get("current_name", "")
    new_name: str = args.get("new_name", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not current_name:
        raise ValueError("Se requiere el argumento 'current_name'.")
    if not new_name:
        raise ValueError("Se requiere el argumento 'new_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    table = _find_plc_tag_table(target_plc, table_name)

    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == current_name:
            rc = constant.set_property(name="Name", value=new_name)
            if rc != 0:
                raise RuntimeError(
                    f"Rename '{current_name}' -> '{new_name}' en tabla "
                    f"'{table_name}': TIA rechazo la modificacion "
                    f"(codigo de retorno {rc})."
                )
            actual = constant.get_property(name="Name")
            if actual != new_name:
                raise RuntimeError(
                    f"Rename '{current_name}' -> '{new_name}' en tabla "
                    f"'{table_name}': set_property retorno 0 (OK) pero el "
                    f"nombre real en TIA es '{actual}', no '{new_name}'. "
                    f"Posible fallo silencioso de Pythonnet/TIA V21."
                )
            return {
                "updated": True,
                "old_name": current_name,
                "new_name": new_name,
            }

    raise RuntimeError(
        f"Constante '{current_name}' no encontrada en tabla '{table_name}'."
    )


# ---------------------------------------------------------------------------
# Handler transaccional (lote atomico con rollback)
# ---------------------------------------------------------------------------
_TRANSACTION_FORBIDDEN_COMMANDS: frozenset[str] = frozenset(
    {
        "open_project",
        "close_project",
        "save_project",
        "list_plcs",
        "compile_plc",
        "compile_blocks",
        "execute_transactional_batch",
        "attach_portal",
        "open_new_portal",
    }
)


def _h_execute_transactional_batch(
    args: dict, tia_client: "SyncTIAClient",
) -> dict:
    """Ejecuta varios comandos bajo una sola transaccion de TIA Portal.

    Si cualquier handler falla, rollback de toda la cadena.
    """
    undo_text: str = args.get("undo_text", "Operacion por lote")
    operations: list[dict] = args.get("operations", [])

    if not operations:
        raise ValueError("La lista de operaciones esta vacia.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)

    # Iniciar transaccion nativa (manual §2.37.27).
    project.start_transaction(undo_text=undo_text, dialog_text=undo_text)

    results_list: list[dict] = []
    cmd: str = ""
    cmd_args: dict = {}
    try:
        for idx, op in enumerate(operations):
            cmd = op.get("command", "")
            cmd_args = op.get("args", {})

            # ``_wait`` es un sub-comando especial: sleep bloqueante
            # local sin tocar TIA. Sirve para dar tiempo a TIA Portal
            # a consolidar entre un import y otro dentro de la
            # transaccion (import_tags -> wait -> import_blocks). El
            # OT worker corre en hilo sync, asi que ``time.sleep`` es
            # valido (no hay event loop del que salir).
            if cmd == "_wait":
                seconds = float(cmd_args.get("seconds", 0))
                time.sleep(seconds)
                results_list.append({
                    "step": idx + 1,
                    "command": cmd,
                    "result": f"sleep {seconds}s",
                })
                continue

            if cmd in _TRANSACTION_FORBIDDEN_COMMANDS:
                raise ValueError(
                    f"El comando '{cmd}' esta prohibido dentro de un lote "
                    "transaccional."
                )

            dispatch_out = tia_client.dispatch(cmd, cmd_args)

            if not dispatch_out.get("ok"):
                raise RuntimeError(
                    f"sub-comando '{cmd}' fallo: "
                    f"{dispatch_out.get('error', '?')}"
                )

            step_result = dispatch_out.get("result")
            results_list.append({
                "step": idx + 1,
                "command": cmd,
                "result": step_result,
            })

            if step_result is False:
                raise RuntimeError(
                    f"Lote abortado: op '{cmd}' retorno False en paso "
                    f"{idx + 1}. Rollback ejecutado."
                )

        project.end_transaction(rollback=False)

        return {
            "success": True,
            "operations_executed": len(operations),
            "details": results_list,
        }

    except Exception as exc:
        try:
            project.end_transaction(rollback=True)
        except Exception:
            pass
        try:
            args_str = _json.dumps(cmd_args, ensure_ascii=False, default=str)[:500]
        except Exception:
            args_str = repr(cmd_args)[:500]
        raise RuntimeError(
            f"Lote abortado en el paso {len(results_list) + 1} ('{cmd}'). "
            f"Args: {args_str}. "
            f"Rollback ejecutado. Motivo: {exc}"
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def register_core_commands(target: "SyncTIAClient") -> None:
    """Registra los 26 comandos core en ``target``.

    Si un comando ya esta registrado, ``register_command()`` lanza
    ValueError. El caller decide si reinstancia o ignora.
    """
    target.register_command("attach_portal", _h_attach_portal)
    target.register_command("detach_portal", _h_detach_portal)
    target.register_command("open_new_portal", _h_open_new_portal)
    target.register_command("open_project", _h_open_project)
    target.register_command("save_project", _h_save_project)
    target.register_command("close_project", _h_close_project)
    target.register_command("ping", _h_ping)
    target.register_command("list_blocks", _h_list_blocks)
    target.register_command("list_plcs", _h_list_plcs)
    target.register_command("get_project_info", _h_get_project_info)
    target.register_command("scan_blocks", _h_scan_blocks)
    target.register_command("compile_plc", _h_compile_plc)
    target.register_command("compile_blocks", _h_compile_blocks)
    target.register_command("export_blocks_sd", _h_export_blocks_sd)
    target.register_command("export_udts_sd", _h_export_udts_sd)
    target.register_command("export_plc_tags_xml", _h_export_plc_tags_xml)
    target.register_command("import_blocks_sd", _h_import_blocks_sd)
    target.register_command("import_plc_tags_xml", _h_import_plc_tags_xml)
    target.register_command("export_block", _h_export_block)
    target.register_command("export_tag_table", _h_export_tag_table)
    target.register_command("import_tag_table", _h_import_tag_table)
    target.register_command("import_block", _h_import_block)
    target.register_command("get_user_constants", _h_get_user_constants)
    target.register_command("update_user_constant_value", _h_update_user_constant_value)
    target.register_command("update_user_constant_name", _h_update_user_constant_name)
    target.register_command("delete_user_constant", _h_delete_user_constant)
    target.register_command(
        "execute_transactional_batch", _h_execute_transactional_batch
    )
