"""Comandos TIA del area alimentacion.

Aporta al SyncTIAClient los handlers de sync de comentarios
dispositivos/procesos + commits online/offline de devices + N_MAX.

Restriccion: este modulo NO importa siemens_tia_scripting. Los
imports de DispCommentUpdater y ProcCommentUpdater son lazy dentro
de cada handler (carga offline solo cuando se ejecuta, no al import
del modulo).
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Callable

from core.infrastructure.tia.tia_export_paths import SdPair

logger = logging.getLogger(__name__)


# Tipos de dispositivo soportados por los DBs de array. Mantener en
# sync con areas/alimentacion/domain/models/dispositivos.py.
EXTRA_HW_TYPES: tuple[str, ...] = (
    "ed",
    "ea",
    "sa",
    "v",
    "m",
    "m_vf",
)

# Kinds de procesos.
EXTRA_PROC_KINDS: tuple[str, ...] = ("preal", "pint", "alm")


# ---------------------------------------------------------------------------
# Handlers de comentarios de dispositivos (1 por hw_type)
# ---------------------------------------------------------------------------
def make_cmd_update_disp_comments_db(hw_type: str) -> Callable[..., Any]:
    """Handler atomico para el DB de ``hw_type``.

    Pasos:
      1. Export selectivo del DB (export_block).
      2. DispCommentUpdater offline sobre los .s7dcl/.s7res exportados.
      3. Si hubo cambios, re-import del bloque (import_block).

    NO abre tx propia: corre dentro de la tx del lote. El IT hace
    export + copytree UNA VEZ antes del batch (modified_bloques/).

    Args:
        plc_name, db_name, db_array_name, slot_map, work_dir,
        target_folder.
    """
    def _cmd(args: dict[str, Any], tia_client: Any) -> dict[str, Any]:
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

        slot_map_int: dict[int, str] = {int(k): v for k, v in slot_map.items()}

        from areas.alimentacion.helpers.sd.disp_comment_updater import (
            DispCommentUpdater,
        )

        s7dcl_path = SdPair(Path(work_dir), db_name).dcl
        s7res_path = SdPair(Path(work_dir), db_name).res

        tia_client._handlers["export_block"]({
            "plc_name": plc_name,
            "block_name": db_name,
            "target_dir": work_dir,
        }, tia_client)

        updater = DispCommentUpdater(
            s7dcl_path=s7dcl_path,
            s7res_path=s7res_path,
            slot_map=slot_map_int,
            db_array_name=db_array_name,
        )
        result = updater.update()
        updater.save()

        if updater.was_modified():
            tia_client._handlers["import_block"]({
                "plc_name": plc_name,
                "import_dir": work_dir,
                "target_folder": target_folder,
            }, tia_client)

        return {
            "hw_type": hw_type,
            "db_name": db_name,
            "modified": updater.was_modified(),
            "disp_comment_result": {
                "reused": result.reused,
                "inserted": result.inserted,
                "no_usar_mlc": result.no_usar_mlc,
                "total_mlcs_in_res": result.total_mlcs_in_res,
            },
        }

    return _cmd


# ---------------------------------------------------------------------------
# Handlers de commits online (N_MAX + renames) y offline (devices)
# ---------------------------------------------------------------------------
def make_cmd_commit_disp_nmax_renames_online() -> Callable[..., Any]:
    """Aplica N_MAX + renames en una tx TIA propia (online puro).

    A diferencia de commit_devices_sync (que mezclaba online+offline
    en la misma tx y provocaba rollback silencioso en TIA V21), este
    handler abre y cierra su propia start_transaction y solo hace
    cambios online: update_user_constant_value por N_MAX +
    update_user_constant_name por renames.

    Los cambios offline (devices) van en otro handler
    (make_cmd_commit_disp_devices_offline) en otra tx TIA, llamada
    secuencialmente desde IT.
    """
    def _cmd(args: dict[str, Any], tia_client: Any) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        undo_text: str = args.get("undo_text", "Sync N_MAX + renames (online)")
        nmax_ops: list[dict[str, Any]] = args.get("nmax_ops") or []
        rename_ops: list[dict[str, Any]] = args.get("rename_ops") or []

        if not plc_name:
            raise ValueError("commit_disp_nmax_renames_online: plc_name requerido.")

        from core.infrastructure.tia import tia_helpers
        from core.infrastructure.tia.tia_handlers import (
            _h_update_user_constant_value,
            _h_update_user_constant_name,
        )

        portal = tia_client.wrapper
        project = tia_helpers._get_active_project(portal)
        tia_helpers._find_plc(project, plc_name)  # valida que existe

        results_list: list[dict[str, Any]] = []
        step_idx = 0

        def _record(op_name: str, result: Any) -> None:
            nonlocal step_idx
            step_idx += 1
            results_list.append({"step": step_idx, "command": op_name, "result": result})

        project.start_transaction(undo_text=undo_text, dialog_text=undo_text)
        op_label = "start_transaction"
        try:
            for nmax_op in nmax_ops:
                op_label = f"update_user_constant_value({nmax_op.get('constant_name')})"
                r = _h_update_user_constant_value({
                    "plc_name": plc_name,
                    "table_name": nmax_op["table_name"],
                    "constant_name": nmax_op["constant_name"],
                    "new_value": nmax_op["new_value"],
                }, tia_client)
                _record("update_user_constant_value", r)

            for rename_op in rename_ops:
                op_label = (
                    f"update_user_constant_name("
                    f"{rename_op.get('table_name')}:"
                    f"{rename_op.get('current_name')}->"
                    f"{rename_op.get('new_name')})"
                )
                r = _h_update_user_constant_name({
                    "plc_name": plc_name,
                    "table_name": rename_op["table_name"],
                    "current_name": rename_op["current_name"],
                    "new_name": rename_op["new_name"],
                }, tia_client)
                _record("update_user_constant_name", r)

            project.end_transaction(rollback=False)
        except Exception as e:
            try:
                project.end_transaction(rollback=True)
            except Exception:
                pass
            raise RuntimeError(
                f"commit_disp_nmax_renames_online abortado en '{op_label}'. "
                f"Rollback ejecutado. Motivo: {e}"
            ) from e

        return {
            "success": True,
            "operations_executed": step_idx,
            "details": results_list,
        }

    return _cmd


def make_cmd_commit_disp_devices_offline() -> Callable[..., Any]:
    """Aplica device changes (import) en una tx TIA propia (offline puro).

    Patron:
      1. export masivo (export_blocks_sd) al snapshot limpio.
      2. TagTableModifier offline sobre los .s7dcl exportados.
      3. import_blocks_sd masivo al PLC.
    """
    def _cmd(args: dict[str, Any], tia_client: Any) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        undo_text: str = args.get("undo_text", "Sync devices (offline)")
        modified_dir: str = args.get("modified_dir", "")
        target_folder: str = args.get("target_folder", "")
        db_subpath: str = args.get("db_subpath", "")
        exports_subdir: str = args.get("exports_subdir", "") or ""

        if not (plc_name and modified_dir and target_folder):
            raise ValueError(
                "commit_disp_devices_offline: plc_name, modified_dir y "
                "target_folder son requeridos."
            )

        from core.infrastructure.tia import tia_helpers
        from areas.alimentacion.helpers.xml.disp_tag_table_modifier import (
            DispTagTableModifier,
        )

        portal = tia_client.wrapper
        project = tia_helpers._get_active_project(portal)
        tia_helpers._find_plc(project, plc_name)

        effective_modified = (
            str(Path(modified_dir) / db_subpath) if db_subpath else modified_dir
        )
        effective_exports = (
            str(Path(exports_subdir) / db_subpath) if (exports_subdir and db_subpath)
            else exports_subdir
        )

        project.start_transaction(undo_text=undo_text, dialog_text=undo_text)
        try:
            # 1. Export masivo al snapshot limpio (si se pasa).
            if effective_exports:
                tia_client._handlers["export_blocks_sd"]({
                    "plc_name": plc_name,
                    "target_dir": effective_exports,
                }, tia_client)
                if Path(effective_exports).exists():
                    shutil.copytree(
                        effective_exports, effective_modified,
                        dirs_exist_ok=True,
                    )
                else:
                    Path(effective_modified).mkdir(parents=True, exist_ok=True)

            # 2. Modifier offline (tag tables).
            modifier = DispTagTableModifier(
                modified_dir=Path(effective_modified),
                exports_dir=Path(effective_exports) if effective_exports else None,
            )
            modifier.run()
            modified = modifier.was_modified

            # 3. Import masivo (si hubo cambios).
            if modified:
                tia_client._handlers["import_blocks_sd"]({
                    "plc_name": plc_name,
                    "import_dir": modified_dir,
                    "target_folder": target_folder,
                }, tia_client)

            project.end_transaction(rollback=False)
        except Exception as e:
            try:
                project.end_transaction(rollback=True)
            except Exception:
                pass
            raise

        return {
            "success": True,
            "modified": modified,
            "plc_name": plc_name,
        }

    return _cmd


def make_cmd_commit_devices_sync() -> Callable[..., Any]:
    """DEPRECATED. Usar commit_disp_nmax_renames_online + commit_disp_devices_offline.

    Mantenido por compat con callers legacy que aún invocan este nombre.
    """
    def _cmd(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "commit_devices_sync esta DEPRECATED. Usar "
            "commit_disp_nmax_renames_online + commit_disp_devices_offline."
        )

    return _cmd


# ---------------------------------------------------------------------------
# Handlers de comentarios de procesos (1 por kind + 1 combinado PARAM)
# ---------------------------------------------------------------------------
def make_cmd_update_proc_comments_db(kind: str) -> Callable[..., Any]:
    """Handler atomico para el DB de procesos del ``kind``.

    kind: 'preal' | 'pint' | 'alm'.

    Pasos:
      1. Export selectivo del DB (export_block).
      2. ProcCommentUpdater offline sobre los .s7dcl/.s7res exportados.
      3. Si hubo cambios, re-import del bloque (import_block).
    """
    def _cmd(args: dict[str, Any], tia_client: Any) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        db_name: str = args.get("db_name", "")
        array_name: str = args.get("array_name", "")
        slot_map_raw: dict[str, str] = args.get("slot_map", {}) or {}
        work_dir: str = args.get("work_dir", "")
        target_folder: str = args.get("target_folder", "")
        db_subpath: str = args.get("db_subpath", "")
        exports_subdir: str = args.get("exports_subdir", "") or ""

        if not (plc_name and db_name and array_name and work_dir and target_folder):
            raise ValueError(
                f"update_proc_comments_db_{kind}: args incompletos."
            )

        slot_map: dict[int, str] = {
            int(k): v for k, v in slot_map_raw.items() if int(k) >= 1
        }

        effective_work_dir = (
            str(Path(work_dir) / db_subpath) if db_subpath else work_dir
        )

        from areas.alimentacion.helpers.sd.proc_comment_updater import (
            ProcCommentUpdater,
        )
        from areas.alimentacion.helpers.sd.mlc_registry import MLCRegistry

        s7dcl_path = SdPair(Path(effective_work_dir), db_name).dcl
        s7res_path = SdPair(Path(effective_work_dir), db_name).res

        if exports_subdir:
            export_target_dir = (
                str(Path(exports_subdir) / db_subpath)
                if db_subpath else exports_subdir
            )
            tia_client._handlers["export_block"]({
                "plc_name": plc_name,
                "block_name": db_name,
                "target_dir": export_target_dir,
            }, tia_client)
            if Path(export_target_dir).exists():
                shutil.copytree(
                    export_target_dir, effective_work_dir,
                    dirs_exist_ok=True,
                )
            else:
                Path(effective_work_dir).mkdir(parents=True, exist_ok=True)
        else:
            tia_client._handlers["export_block"]({
                "plc_name": plc_name,
                "block_name": db_name,
                "target_dir": effective_work_dir,
            }, tia_client)

        updater = ProcCommentUpdater(
            s7dcl_path=s7dcl_path,
            s7res_path=s7res_path,
            slot_map=slot_map,
            array_name=array_name,
            satellite_arrays=set(_PROC_SATELLITES.get(kind, set())),
            registry=MLCRegistry(),
        )
        result = updater.update()
        updater.save()
        modified = updater.was_modified()

        if modified:
            tia_client._handlers["import_block"]({
                "plc_name": plc_name,
                "import_dir": work_dir,
                "target_folder": "",
            }, tia_client)

        return {
            "kind": kind,
            "db_name": db_name,
            "array_name": array_name,
            "modified": modified,
            "proc_comment_result": {
                "reused": result.reused,
                "inserted": result.inserted,
                "satellite_reused": result.satellite_reused,
                "satellite_inserted": result.satellite_inserted,
                "total_mlcs_in_res": result.total_mlcs_in_res,
            },
        }

    return _cmd


def make_cmd_update_proc_comments_db_param() -> Callable[..., Any]:
    """Handler combinado para los 2 arrays del DB PARAM (PReal + PInt).

    Razon: si se enviaran 2 ops separadas (PReal, PInt) sobre el mismo
    DB, la segunda op SOBREESCRIBIA el .s7dcl/.s7res en exports/ con un
    export fresco de TIA (sin el cambio de PReal). Solucion: 1 solo
    export_block, 2 llamadas al ProcCommentUpdater sobre el MISMO
    archivo, 1 solo import_block al final.

    Args:
        plc_name, db_name, preal_slot_map, pint_slot_map, work_dir,
        target_folder, db_subpath (opcional), exports_subdir (opcional).
    """
    def _cmd(args: dict[str, Any], tia_client: Any) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        db_name: str = args.get("db_name", "")
        preal_slot_map_raw: dict[str, str] = args.get("preal_slot_map", {}) or {}
        pint_slot_map_raw: dict[str, str] = args.get("pint_slot_map", {}) or {}
        work_dir: str = args.get("work_dir", "")
        target_folder: str = args.get("target_folder", "")
        db_subpath: str = args.get("db_subpath", "")
        exports_subdir: str = args.get("exports_subdir", "") or ""

        if not (plc_name and db_name and work_dir and target_folder):
            raise ValueError(
                f"update_proc_comments_db_param: args incompletos. "
                f"Recibido: plc_name={plc_name!r} db_name={db_name!r} "
                f"work_dir={work_dir!r} target_folder={target_folder!r}"
            )

        preal_slot_map: dict[int, str] = {
            int(k): v for k, v in preal_slot_map_raw.items() if int(k) >= 1
        }
        pint_slot_map: dict[int, str] = {
            int(k): v for k, v in pint_slot_map_raw.items() if int(k) >= 1
        }

        effective_work_dir = (
            str(Path(work_dir) / db_subpath) if db_subpath else work_dir
        )

        from areas.alimentacion.helpers.sd.proc_comment_updater import (
            ProcCommentUpdater,
        )
        from areas.alimentacion.helpers.sd.mlc_registry import MLCRegistry

        s7dcl_path = SdPair(Path(effective_work_dir), db_name).dcl
        s7res_path = SdPair(Path(effective_work_dir), db_name).res

        # 1. Un solo export_block sobre el DB PARAM.
        if exports_subdir:
            export_target_dir = (
                str(Path(exports_subdir) / db_subpath)
                if db_subpath else exports_subdir
            )
            tia_client._handlers["export_block"]({
                "plc_name": plc_name,
                "block_name": db_name,
                "target_dir": export_target_dir,
            }, tia_client)
            if Path(export_target_dir).exists():
                shutil.copytree(
                    export_target_dir, effective_work_dir,
                    dirs_exist_ok=True,
                )
            else:
                Path(effective_work_dir).mkdir(parents=True, exist_ok=True)
        else:
            tia_client._handlers["export_block"]({
                "plc_name": plc_name,
                "block_name": db_name,
                "target_dir": effective_work_dir,
            }, tia_client)

        # 2. updater PReal.
        preal_result = None
        preal_modified = False
        if preal_slot_map:
            updater_preal = ProcCommentUpdater(
                s7dcl_path=s7dcl_path,
                s7res_path=s7res_path,
                slot_map=preal_slot_map,
                array_name="PReal",
                satellite_arrays=set(_PROC_SATELLITES["preal"]),
                registry=MLCRegistry(),
            )
            preal_result = updater_preal.update()
            updater_preal.save()
            preal_modified = updater_preal.was_modified()

        # 3. updater PInt (sobre el mismo archivo ya modificado por PReal).
        pint_result = None
        pint_modified = False
        if pint_slot_map:
            updater_pint = ProcCommentUpdater(
                s7dcl_path=s7dcl_path,
                s7res_path=s7res_path,
                slot_map=pint_slot_map,
                array_name="PInt",
                satellite_arrays=set(_PROC_SATELLITES["pint"]),
                registry=MLCRegistry(),
            )
            pint_result = updater_pint.update()
            updater_pint.save()
            pint_modified = updater_pint.was_modified()

        # 4. Un solo import_block si alguno modifico.
        any_modified = preal_modified or pint_modified
        if any_modified:
            tia_client._handlers["import_block"]({
                "plc_name": plc_name,
                "import_dir": work_dir,
                "target_folder": "",
            }, tia_client)

        return {
            "kind": "param",
            "db_name": db_name,
            "modified": any_modified,
            "preal": _result_block(preal_result, preal_modified),
            "pint": _result_block(pint_result, pint_modified),
        }

    return _cmd


# Satelites de arrays de procesos (PReal y PInt dependen de otros).
_PROC_SATELLITES: dict[str, tuple[str, ...]] = {
    "preal": (),
    "pint": (),
    "alm": (),
}


def _result_block(
    result: Any,
    modified: bool,
) -> dict[str, Any]:
    """Empaqueta un ProcCommentResult (o None) en dict JSON-safe.

    Cada PReal/PInt puede ser None si su slot_map estaba vacio.
    """
    if result is None:
        return {
            "modified": False,
            "reused": {}, "inserted": {},
            "satellite_reused": {}, "satellite_inserted": {},
            "total_mlcs_in_res": 0,
        }
    return {
        "modified": modified,
        "reused": result.reused,
        "inserted": result.inserted,
        "satellite_reused": result.satellite_reused,
        "satellite_inserted": result.satellite_inserted,
        "total_mlcs_in_res": result.total_mlcs_in_res,
    }


# ---------------------------------------------------------------------------
# Adaptadores de registro
# ---------------------------------------------------------------------------
def _wrap_handler(handler):
    """Pasa los args del SyncTIAClient (args, tia_client) directamente al handler.

    El dispatcher del SyncTIAClient invoca con (args, tia_client). Los
    handlers internos del area (_cmd) ahora esperan la misma firma: el
    refactor (sept-2026) elimino la indireccion legacy de extraer
    ``portal`` y ``ts`` aqui -- el handler los toma directo de
    ``tia_client.wrapper`` cuando los necesita (project.start_transaction,
    user_constants, etc).
    """
    def _wrapped(args, tia_client):
        return handler(args, tia_client)
    return _wrapped


def register(registry):
    """Aporta los comandos al COMMAND_REGISTRY legacy (Fase 3).

    Compat con worker_tia.py. Tras el rename a tia_loop.py, este
    punto de extension queda solo para tests que importan worker_tia.
    """
    for hw in EXTRA_HW_TYPES:
        registry[f"update_disp_comments_db_{hw}"] = (
            make_cmd_update_disp_comments_db(hw)
        )
    for kind in EXTRA_PROC_KINDS:
        registry[f"update_proc_comments_db_{kind}"] = (
            make_cmd_update_proc_comments_db(kind)
        )
    registry["update_proc_comments_db_param"] = (
        make_cmd_update_proc_comments_db_param()
    )
    registry["commit_disp_nmax_renames_online"] = (
        make_cmd_commit_disp_nmax_renames_online()
    )
    registry["commit_disp_devices_offline"] = (
        make_cmd_commit_disp_devices_offline()
    )
    registry["commit_devices_sync"] = make_cmd_commit_devices_sync()


def register_main(tia_client) -> None:
    """Aporta los comandos del area al SyncTIAClient.

    Punto de extension estandar. main_supervisor llama register_main()
    por cada area declarada en AreaSpec.contributes_tia_commands.
    """
    for hw in EXTRA_HW_TYPES:
        tia_client.register_command(
            f"update_disp_comments_db_{hw}",
            _wrap_handler(make_cmd_update_disp_comments_db(hw)),
        )
    for kind in EXTRA_PROC_KINDS:
        tia_client.register_command(
            f"update_proc_comments_db_{kind}",
            _wrap_handler(make_cmd_update_proc_comments_db(kind)),
        )
    tia_client.register_command(
        "update_proc_comments_db_param",
        _wrap_handler(make_cmd_update_proc_comments_db_param()),
    )
    tia_client.register_command(
        "commit_disp_nmax_renames_online",
        _wrap_handler(make_cmd_commit_disp_nmax_renames_online()),
    )
    tia_client.register_command(
        "commit_disp_devices_offline",
        _wrap_handler(make_cmd_commit_disp_devices_offline()),
    )
    tia_client.register_command(
        "commit_devices_sync",
        _wrap_handler(make_cmd_commit_devices_sync()),
    )


__all__ = [
    "EXTRA_HW_TYPES",
    "EXTRA_PROC_KINDS",
    "make_cmd_update_disp_comments_db",
    "make_cmd_update_proc_comments_db",
    "make_cmd_update_proc_comments_db_param",
    "make_cmd_commit_devices_sync",
    "register",
    "register_main",
]
