"""Comandos del worker OT específicos del área alimentación.

Viven AQUÍ (no en ``core.infrastructure.tia.worker_tia``) para que el
motor OT permanezca genérico y no sepa qué es "alimentación". La
transacción atómica sigue funcionando porque estos handlers corren
DENTRO del proceso del worker, bajo el mismo
``start_transaction`` / ``end_transaction`` que cualquier otro
comando del lote.

Refactor de ``_make_cmd_update_disp_comments_db`` (antes en
``core.infrastructure.tia.worker_tia``, líneas 484-556) y de los 6
entries ``update_disp_comments_db_*`` del ``COMMAND_REGISTRY``.

Punto de extensión cableado por ``AreaSpec.contributes_tia_commands``
y consumido al arrancar el worker vía
``core.infrastructure.tia.command_loader.load_extra_commands``.

Restricción arquitectónica (``.clinerules`` §1): este módulo NO
importa ``siemens_tia_scripting``. Solo aporta ``Callable`` con firma
``(portal, ts, args) -> dict`` que el worker invocará dentro de su
proceso. El import local de ``DispCommentUpdater`` ocurre dentro del
handler para preservar el comportamiento offline-first del worker
(la pieza SD se carga solo cuando el handler se ejecuta, no al
import del módulo).
"""
from __future__ import annotations

import os
from typing import Any, Callable


# Tipos de dispositivo soportados por los DBs de array. Mantener en
# sync con ``areas/alimentacion/domain/models/dispositivos.py``.
EXTRA_HW_TYPES: tuple[str, ...] = (
    "ed",
    "ea",
    "sa",
    "v",
    "m",
    "m_vf",
)


def make_cmd_update_disp_comments_db(hw_type: str) -> Callable[..., Any]:
    """Factory que genera un handler atómico para el DB de ``hw_type``.

    El ``hw_type`` se queda capturado en el closure para etiquetar el
    retorno y poder trazarlo en logs / historial de TIA.

    El handler:
      1. Exporta selectivamente el DB objetivo (``export_block``).
      2. Aplica el updater offline ``DispCommentUpdater`` sobre los
         ``.s7dcl`` / ``.s7res`` exportados.
      3. Si hubo cambios, re-importa el bloque al proyecto
         (``import_block``).

    Vive dentro de la transacción que abrió
    ``execute_transactional_batch`` en el lote (no abre transacción
    propia); es atómico respecto al lote.
    """
    def _cmd(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        db_name: str = args.get("db_name", "")
        db_array_name: str = args.get("db_array_name", "")
        slot_map: dict[str, str] = args.get("slot_map", {})
        work_dir: str = args.get("work_dir", "")
        target_folder: str = args.get("target_folder", "")

        if not (plc_name and db_name and db_array_name and work_dir and target_folder):
            raise ValueError(
                f"update_disp_comments_db_{hw_type}: args incompletos. "
                f"Recibido: plc_name={plc_name!r} db_name={db_name!r} "
                f"db_array_name={db_array_name!r} work_dir={work_dir!r} "
                f"target_folder={target_folder!r}"
            )

        # Coerción: slot_map llega con keys str (JSON); el updater quiere int.
        slot_map_int: dict[int, str] = {int(k): v for k, v in slot_map.items()}

        # Import local: solo se carga cuando el handler se invoca
        # (cumple "offline-first" del worker, igual que antes). Apunta
        # a la nueva ubicación del paquete SD (PR 3).
        from areas.alimentacion.infrastructure.sd.disp_comment_updater import (
            DispCommentUpdater,
        )

        s7dcl_path = os.path.join(work_dir, f"{db_name}.s7dcl")
        s7res_path = os.path.join(work_dir, f"{db_name}.s7res")

        # Import lazy del worker para evitar el ciclo
        # ``worker_tia → command_loader → AreaRegistry → areas.<area> →
        # extra_commands → (lazy) worker_tia``. En el momento en que se
        # invoca el handler, ``worker_tia`` ya está completamente cargado.
        from core.infrastructure.tia import worker_tia
        core_registry = worker_tia.COMMAND_REGISTRY

        # 1. EXPORT SELECTIVO (reusa ``export_block`` del core).
        core_registry["export_block"](portal, ts, {
            "plc_name":   plc_name,
            "block_name": db_name,
            "target_dir": work_dir,
        })

        # 2. Updater offline.
        updater = DispCommentUpdater(
            s7dcl_path=s7dcl_path,
            s7res_path=s7res_path,
            slot_map=slot_map_int,
            db_array_name=db_array_name,
        )
        result = updater.update()
        updater.save()

        # 3. IMPORT SELECTIVO (reusa ``import_block`` del core) — solo si
        #    el updater modificó algo, para no ensuciar el historial Undo.
        if updater.was_modified():
            core_registry["import_block"](portal, ts, {
                "plc_name":      plc_name,
                "import_dir":    work_dir,
                "target_folder": target_folder,
            })

        return {
            "hw_type":           hw_type,
            "db_name":           db_name,
            "modified":          updater.was_modified(),
            "disp_comment_result": {
                "reused":            result.reused,
                "inserted":          result.inserted,
                "no_usar_mlc":       result.no_usar_mlc,
                "total_mlcs_in_res": result.total_mlcs_in_res,
            },
        }

    return _cmd


def register(registry: dict[str, Callable[..., Any]]) -> None:
    """Aporta los 6 comandos ``update_disp_comments_db_*`` al registry.

    Muta ``registry`` in-place. Es seguro llamarla varias veces (los
    handlers se machacan por nombre, no se duplican).
    """
    for hw in EXTRA_HW_TYPES:
        registry[f"update_disp_comments_db_{hw}"] = make_cmd_update_disp_comments_db(hw)


__all__ = ["EXTRA_HW_TYPES", "make_cmd_update_disp_comments_db", "register"]
