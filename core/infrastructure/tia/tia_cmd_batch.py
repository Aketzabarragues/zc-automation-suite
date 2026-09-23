"""core.infrastructure.tia.tia_cmd_batch - comandos de lote.

Dos comandos:

  - execute_transactional_batch: ejecuta N comandos bajo UNA transaccion
    de TIA Portal. Si cualquier handler falla, rollback de toda la cadena.
  - execute_batch: ejecuta N comandos en serie SIN transaccion. Best-effort:
    si un sub-comando falla, continua con los siguientes y reporta los
    errores al final. Pensado para READS (export_*, scan_blocks, list_*,
    ping, get_user_constants) y para batches grandes donde se prefiere
    continuidad a atomicidad (p. ej. regenerar un preview).

Restricciones arquitectonicas:
  - El sub-comando especial ``_wait`` (sleep bloqueante local) es valido
    dentro de AMBOS lotes (transaccional y no). Sirve para dar tiempo
    a TIA Portal a consolidar entre un export y otro dentro del lote.
  - En ``execute_transactional_batch`` los comandos prohibidos (los de
    lifecycle, los de compile, los de listado, y el propio batch) se
    validan en ``_TRANSACTION_FORBIDDEN_COMMANDS`` (visible como privado
    del modulo para tests).
  - En ``execute_batch`` NO hay lista de prohibidos: el caller decide
    que mezcla de comandos envia. Si mete imports/updates, NO habra
    rollback atómico (usar ``execute_transactional_batch`` para eso).

Cada handler es una FC pura: recibe ``(args: dict, tia_client: SyncTIAClient)``
y devuelve ``dict``. Acceso a portal via ``tia_client.wrapper`` (single-threaded;
lo toca el tia-loop).
"""
from __future__ import annotations

import json as _json
import logging
import time
from typing import TYPE_CHECKING, Any

from core.infrastructure.tia.tia_helpers import _get_active_project

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


# Comandos prohibidos dentro de un lote transaccional. Se excluyen los
# de lifecycle (open/close/save_project, attach/detach/open_new_portal),
# los de compile (rompen el modelo transaccional si se anida), los de
# listado (no tiene sentido ejecutar un ping dentro de una tx) y el
# propio execute_transactional_batch (no se admite nesting).
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


def _h_execute_batch(
    args: dict, tia_client: "SyncTIAClient",
) -> dict:
    """Ejecuta N comandos en serie SIN transaccion de TIA Portal.

    Best-effort: si un sub-comando falla, se reporta en su entrada de
    ``details`` pero el lote CONTINUA con los siguientes. El handler
    final devuelve ``success=False`` si hubo algun fallo, mas nunca
    aborta a la primera (la idea es que un fallo de export no impida
    que el resto de exports se ejecuten y la SPA reciba la maxima
    informacion posible).

    Cada entrada de ``details`` lleva:
      - ``step``: 1-indexed step number.
      - ``command``: nombre del sub-comando.
      - ``ok``: True si el dispatch devolvio ok=True y result != False.
      - ``result``: dict/valor devuelto por el handler (si ok=True).
      - ``error``: mensaje de error (si ok=False).

    Sub-comando especial ``_wait``:
      Misma semantica que en ``_h_execute_transactional_batch``:
      ``{"command": "_wait", "args": {"seconds": N}}`` produce un
      sleep bloqueante local sin tocar TIA. Util para consolidar
      entre exports (export_block -> _wait -> export_plc_tags_xml).

    Restricciones arquitectonicas (deliberadamente mas laxas que
    ``_h_execute_transactional_batch``):
      - NO hay lista de prohibidos: el caller envia lo que necesita.
      - NO se admite nesting del propio ``execute_batch`` (se rechaza
        para evitar recursion infinita). ``execute_transactional_batch``
        SI es admisible como sub-comando (anidamiento explicito).
    """
    operations: list[dict] = args.get("operations", [])

    if not operations:
        raise ValueError("La lista de operaciones esta vacia.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )

    details: list[dict] = []
    any_failed = False
    cmd: str = ""
    cmd_args: dict = {}

    for idx, op in enumerate(operations):
        cmd = op.get("command", "")
        cmd_args = op.get("args", {})

        if cmd == "execute_batch":
            details.append({
                "step": idx + 1,
                "command": cmd,
                "ok": False,
                "error": "execute_batch no admite nesting (recursion).",
            })
            any_failed = True
            continue

        if cmd == "_wait":
            seconds = float(cmd_args.get("seconds", 0))
            time.sleep(seconds)
            details.append({
                "step": idx + 1,
                "command": cmd,
                "ok": True,
                "result": f"sleep {seconds}s",
            })
            continue

        try:
            dispatch_out = tia_client.dispatch(cmd, cmd_args)
            if not dispatch_out.get("ok"):
                details.append({
                    "step": idx + 1,
                    "command": cmd,
                    "ok": False,
                    "error": dispatch_out.get("error", "?"),
                })
                any_failed = True
                continue

            step_result = dispatch_out.get("result")
            if step_result is False:
                details.append({
                    "step": idx + 1,
                    "command": cmd,
                    "ok": False,
                    "error": f"sub-comando retorno False",
                })
                any_failed = True
                continue

            details.append({
                "step": idx + 1,
                "command": cmd,
                "ok": True,
                "result": step_result,
            })
        except Exception as exc:
            details.append({
                "step": idx + 1,
                "command": cmd,
                "ok": False,
                "error": repr(exc)[:500],
            })
            any_failed = True

    return {
        "success": not any_failed,
        "operations_executed": len(operations),
        "operations_failed": sum(1 for d in details if not d["ok"]),
        "details": details,
    }


# Mapa nombre → handler. El registro central (tia_commands_catalog)
# importará este dict para registrar ambos comandos en el worker.
COMMANDS: dict[str, Any] = {
    "execute_transactional_batch": _h_execute_transactional_batch,
    "execute_batch": _h_execute_batch,
}


__all__ = [
    "COMMANDS",
    "_TRANSACTION_FORBIDDEN_COMMANDS",
    "_h_execute_transactional_batch",
    "_h_execute_batch",
]
