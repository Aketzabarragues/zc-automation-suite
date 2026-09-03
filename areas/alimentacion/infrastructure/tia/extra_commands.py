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


def make_cmd_commit_devices_sync() -> Callable[..., Any]:
    """Handler del op compuesto ``commit_devices_sync``.

    Reusa los handlers atómicos del core del worker
    (``update_user_constant_value``, ``update_user_constant_name``) y
    los métodos nativos de PlcTagTable (``table.export``,
    ``target_plc.import_plc_tags``) bajo una ÚNICA transacción.

    **Importante**: este op NO abre su propia ``start_transaction``.
    Se ejecuta DENTRO de la transacción que abrió el batch wrapper
    (``_cmd_execute_transactional_batch`` en ``worker_tia``). El
    wrapper es el responsable del ``start_transaction`` y del
    ``end_transaction(rollback=False/True)``. Si este op abriera su
    propia transacción, TIA Portal V21 rechazaría con
    ``OpennessAccessException: Multiple instances of ExclusiveAccess
    is not supported`` (bug detectado en 2026-08-28 durante validación
    en PLC real).

    El edit XML offline (paso 3c) corre dentro del worker usando
    ``TagTableModifier`` (Python puro, no importa
    ``siemens_tia_scripting``). Moverlo aquí respeta ``.clinerules`` §1
    (el worker sigue siendo el único proceso que importa la DLL).

    Si el op propaga una excepción, el batch wrapper hace
    ``end_transaction(rollback=True)`` y revierte N_MAX + renames +
    devices ya aplicados. Los XMLs editados en ``work_dir`` quedan en
    disco (write-only, no se pueden rollbackear desde TIA) y se
    sobrescriben en el siguiente run.

    Args del op:
      - ``plc_name`` (str, requerido).
      - ``undo_text`` (str, opcional).
      - ``work_dir`` (str, requerido): directorio donde el worker
        escribe los XML exportados/modificados.
      - ``nmax_ops`` (list[dict]): ops online, cada dict con
        ``{table_name, constant_name, new_value}``.
      - ``rename_ops`` (list[dict]): ops online, cada dict con
        ``{table_name, current_name, new_name}``.
      - ``device_changes`` (list[dict]): ops offline, cada dict con
        ``{table_name, tia_folder, adds, removes}``.

    Específico del flujo "sync dispositivos" del subdominio alimentación:
    NO genérico (la semántica de N_MAX como PlcUserConstant de la
    tabla 000_Config_Dispositivos y de los devices como PlcUserConstant
    de las 6 tablas 2000_Disp_<hw> es convención de este área).
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
        from pathlib import Path
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

        # Import local: solo se carga cuando el handler se invoca
        # (cumple "offline-first" del worker, igual que los
        # handlers de disp). Apunta al nuevo paquete SD.
        from areas.alimentacion.infrastructure.sd.proc_comment_updater import (
            ProcCommentUpdater,
        )
        from areas.alimentacion.infrastructure.sd.mlc_registry import MLCRegistry

        s7dcl_path = os.path.join(work_dir, f"{db_name}.s7dcl")
        s7res_path = os.path.join(work_dir, f"{db_name}.s7res")

        # Import lazy del worker para evitar el ciclo
        # ``worker_tia → command_loader → AreaRegistry → areas.<area>
        # → extra_commands → (lazy) worker_tia``.
        from core.infrastructure.tia import worker_tia
        core_registry = worker_tia.COMMAND_REGISTRY

        # 1. EXPORT SELECTIVO (reusa ``export_block`` del core).
        core_registry["export_block"](portal, ts, {
            "plc_name":   plc_name,
            "block_name": db_name,
            "target_dir": work_dir,
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
        #    historial Undo.
        if updater.was_modified():
            core_registry["import_block"](portal, ts, {
                "plc_name":      plc_name,
                "import_dir":    work_dir,
                "target_folder": target_folder,
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


def register(registry: dict[str, Callable[..., Any]]) -> None:
    """Aporta los comandos del área alimentación al ``COMMAND_REGISTRY``.

    Comandos registrados:
      - ``update_disp_comments_db_<hw>`` (×6): SD source comments
        offline + import por hw_type.
      - ``commit_devices_sync``: op compuesto N_MAX + renames + devices
        en una sola ``start_transaction``.
      - ``update_proc_comments_db_<kind>`` (×3: preal, pint, alm):
        SD source comments offline + import por array de proceso,
        con propagación a satélites del mismo slot.

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
    registry["commit_devices_sync"] = make_cmd_commit_devices_sync()


__all__ = [
    "EXTRA_HW_TYPES",
    "EXTRA_PROC_KINDS",
    "make_cmd_update_disp_comments_db",
    "make_cmd_update_proc_comments_db",
    "make_cmd_commit_devices_sync",
    "register",
]
