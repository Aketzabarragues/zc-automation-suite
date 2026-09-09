"""Comandos del worker OT específicos del área alimentación.

Viven AQUÍ (no en ``core.infrastructure.tia.worker_tia``) para que el
motor OT permanezca genérico y no sepa qué es "alimentación". La
transacción atómica sigue funcionando porque estos handlers corren
DENTRO del proceso del worker, bajo el mismo
``start_transaction`` / ``end_transaction`` que cualquier otro
comando del lote.

Comandos aportados al ``COMMAND_REGISTRY`` del worker:
  - ``update_disp_comments_db_<hw>`` (×6, uno por hw_type): export +
    edit SD offline + import selectivo de los DBs de array.
  - ``commit_devices_sync``: commit atómico N_MAX + renames + devices
    en una sola ``start_transaction`` del worker. Específico del flujo
    "sync dispositivos" del subdominio alimentación (N_MAX como
    PlcUserConstant de la tabla 000_Config_Dispositivos + devices como
    PlcUserConstant de las 6 tablas 2000_Disp_<hw>).

Punto de extensión cableado por ``AreaSpec.contributes_tia_commands``
y consumido al arrancar el worker vía
``core.infrastructure.tia.command_loader.load_extra_commands``.

Restricción arquitectónica (``.clinerules`` §1): este módulo NO
importa ``siemens_tia_scripting``. Solo aporta ``Callable`` con firma
``(portal, ts, args) -> dict`` que el worker invocará dentro de su
proceso. Los imports locales de ``DispCommentUpdater`` y
``TagTableModifier`` ocurren dentro de los handlers para preservar el
comportamiento offline-first del worker (la pieza offline se carga
solo cuando el handler se ejecuta, no al import del módulo).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from core.infrastructure.tia.export_paths import SdPair


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

    Args (de ``args``):
        plc_name: nombre del PLC en TIA.
        db_name: nombre del DB objetivo.
        db_array_name: nombre del array dentro del DB.
        slot_map: ``{slot: texto}``.
        work_dir: directorio de TRABAJO donde TIA escribe el export,
                  el updater modifica in-place, y desde donde TIA
                  importa. Por convención de 9 carpetas
                  (``_plan/16_carpetas_convencion.md``), es
                  ``modified_bloques/<db_subpath>`` (raíz de la fase
                  post-commit).
        target_folder: carpeta TIA donde está el DB (estática para
                       dispositivos, viene de ``config.json``).
        exports_subdir: directorio del SNAPSHOT LIMPIO pre-commit
                       (opcional, Commit 7). Si se pasa, TIA
                       exporta aquí primero, luego
                       ``shutil.copytree`` copia el snapshot a
                       ``work_dir``, y el updater modifica la
                       copia. Si NO se pasa (legacy), TIA
                       exporta directo a ``work_dir`` y el updater
                       modifica in-place. Con ``exports_subdir``
                       se consigue que ``git diff exports/bloques/
                       modified/bloques/`` muestre los cambios del
                       updater (audit pre vs post).
    """
    def _cmd(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        db_name: str = args.get("db_name", "")
        db_array_name: str = args.get("db_array_name", "")
        slot_map: dict[str, str] = args.get("slot_map", {})
        work_dir: str = args.get("work_dir", "")
        target_folder: str = args.get("target_folder", "")
        # ``exports_subdir`` (Commit 7): ver rationale en el docstring.
        # Si se pasa, el export va al snapshot limpio (``exports/bloques``)
        # y luego se copia a ``work_dir`` (= ``modified_bloques``). Si
        # NO se pasa (legacy), el export va directo a ``work_dir`` y el
        # updater modifica in-place (asimétrico con proc; ver
        # ``_plan/16_carpetas_convencion.md`` §8 sobre la decisión de
        # Commit 7).
        exports_subdir: str = args.get("exports_subdir", "") or ""

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

        s7dcl_path = SdPair(Path(work_dir), db_name).dcl
        s7res_path = SdPair(Path(work_dir), db_name).res

        # Import lazy del worker para evitar el ciclo
        # ``worker_tia → command_loader → AreaRegistry → areas.<area> →
        # extra_commands → (lazy) worker_tia``. En el momento en que se
        # invoca el handler, ``worker_tia`` ya está completamente cargado.
        from core.infrastructure.tia import worker_tia
        core_registry = worker_tia.COMMAND_REGISTRY

        # 1. EXPORT SELECTIVO (reusa ``export_block`` del core).
        #    Patrón nuevo (Commit 7, si ``exports_subdir`` se pasa):
        #      - Export al snapshot limpio (``exports/bloques``) +
        #        ``shutil.copytree`` a ``work_dir`` (= ``modified_bloques``).
        #        El updater modifica la copia, dejando el snapshot
        #        limpio en ``exports/bloques/`` intacto.
        #      - Consecuencia: ``git diff exports/bloques/ modified/bloques/``
        #        muestra los cambios del updater.
        #    Patrón legacy (``exports_subdir=""``):
        #      - Export directo a ``work_dir`` y updater modifica
        #        in-place. (Asimétrico con proc; pre-Commit 7.)
        if exports_subdir:
            export_target_dir = exports_subdir
            core_registry["export_block"](portal, ts, {
                "plc_name":   plc_name,
                "block_name": db_name,
                "target_dir": export_target_dir,
            })
            # El export escribe ``.s7dcl``/``.s7res`` en
            # ``export_target_dir`` (TIA respeta la ruta tal cual).
            # Copiamos el contenido a ``work_dir`` para que el updater
            # opere sobre la copia, no sobre el snapshot limpio.
            if Path(export_target_dir).exists():
                shutil.copytree(
                    export_target_dir, work_dir,
                    dirs_exist_ok=True,
                )
            else:
                # El export no produjo archivos (¿db_name mal?). El
                # updater fallará al no encontrar ``.s7dcl``/``.s7res``;
                # dejamos que lance el error natural en lugar de
                # enmascararlo con un fallback.
                Path(work_dir).mkdir(parents=True, exist_ok=True)
        else:
            # Legacy: export directo a ``work_dir``.
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


def make_cmd_commit_disp_nmax_renames_online() -> Callable[..., Any]:
    """Handler que aplica N_MAX + renames en una tx TIA propia (online puro).

    A diferencia del antiguo ``commit_devices_sync`` (que mezclaba online
    con offline en la misma tx y provocaba rollback silencioso en TIA V21),
    este handler **abre y cierra su propia** ``start_transaction`` /
    ``end_transaction`` y SOLO hace cambios online:

      * ``update_user_constant_value`` por cada N_MAX.
      * ``update_user_constant_name`` por cada rename.

    Los cambios offline (devices) van en otro handler separado
    (``make_cmd_commit_disp_devices_offline``) que corre en OTRA tx
    TIA, llamada secuencialmente desde IT. Esto evita el bug V21 del
    "primer commit no aplica, segundo sí" causado por la mezcla
    online+offline en una misma tx.

    Si una op falla, hace ``end_transaction(rollback=True)`` y re-lanza
    la excepción. Ver ``.clinerules`` §2.2 sobre el state machine
    del worker.
    """
    def _cmd(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        undo_text: str = args.get("undo_text", "Sync N_MAX + renames (online)")
        nmax_ops: list[dict[str, Any]] = args.get("nmax_ops") or []
        rename_ops: list[dict[str, Any]] = args.get("rename_ops") or []

        if not plc_name:
            raise ValueError("commit_disp_nmax_renames_online: plc_name requerido.")

        # Imports locales: ciclo worker_tia → extra_commands → (lazy) worker_tia.
        from core.infrastructure.tia import worker_tia
        from core.infrastructure.tia.worker_tia import (
            _cmd_update_user_constant_value,
            _cmd_update_user_constant_name,
        )

        project = worker_tia._get_active_project(portal)
        # Valida que el PLC existe (lanza si no).
        worker_tia._find_plc(project, plc_name)

        results_list: list[dict[str, Any]] = []
        step_idx = 0

        def _record(op_name: str, result: Any) -> None:
            nonlocal step_idx
            step_idx += 1
            results_list.append(
                {"step": step_idx, "command": op_name, "result": result}
            )

        # Tx TIA PROPIA (no del batch wrapper). Online puro.
        project.start_transaction(undo_text=undo_text, dialog_text=undo_text)
        op_label = "start_transaction"
        try:
            for nmax_op in nmax_ops:
                op_label = (
                    f"update_user_constant_value("
                    f"{nmax_op.get('constant_name')})"
                )
                r = _cmd_update_user_constant_value(
                    portal, ts, {
                        "plc_name": plc_name,
                        "table_name": nmax_op["table_name"],
                        "constant_name": nmax_op["constant_name"],
                        "new_value": nmax_op["new_value"],
                    }
                )
                _record("update_user_constant_value", r)

            for rename_op in rename_ops:
                op_label = (
                    f"update_user_constant_name("
                    f"{rename_op.get('table_name')}:"
                    f"{rename_op.get('current_name')}->"
                    f"{rename_op.get('new_name')})"
                )
                r = _cmd_update_user_constant_name(
                    portal, ts, {
                        "plc_name": plc_name,
                        "table_name": rename_op["table_name"],
                        "current_name": rename_op["current_name"],
                        "new_name": rename_op["new_name"],
                    }
                )
                _record("update_user_constant_name", r)

            # Confirmar (manual §2.37.28). Sin rollback.
            project.end_transaction(rollback=False)
        except Exception as e:
            # Rollback atómico: deshace cualquier set_property parcial.
            try:
                project.end_transaction(rollback=True)
            except Exception:
                pass
            raise RuntimeError(
                f"commit_disp_nmax_renames_online abortado en "
                f"'{op_label}'. Rollback ejecutado. Motivo: {e}"
            ) from e

        return {
            "success": True,
            "operations_executed": step_idx,
            "details": results_list,
        }

    return _cmd


def make_cmd_commit_disp_devices_offline() -> Callable[..., Any]:
    """Handler que aplica device changes (import) en una tx TIA propia
    (offline puro).

    A diferencia del antiguo ``commit_devices_sync`` (que mezclaba online
    con offline en la misma tx y provocaba rollback silencioso en TIA V21),
    este handler **abre y cierra su propia** ``start_transaction`` /
    ``end_transaction`` y SOLO hace cambios offline:

      * Por cada ``device_change``: ``import_plc_tags`` desde
        ``work_dir`` (los XMLs ya están editados por IT en el
        Stage 7 ``copy_and_edit`` de ``ejecutar_transaccion``).

    NO hace ``table.export`` (sept-2026 fix del race condition): ese
    paso lo hace IT en el Stage 6 ``export_post_tx_a`` (después de
    Tx A y con sleep de consolidación), leyendo los datos
    post-renames de TIA. Hacerlo aquí leería los datos stale (sin
    renames consolidados) y los re-importaría, haciendo rollback
    silencioso de los renames aplicados en Tx A.

    Los cambios online (N_MAX + renames) van en otro handler
    (``make_cmd_commit_disp_nmax_renames_online``) que corre en OTRA
    tx TIA, llamada secuencialmente desde IT.

    Si una op falla, hace ``end_transaction(rollback=True)`` y re-lanza
    la excepción. Los XML editados en ``work_dir`` se sobrescriben
    en el siguiente run (idempotente).
    """
    def _cmd(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        undo_text: str = args.get("undo_text", "Sync devices (offline)")
        work_dir: str = args.get("work_dir", "")
        device_changes: list[dict[str, Any]] = args.get("device_changes") or []

        if not plc_name:
            raise ValueError("commit_disp_devices_offline: plc_name requerido.")
        if not work_dir:
            raise ValueError("commit_disp_devices_offline: work_dir requerido.")

        # Imports locales.
        # Nota: ``TagTableModifier`` ya NO se importa aquí — la
        # edición offline la hace IT en el Stage 7 ``copy_and_edit``
        # de ``ejecutar_transaccion``. Este handler solo importa XMLs
        # ya editados.
        from core.infrastructure.tia import worker_tia
        from core.infrastructure.tia.worker_tia import _safe_get_table_name

        project = worker_tia._get_active_project(portal)
        target_plc = worker_tia._find_plc(project, plc_name)
        work_path = Path(work_dir)
        work_path.mkdir(parents=True, exist_ok=True)

        results_list: list[dict[str, Any]] = []
        step_idx = 0

        def _record(op_name: str, result: Any) -> None:
            nonlocal step_idx
            step_idx += 1
            results_list.append(
                {"step": step_idx, "command": op_name, "result": result}
            )

        # Tx TIA PROPIA. Offline puro.
        project.start_transaction(undo_text=undo_text, dialog_text=undo_text)
        op_label = "start_transaction"
        try:
            for dev_change in device_changes:
                table_name: str = dev_change["table_name"]
                tia_folder: str = dev_change.get("tia_folder", "")
                adds: list[dict[str, str]] = dev_change.get("adds") or []
                removes: set[str] = set(dev_change.get("removes") or [])

                # 3a. Buscar la tabla.
                tables = target_plc.get_plc_tag_tables()
                table = next(
                    (
                        t for t in tables
                        if _safe_get_table_name(t) == table_name
                    ),
                    None,
                )
                if table is None:
                    raise RuntimeError(
                        f"Tabla '{table_name}' no encontrada en PLC "
                        f"'{plc_name}'."
                    )

                # 3b. ANTES: ``table.export(...)`` — REDUNDANTE, causa
                #     rollback de renames. ELIMINADO en sept-2026: el
                #     export ahora se hace en Stage 6
                #     (``export_post_tx_a``), después de Tx A y con
                #     sleep de consolidación. El XML exportado está
                #     en ``modified/variables/<tia_folder>/<table_name>.xml``
                #     antes de que se invoque este handler (lo edita
                #     IT en Stage 7 ``copy_and_edit``).

                # 3c. Validar que el XML está presente. La edición
                #     offline la hace IT en el Stage 7 ``copy_and_edit``
                #     de ``ejecutar_transaccion``: este handler solo
                #     importa lo que ya está en ``work_path``.
                xml_path = work_path / tia_folder / f"{table_name}.xml"
                if not xml_path.is_file():
                    matches = list(work_path.rglob(f"{table_name}.xml"))
                    if not matches:
                        raise RuntimeError(
                            f"XML de '{table_name}' no encontrado en "
                            f"work_dir '{work_path}'. ¿Stage 7 "
                            f"``copy_and_edit`` corrió antes de "
                            f"invocar este handler?"
                        )
                    xml_path = matches[0]

                # 3d. Import selectivo. Pasamos ``target_folder_path=""``
                #     para que TIA reconcilie por NOMBRE (commit 3e2babd).
                op_label = f"import_plc_tags_xml({table_name})"
                target_plc.import_plc_tags(
                    import_root_directory=str(work_path),
                    target_folder_path="",
                )
                _record(
                    f"import_plc_tags_xml[{table_name}]",
                    True,
                )

            project.end_transaction(rollback=False)
        except Exception as e:
            try:
                project.end_transaction(rollback=True)
            except Exception:
                pass
            raise RuntimeError(
                f"commit_disp_devices_offline abortado en '{op_label}'. "
                f"Rollback ejecutado. Motivo: {e}"
            ) from e

        return {
            "success": True,
            "operations_executed": step_idx,
            "details": results_list,
        }

    return _cmd


def make_cmd_commit_devices_sync() -> Callable[..., Any]:
    """DEPRECATED: usar ``commit_disp_nmax_renames_online`` +
    ``commit_disp_devices_offline`` en su lugar.

    Esta factory se mantiene por compat con callers/tests legacy, pero
    YA NO es la vía recomendada. Mezcla online (N_MAX+renames) y
    offline (devices) en la misma ``start_transaction``, lo que en TIA
    V21 produce un rollback silencioso de los cambios online (ver
    análisis del LLM externo, sept-2026).

    El bug "primer commit no aplica, segundo sí" desaparece al
    partir el flujo en 2 transacciones secuenciales online→offline.
    Se retira en PR siguiente tras confirmar el fix en prod.
    """
    def _cmd(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        undo_text: str = args.get(
            "undo_text", "Sync dispositivos (N_MAX + devices)"
        )
        work_dir: str = args.get("work_dir", "")
        nmax_ops: list[dict[str, Any]] = args.get("nmax_ops") or []
        rename_ops: list[dict[str, Any]] = args.get("rename_ops") or []
        device_changes: list[dict[str, Any]] = args.get("device_changes") or []

        if not plc_name:
            raise ValueError("Se requiere el argumento 'plc_name'.")
        if not work_dir:
            raise ValueError("Se requiere el argumento 'work_dir'.")
        # Las 3 fases (N_MAX, renames, devices) son siempre activas. Si
        # una lista llega vacia, eso es "no hay cambios en esta fase" y
        # el bucle simplemente no se ejecuta. El op sigue bajo UNA sola
        # transaccion del wrapper del batch.

        # Import lazy del core del worker (sigue el mismo patrón que
        # los otros handlers de este módulo: evita el ciclo
        # ``worker_tia → command_loader → areas.<area> → extra_commands
        # → (lazy) worker_tia``).
        from core.infrastructure.tia import worker_tia
        from core.infrastructure.tia.worker_tia import (
            _cmd_update_user_constant_value,
            _cmd_update_user_constant_name,
            _safe_get_table_name,
        )
        from areas.alimentacion.infrastructure.xml.disp_tag_table_modifier import TagTableModifier

        project = worker_tia._get_active_project(portal)
        target_plc = worker_tia._find_plc(project, plc_name)
        # Asegurar que work_dir existe (defensivo: el caller ya
        # deberia haberlo creado, pero si no, lo creamos).
        work_path = Path(work_dir)
        work_path.mkdir(parents=True, exist_ok=True)

        # Acumulador de resultados: cada paso anade su retorno nativo
        # para inspeccion posterior.
        results_list: list[dict[str, Any]] = []
        step_idx = 0
        op_label = ""

        def _record(op_name: str, result: Any) -> None:
            nonlocal step_idx
            step_idx += 1
            results_list.append(
                {"step": step_idx, "command": op_name, "result": result}
            )

        # NOTA ARQUITECTONICA IMPORTANTE:
        # Este op NO abre su propia ``start_transaction``. Se ejecuta
        # DENTRO de la transaccion que abrio el batch wrapper
        # (``_cmd_execute_transactional_batch`` en el worker). El
        # wrapper es el responsable de:
        #   1. ``project.start_transaction`` al inicio del lote.
        #   2. ``project.end_transaction(rollback=False/True)`` al final.
        # Si abrieramos OTRA transaccion aqui, TIA Portal V21
        # rechazaria con ``OpennessAccessException: Multiple
        # instances of ExclusiveAccess is not supported`` (bug
        # detectado en 2026-08-28). El rollback completo de toda la
        # cadena (N_MAX + renames + devices) lo gestiona el wrapper.
        try:
            # 1. N_MAX online (dentro de la tx del wrapper).
            for nmax_op in nmax_ops:
                op_label = (
                    f"update_user_constant_value("
                    f"{nmax_op.get('constant_name')})"
                )
                r = _cmd_update_user_constant_value(
                    portal, ts, {
                        "plc_name": plc_name,
                        "table_name": nmax_op["table_name"],
                        "constant_name": nmax_op["constant_name"],
                        "new_value": nmax_op["new_value"],
                    }
                )
                _record("update_user_constant_value", r)

            # 2. Renames online.
            for rename_op in rename_ops:
                op_label = (
                    f"update_user_constant_name("
                    f"{rename_op.get('table_name')}:"
                    f"{rename_op.get('current_name')}->"
                    f"{rename_op.get('new_name')})"
                )
                r = _cmd_update_user_constant_name(
                    portal, ts, {
                        "plc_name": plc_name,
                        "table_name": rename_op["table_name"],
                        "current_name": rename_op["current_name"],
                        "new_name": rename_op["new_name"],
                    }
                )
                _record("update_user_constant_name", r)

            # 3. Devices: export + edit + import por cada tabla.
            for dev_change in device_changes:
                table_name: str = dev_change["table_name"]
                tia_folder: str = dev_change.get("tia_folder", "")
                adds: list[dict[str, str]] = dev_change.get("adds") or []
                removes: set[str] = set(dev_change.get("removes") or [])

                # 3a. Buscar la tabla.
                tables = target_plc.get_plc_tag_tables()
                table = next(
                    (
                        t for t in tables
                        if _safe_get_table_name(t) == table_name
                    ),
                    None,
                )
                if table is None:
                    raise RuntimeError(
                        f"Tabla '{table_name}' no encontrada en PLC '{plc_name}'."
                    )

                # 3b. Export selectivo (incluye la estructura de carpetas TIA).
                op_label = f"export_plc_tags_xml({table_name})"
                table.export(
                    target_directory_path=str(work_path),
                    keep_folder_structure=True,
                )
                _record(
                    f"export_plc_tags_xml[{table_name}]",
                    str(work_path),
                )

                # 3c. Edit XML offline (dentro del worker). El export
                # escribio ``work_dir/<tia_folder>/<table_name>.xml``;
                # modificamos in-place.
                xml_path = work_path / tia_folder / f"{table_name}.xml"
                if not xml_path.is_file():
                    # Fallback: buscar el XML en cualquier subdirectorio
                    # de ``work_dir`` (defensivo, por si la estructura
                    # de carpetas varia entre versiones de TIA).
                    matches = list(work_path.rglob(f"{table_name}.xml"))
                    if not matches:
                        raise RuntimeError(
                            f"XML de '{table_name}' no encontrado tras export "
                            f"en '{work_path}'."
                        )
                    xml_path = matches[0]

                op_label = f"edit_xml({table_name})"
                modifier = TagTableModifier(xml_path)
                added_count = modifier.add_user_constants_by_table(
                    table_name, adds
                )
                removed_count = modifier.remove_user_constants(removes)
                # CRITICO: regenerar el ID de la PlcTagTable raiz. TIA
                # exporta con ID="0" (placeholder), y al re-importar
                # V21 intenta CREAR en vez de actualizar, fallando con
                # "Cannot create... already exists". Asignamos un ID
                # unico alto (max+0x10000) para forzar la ruta de UPDATE.
                new_table_id = modifier.regenerate_root_table_id()
                if modifier.was_modified():
                    modifier.save(xml_path)
                _record(
                    f"edit_xml[{table_name}]",
                    {
                        "added": added_count,
                        "removed": removed_count,
                        "modified": modifier.was_modified(),
                        "new_table_id": new_table_id,
                    },
                )

                # 3d. Import selectivo.
                #
                # En V21, pasar ``target_folder_path=tia_folder`` con
                # ``ID="0"`` en la PlcTagTable hace que TIA intente CREAR
                # (no actualizar) la tabla. Soluciones aplicadas:
                #  1. ``regenerate_root_table_id`` cambia el ID="0" a uno
                #     unico alto (ver 3c).
                #  2. Pasamos ``target_folder_path=""`` (en vez del nombre
                #     de carpeta) para que TIA reconcilie POR NOMBRE
                #     en lugar de por ruta. Es la estrategia del legacy
                #     (``import_plc_tags_xml`` original) que en V20/V21
                #     funciona mejor que pasar la carpeta explícita.
                op_label = f"import_plc_tags_xml({table_name})"
                target_plc.import_plc_tags(
                    import_root_directory=str(work_path),
                    target_folder_path="",
                )
                _record(
                    f"import_plc_tags_xml[{table_name}]",
                    True,
                )

            return {
                "success": True,
                "operations_executed": step_idx,
                "details": results_list,
            }

        except Exception as e:
            # No llamamos a ``end_transaction`` aqui: lo gestiona el
            # batch wrapper. Solo propagamos la excepcion anadida con
            # info del paso que fallo para que el log sea diagnostico.
            import json as _json
            try:
                args_str = _json.dumps(
                    {"op": op_label,
                     "device_change": device_changes[-1] if device_changes else None},
                    ensure_ascii=False, default=str
                )[:500]
            except Exception:
                args_str = repr(op_label)[:500]
            raise RuntimeError(
                f"commit_devices_sync abortado en el paso {step_idx + 1} "
                f"('{op_label}'). Excepcion propagada al batch wrapper "
                f"(que hara rollback del lote). Motivo: {e}. "
                f"Contexto: {args_str}"
            ) from e

    return _cmd


# ── Comandos de procesos (sync comentarios por slot) ──────────────────
#
# Tipos de array soportados en los DBs PARAM/ALM de procesos.
# Mantener en sync con la convención de los .s7dcl exportados por
# TIA y con los nombres hardcoded en el builder de slot_maps
# (``areas/alimentacion/application/proc_slot_map_builder.py``).
EXTRA_PROC_KINDS: tuple[str, ...] = (
    "preal",
    "pint",
    "alm",
)

# Mapeo de satélites por kind (mismo número de slots que el array
# principal, mismo MLC-distinto-mismo-texto).
# - preal → PReal[] con 2 satélites (Bool Vis y Real ValorAnterior
#           dentro de Aux).
# - pint  → PInt[] con 2 satélites (Int Vis y Int ValorAnterior
#           dentro de Aux).
# - alm   → ALM[] sin satélites (array principal único en DB_ALM).
_PROC_SATELLITES: dict[str, frozenset[str]] = {
    "preal": frozenset({"PReal_Vis", "Aux.PReal_ValorAnterior"}),
    "pint":  frozenset({"PInt_Vis",  "Aux.PInt_ValorAnterior"}),
    "alm":   frozenset(),
}


def make_cmd_update_proc_comments_db(kind: str) -> Callable[..., Any]:
    """Factory que genera un handler atómico para el array ``kind`` de proceso.

    El ``kind`` se queda capturado en el closure para etiquetar el
    retorno y poder trazarlo en logs / historial de TIA.

    El handler:
      1. Exporta selectivamente el DB objetivo (``export_block``).
      2. Aplica el updater offline ``ProcCommentUpdater`` sobre
         los ``.s7dcl`` / ``.s7res`` exportados, con propagación a
         satélites del mismo slot.
      3. Si hubo cambios, re-importa el bloque al proyecto
         (``import_block``).

    Vive dentro de la transacción que abrió
    ``execute_transactional_batch`` en el lote (no abre transacción
    propia); es atómico respecto al lote.
    """
    if kind not in _PROC_SATELLITES:
        raise ValueError(
            f"make_cmd_update_proc_comments_db: kind '{kind}' no soportado. "
            f"Esperado uno de {list(_PROC_SATELLITES)}."
        )
    satellites = _PROC_SATELLITES[kind]

    def _cmd(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        db_name: str = args.get("db_name", "")
        array_name: str = args.get("array_name", "")
        slot_map: dict[str, str] = args.get("slot_map", {})
        work_dir: str = args.get("work_dir", "")
        target_folder: str = args.get("target_folder", "")
        # ``db_subpath`` es la subcarpeta TIA del DB (e.g.
        # ``"ZC_Plantillas\\50010_ProcesoEstandar\\53010_Parametros"``).
        # TIA Portal V21 requiere reimportar en la MISMA ruta donde
        # ya existe el bloque; si no, falla con "object with the
        # name already exists" (validado 2026-09-07). Si la cache
        # no tiene la ruta (``""``), el worker escribe a la raíz
        # de ``exports/`` (legacy).
        db_subpath: str = args.get("db_subpath", "")
        # ``exports_subdir`` (Commit 5): si se pasa, el handler
        # exporta al snapshot limpio (``exports_subdir/<db_subpath>``)
        # y luego ``shutil.copytree`` lo copia a ``work_dir/<db_subpath>``
        # (que será ``modified_bloques``). Si NO se pasa (legacy,
        # backward compat con Commit 4 y tests anteriores), el export
        # va directamente a ``work_dir/<db_subpath>`` y el updater
        # modifica in-place. Default ``""`` = comportamiento legacy.
        exports_subdir: str = args.get("exports_subdir", "") or ""

        if not (
            plc_name and db_name and array_name and work_dir and target_folder
        ):
            raise ValueError(
                f"update_proc_comments_db_{kind}: args incompletos. "
                f"Recibido: plc_name={plc_name!r} db_name={db_name!r} "
                f"array_name={array_name!r} work_dir={work_dir!r} "
                f"target_folder={target_folder!r}"
            )

        # Coerción: slot_map llega con keys str (JSON); el updater quiere int.
        slot_map_int: dict[int, str] = {
            int(k): v for k, v in slot_map.items() if int(k) >= 1
        }

        # Subcarpeta efectiva: si el BloqueCache tenía la ruta del
        # bloque (``db_subpath``), el archivo va a
        # ``<work_dir>/<db_subpath>/<db_name>.s7dcl`` (mismo path
        # que TIA tiene internamente, así el reimport reconcilia
        # por nombre y hace UPDATE). Si no, cae a la raíz legacy.
        effective_work_dir = (
            str(Path(work_dir) / db_subpath) if db_subpath else work_dir
        )

        # Import local: solo se carga cuando el handler se invoca
        # (cumple "offline-first" del worker, igual que los
        # handlers de disp). Apunta al nuevo paquete SD.
        from areas.alimentacion.infrastructure.sd.proc_comment_updater import (
            ProcCommentUpdater,
        )
        from areas.alimentacion.infrastructure.sd.mlc_registry import MLCRegistry

        s7dcl_path = SdPair(Path(effective_work_dir), db_name).dcl
        s7res_path = SdPair(Path(effective_work_dir), db_name).res

        # Import lazy del worker para evitar el ciclo
        # ``worker_tia → command_loader → AreaRegistry → areas.<area>
        # → extra_commands → (lazy) worker_tia``.
        from core.infrastructure.tia import worker_tia
        core_registry = worker_tia.COMMAND_REGISTRY

        # 1. EXPORT SELECTIVO (reusa ``export_block`` del core).
        #    Patrón nuevo (Commit 5, si se pasa ``exports_subdir``):
        #      - TIA escribe ``.s7dcl``/``.s7res`` al snapshot limpio
        #        en ``<exports_subdir>/<db_subpath>/`` (auditable).
        #      - ``shutil.copytree`` copia el snapshot a
        #        ``<work_dir>/<db_subpath>/`` (= ``modified_bloques``)
        #        para que el updater modifique la copia, dejando el
        #        snapshot intacto.
        #    Patrón legacy (backward compat, ``exports_subdir=""``):
        #      - TIA escribe directo a ``<work_dir>/<db_subpath>/``
        #        y el updater modifica in-place. Mismo comportamiento
        #        que Commit 4 (disp) y que los tests anteriores.
        if exports_subdir:
            export_target_dir = (
                str(Path(exports_subdir) / db_subpath)
                if db_subpath else exports_subdir
            )
            core_registry["export_block"](portal, ts, {
                "plc_name":   plc_name,
                "block_name": db_name,
                "target_dir": export_target_dir,
            })
            # Copia el snapshot limpio a ``effective_work_dir``
            # (``work_dir/<db_subpath>``). TIA ya creó el directorio
            # durante el export; ``copytree`` lo replica en el destino
            # (que se crea si no existe). ``dirs_exist_ok=True``
            # permite re-ejecuciones defensivas.
            if Path(export_target_dir).exists():
                shutil.copytree(
                    export_target_dir, effective_work_dir,
                    dirs_exist_ok=True,
                )
            else:
                # Caso defensivo: TIA no exportó nada. Creamos el
                # directorio vacío para que el updater no lance
                # ``FileNotFoundError`` al instanciarse.
                Path(effective_work_dir).mkdir(
                    parents=True, exist_ok=True,
                )
        else:
            # Legacy: export directo a ``effective_work_dir``.
            core_registry["export_block"](portal, ts, {
                "plc_name":   plc_name,
                "block_name": db_name,
                "target_dir": effective_work_dir,
            })

        # 2. Updater offline (con propagación a satélites).
        updater = ProcCommentUpdater(
            s7dcl_path=s7dcl_path,
            s7res_path=s7res_path,
            slot_map=slot_map_int,
            array_name=array_name,
            satellite_arrays=set(satellites),
            registry=MLCRegistry(),
        )
        result = updater.update()
        updater.save()

        # 3. IMPORT SELECTIVO (reusa ``import_block`` del core) — solo
        #    si el updater modificó algo, para no ensuciar el
        #    historial Undo. Pasamos ``work_dir`` (raíz) y TIA
        #    escanea recursivamente: si el archivo está en
        #    ``<work_dir>/<db_subpath>/<db_name>.s7dcl``, TIA
        #    encuentra el bloque en su ubicación correcta y hace
        #    UPDATE (no CREATE).
        #
        #    CRÍTICO: ``target_folder`` se pasa VACÍO (no el
        #    ``get_tia_folder_proceso()`` que viene del use case) para
        #    que TIA reconcilie por NOMBRE en lugar de por ruta. Si
        #    pasáramos ``target_folder="003_Procesos"``, TIA intentaría
        #    CREAR el bloque en ese folder, pero como el bloque ya
        #    existe en otra ubicación (``ZC_Plantillas/.../...``), falla
        #    con "object with the name already exists". Mismo patrón
        #    que ``commit_devices_sync`` (legacy ``import_plc_tags_xml``).
        if updater.was_modified():
            core_registry["import_block"](portal, ts, {
                "plc_name":      plc_name,
                "import_dir":    work_dir,
                "target_folder": "",  # reconcilia por nombre (ver rationale arriba)
            })

        return {
            "kind":      kind,
            "db_name":   db_name,
            "array_name": array_name,
            "modified":  updater.was_modified(),
            "proc_comment_result": {
                "reused":              result.reused,
                "inserted":            result.inserted,
                "satellite_reused":    result.satellite_reused,
                "satellite_inserted":  result.satellite_inserted,
                "total_mlcs_in_res":   result.total_mlcs_in_res,
            },
        }

    return _cmd


def make_cmd_update_proc_comments_db_param() -> Callable[..., Any]:
    """Handler combinado para los 2 arrays del DB PARAM (PReal + PInt).

    El bug del que partimos: cuando se enviaban 2 ops separadas
    (``_preal`` y ``_pint``) sobre el mismo DB, la segunda op
    SOBREESCRIBÍA el ``.s7dcl`` / ``.s7res`` en ``exports/`` con un
    export fresco de TIA (que aún no tenía el cambio de PReal si TIA
    rechazó ese MLC concreto). El resultado: PReal se quedaba sin
    actualizar aunque el updater SÍ lo escribía en disco.

    Solución: 1 solo ``export_block`` al inicio, 2 llamadas al
    ``ProcCommentUpdater`` (PReal, luego PInt) sobre el MISMO archivo
    exportado, 1 solo ``save()`` implícito por updater, y 1 solo
    ``import_block`` al final (si alguno modificó). El ALM sigue
    saliendo como op separada porque usa un DB distinto.

    Args:
        args: ``{
            "plc_name": str,
            "db_name": str (DB PARAM),
            "preal_slot_map": dict[str, str] (slot 1-based → texto),
            "pint_slot_map":  dict[str, str] (slot 1-based → texto),
            "work_dir": str (root de modified_bloques si se pasa
                              exports_subdir; en otro caso root
                              del snapshot directo),
            "exports_subdir": str (opcional, Commit 5). Si se pasa,
                              TIA exporta al snapshot limpio aquí
                              (``exports_bloques``) y luego
                              ``shutil.copytree`` lo copia a
                              ``work_dir/<db_subpath>``. Si se omite,
                              el export va directo a ``work_dir``
                              (legacy / backward compat con Commit 4).
            "target_folder": str,
        }``
    """
    def _cmd(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
        plc_name: str = args.get("plc_name", "")
        db_name: str = args.get("db_name", "")
        preal_slot_map_raw: dict[str, str] = args.get("preal_slot_map", {}) or {}
        pint_slot_map_raw: dict[str, str] = args.get("pint_slot_map", {}) or {}
        work_dir: str = args.get("work_dir", "")
        target_folder: str = args.get("target_folder", "")
        # ``db_subpath`` es la subcarpeta TIA del DB PARAM. Ver
        # rationale en el handler ``_alm``.
        db_subpath: str = args.get("db_subpath", "")
        # ``exports_subdir`` (Commit 5): ver rationale completo en el
        # factory ``make_cmd_update_proc_comments_db``. Si se pasa, el
        # export va al snapshot limpio (``exports_bloques``) y luego
        # se copia a ``work_dir`` (= ``modified_bloques``). Si NO se
        # pasa (legacy), el export va directo a ``work_dir`` y el
        # updater modifica in-place.
        exports_subdir: str = args.get("exports_subdir", "") or ""

        if not (plc_name and db_name and work_dir and target_folder):
            raise ValueError(
                f"update_proc_comments_db_param: args incompletos. "
                f"Recibido: plc_name={plc_name!r} db_name={db_name!r} "
                f"work_dir={work_dir!r} target_folder={target_folder!r}"
            )

        # Coerción: los slot_map llegan con keys str (JSON); el updater
        # quiere int. Filtro slot 0 (defensivo, no aplica a procesos).
        preal_slot_map: dict[int, str] = {
            int(k): v for k, v in preal_slot_map_raw.items() if int(k) >= 1
        }
        pint_slot_map: dict[int, str] = {
            int(k): v for k, v in pint_slot_map_raw.items() if int(k) >= 1
        }

        # Subcarpeta efectiva: ver rationale en el handler ``_alm``.
        effective_work_dir = (
            str(Path(work_dir) / db_subpath) if db_subpath else work_dir
        )

        # Import local (offline-first; mismo patrón que los otros handlers).
        from areas.alimentacion.infrastructure.sd.proc_comment_updater import (
            ProcCommentUpdater,
        )
        from areas.alimentacion.infrastructure.sd.mlc_registry import MLCRegistry

        s7dcl_path = SdPair(Path(effective_work_dir), db_name).dcl
        s7res_path = SdPair(Path(effective_work_dir), db_name).res

        # Import lazy del worker.
        from core.infrastructure.tia import worker_tia
        core_registry = worker_tia.COMMAND_REGISTRY

        # 1. UN SOLO export_block sobre el DB PARAM. Patrón nuevo
        #    (Commit 5, si ``exports_subdir`` se pasa):
        #      - Export al snapshot limpio (``exports_bloques``) +
        #        ``shutil.copytree`` a ``modified_bloques``.
        #    Patrón legacy (backward compat, ``exports_subdir=""``):
        #      - Export directo a ``modified_bloques`` (lo que
        #        Commit 4 dejó para disp; también funciona aquí).
        if exports_subdir:
            export_target_dir = (
                str(Path(exports_subdir) / db_subpath)
                if db_subpath else exports_subdir
            )
            core_registry["export_block"](portal, ts, {
                "plc_name":   plc_name,
                "block_name": db_name,
                "target_dir": export_target_dir,
            })
            if Path(export_target_dir).exists():
                shutil.copytree(
                    export_target_dir, effective_work_dir,
                    dirs_exist_ok=True,
                )
            else:
                Path(effective_work_dir).mkdir(
                    parents=True, exist_ok=True,
                )
        else:
            # Legacy: export directo a ``effective_work_dir``.
            core_registry["export_block"](portal, ts, {
                "plc_name":   plc_name,
                "block_name": db_name,
                "target_dir": effective_work_dir,
            })

        # 2. updater PReal (con sus satélites).
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

        # 3. updater PInt (con sus satélites) — opera sobre el MISMO
        #    archivo ya modificado por PReal. Como ``MLCRegistry`` se
        #    re-extrae del .s7res en cada nueva instancia, ve los
        #    MLCs nuevos/actualizados del paso anterior.
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

        # 4. UN SOLO import_block (si alguno de los dos modificó algo).
        #    Ver rationale del ``target_folder=""`` en el handler ``_alm``.
        any_modified = preal_modified or pint_modified
        if any_modified:
            core_registry["import_block"](portal, ts, {
                "plc_name":      plc_name,
                "import_dir":    work_dir,
                "target_folder": "",  # reconcilia por nombre
            })

        return {
            "kind":      "param",
            "db_name":   db_name,
            "modified":  any_modified,
            "preal": _result_block(preal_result, preal_modified),
            "pint":  _result_block(pint_result,  pint_modified),
        }

    return _cmd


def _result_block(
    result: "ProcCommentResult | None",
    modified: bool,
) -> dict[str, Any]:
    """Empaqueta un ``ProcCommentResult`` (o ``None``) en un dict JSON-safe.

    Usado por ``make_cmd_update_proc_comments_db_param`` para componer
    el payload de retorno: cada uno de PReal/PInt puede estar ``None``
    si su slot_map estaba vacío (cero cambios que aplicar).
    """
    if result is None:
        return {
            "modified": False,
            "reused": {}, "inserted": {},
            "satellite_reused": {}, "satellite_inserted": {},
            "total_mlcs_in_res": 0,
        }
    return {
        "modified":            modified,
        "reused":              result.reused,
        "inserted":            result.inserted,
        "satellite_reused":    result.satellite_reused,
        "satellite_inserted":  result.satellite_inserted,
        "total_mlcs_in_res":   result.total_mlcs_in_res,
    }


def register(registry: dict[str, Callable[..., Any]]) -> None:
    """Aporta los comandos del área alimentación al ``COMMAND_REGISTRY``.

    Comandos registrados:
      - ``update_disp_comments_db_<hw>`` (×6): SD source comments
        offline + import por hw_type.
      - ``commit_disp_nmax_renames_online``: handler online puro
        (N_MAX + renames) con su propia ``start_transaction`` /
        ``end_transaction``. Sept-2026: sustituye al antiguo
        ``commit_devices_sync`` para evitar el rollback silencioso de
        TIA V21 al mezclar online + offline en la misma tx.
      - ``commit_disp_devices_offline``: handler offline puro
        (export + edit + import por tabla) con su propia tx.
        Se llama secuencialmente desde IT tras el handler online.
      - ``commit_devices_sync``: DEPRECATED. Se mantiene por compat
        con tests/callers legacy; se retira en PR siguiente.
      - ``update_proc_comments_db_<kind>`` (×3: preal, pint, alm):
        SD source comments offline + import por array de proceso,
        con propagación a satélites del mismo slot.
      - ``update_proc_comments_db_param``: handler combinado que aplica
        PReal y PInt sobre el MISMO DB PARAM en un solo export/import.
        Evita el bug del doble ``export_block`` que SOBREESCRIBÍA el
        cambio de PReal al exportar PInt.

    Muta ``registry`` in-place. Es seguro llamarla varias veces (los
    handlers se machacan por nombre, no se duplican).
    """
    for hw in EXTRA_HW_TYPES:
        registry[f"update_disp_comments_db_{hw}"] = (
            make_cmd_update_disp_comments_db(hw)
        )
    for kind in EXTRA_PROC_KINDS:
        registry[f"update_proc_comments_db_{kind}"] = (
            make_cmd_update_proc_comments_db(kind)
        )
    # Handler combinado para los 2 arrays del DB PARAM (PReal + PInt).
    # Evita el doble ``export_block`` sobre el mismo DB que SOBREESCRIBÍA
    # el cambio de PReal al exportar PInt (bug fixed 2026-09-07).
    registry["update_proc_comments_db_param"] = (
        make_cmd_update_proc_comments_db_param()
    )
    # Sept-2026: 2 handlers nuevos que reemplazan al antiguo
    # ``commit_devices_sync``. Cada uno abre/cierra su propia tx TIA
    # para evitar el rollback silencioso de V21 al mezclar online +
    # offline en la misma tx.
    registry["commit_disp_nmax_renames_online"] = (
        make_cmd_commit_disp_nmax_renames_online()
    )
    registry["commit_disp_devices_offline"] = (
        make_cmd_commit_disp_devices_offline()
    )
    # DEPRECATED: se mantiene por compat con callers/tests legacy.
    # Se retira en PR siguiente tras confirmar el fix en prod.
    registry["commit_devices_sync"] = make_cmd_commit_devices_sync()


__all__ = [
    "EXTRA_HW_TYPES",
    "EXTRA_PROC_KINDS",
    "make_cmd_update_disp_comments_db",
    "make_cmd_update_proc_comments_db",
    "make_cmd_update_proc_comments_db_param",
    "make_cmd_commit_devices_sync",
    "register",
]
