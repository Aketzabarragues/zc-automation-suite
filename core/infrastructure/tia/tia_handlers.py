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
def _h_compile_plc(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Compila el software del PLC y retorna el booleano nativo de Siemens.

    Returns:
        ``{"had_errors": bool}``:
          - True  -> compilacion TIENE errores.
          - False -> compilacion NO tiene errores (exito).
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
    had_errors = bool(target_plc.compile_software())
    return {"had_errors": had_errors}


def _h_compile_blocks(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Compila una lista explicita de bloques del PLC (no todo el software).

    Mas rapido que compile_plc cuando solo se han tocado unos DBs
    concretos. Por bloque:
      - is_consistent()=True  -> se SALTA.
      - is_consistent()=False -> se COMPILA.
      - bloque no encontrado  -> se SALTA (no falla el handler entero).

    Returns:
        ``{
            "compiled":         [{"name", "had_errors", "was_inconsistent"}],
            "skipped_unchanged": [name, ...],
            "not_found":        [name, ...],
            "errors":           [{"name", "error"}],
        }``
    """
    plc_name: str = args.get("plc_name", "")
    block_names = args.get("block_names")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not block_names:
        raise ValueError(
            "Se requiere 'block_names' (lista no vacia de bloques a compilar). "
            "Si quieres compilar todo el PLC, usa el comando 'compile_plc'."
        )

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    # Indexar bloques del PLC por nombre para busqueda O(1).
    all_blocks = target_plc.get_program_blocks()
    by_name: dict = {}
    for b in all_blocks:
        name = _safe_get_block_name(b)
        if name is not None:
            by_name.setdefault(name, b)  # primero que aparece gana

    compiled: list[dict] = []
    skipped_unchanged: list[str] = []
    not_found: list[str] = []
    errors: list[dict] = []

    for name in block_names:
        block = by_name.get(name)
        if block is None:
            not_found.append(name)
            continue
        # is_consistent(): True si ya esta compilado y sin cambios.
        try:
            is_consistent = bool(block.is_consistent())
        except Exception:
            # Defensivo: si lanza (raro), asumimos NO consistente y compilamos.
            is_consistent = False
        if is_consistent:
            skipped_unchanged.append(name)
            continue
        # .compile() retorna True si hay errores (semantica Siemens §2.2.11).
        try:
            had_errors = bool(block.compile())
            compiled.append({
                "name": name,
                "had_errors": had_errors,
                "was_inconsistent": True,
            })
        except Exception as exc:
            errors.append({
                "name": name,
                "error": f"{type(exc).__name__}: {exc}",
            })

    return {
        "compiled": compiled,
        "skipped_unchanged": skipped_unchanged,
        "not_found": not_found,
        "errors": errors,
        # Campos top-level para que ``_summarize_result`` (en
        # ``tia_helpers.py``) los incluya en el log del decorador
        # ``@log_ot_command``. Asi el operario ve en la consola web
        # ``n_compiled_ok=5, n_compiled_err=2, n_skipped=10, ...`` sin
        # tener que abrir el dict completo.
        "n_compiled_ok": sum(
            1 for c in compiled if not c["had_errors"]
        ),
        "n_compiled_err": sum(
            1 for c in compiled if c["had_errors"]
        ) + len(errors),
        "n_skipped": len(skipped_unchanged),
        "n_not_found": len(not_found),
        "n_errors": len(errors),
    }


# ---------------------------------------------------------------------------
# Handlers de export
# ---------------------------------------------------------------------------
def _h_export_blocks_sd(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta los bloques de programa del PLC como .s7dcl."""
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)
    return _export_objects_sd(target_plc, target_path, "program_blocks")


def _h_export_udts_sd(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta los User Data Types del PLC como .s7dcl."""
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)
    return _export_objects_sd(target_plc, target_path, "user_data_types")


def _h_export_plc_tags_xml(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta las tablas de variables del PLC como XML SimaticML."""
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    target_table_names = args.get("table_names")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    tag_tables = target_plc.get_plc_tag_tables()
    count = 0
    for table in tag_tables:
        if target_table_names is not None:
            name = _safe_get_table_name(table)
            if name not in target_table_names:
                continue
        table.export(
            target_directory_path=str(target_path),
            keep_folder_structure=True,
        )
        count += 1

    return {"exported_to": str(target_path), "count": count}


def _h_export_block(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta un bloque de programa como SimaticSD (manual §2.10.5)."""
    plc_name: str = args.get("plc_name", "")
    block_name: str = args.get("block_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not block_name:
        raise ValueError("Se requiere el argumento 'block_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    blocks = target_plc.get_program_blocks()
    for block in blocks:
        name = _safe_get_block_name(block)
        if name == block_name:
            block.export(
                target_directory_path=str(target_path),
                export_format="SimaticSD",
                keep_folder_structure=False,
            )
            return {"exported_to": str(target_path), "block_name": block_name}

    raise RuntimeError(
        f"Bloque '{block_name}' no encontrado en PLC '{plc_name}'."
    )


def _h_export_tag_table(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta una PlcTagTable como XML SimaticML."""
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not table_name:
        raise ValueError("Se requiere el argumento 'table_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    tag_tables = target_plc.get_plc_tag_tables()
    for table in tag_tables:
        name = _safe_get_table_name(table)
        if name == table_name:
            table.export(
                target_directory_path=str(target_path),
                keep_folder_structure=False,
            )
            return {"exported_to": str(target_path), "table_name": table_name}

    raise RuntimeError(
        f"Tabla '{table_name}' no encontrada en PLC '{plc_name}'."
    )


# ---------------------------------------------------------------------------
# Handlers de import
# ---------------------------------------------------------------------------
def _h_import_blocks_sd(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa bloques .s7dcl desde el disco al PLC (manual §2.2.23).

    CUIDADO: ``import_blocks`` tiene la firma
    ``import_blocks(import_root_directory: str, target_folder_path: Optional[str] = None)``
    (default = ``None``, NO string vacio). Pasar ``target_folder_path=""``
    (string vacio) hace que TIA V21 NO haga match UPDATE de bloques
    pre-existentes (replica el árbol de carpetas del PLC dentro del
    ``import_root_directory``); en su lugar intenta CREATE y falla con
    "Import failed because an object with the name X already exists".
    Validado en VM: el mismo directorio que importa OK con script
    standalone (``plc.import_blocks(import_root_directory=...)`` sin
    pasar ``target_folder_path``) falla cuando el handler pasa
    ``""``. Solucion: si el caller no pasa un ``target_folder`` no
    vacio, NO pasamos el argumento y dejamos que TIA use su default
    (``None`` = escanea recursivo, hace match UPDATE por nombre de
    bloque preservando la ruta relativa).

    Reproducido del bug en sept-2026: el handler original hacia
    ``args.get("target_folder") or ""`` y siempre pasaba el argumento
    a TIA, lo que rompia el ``Crear proceso desde plantilla`` (el FB
    ``proc_process_crear_aplicar`` de alimentacion que llama a este
    handler con ``target_folder`` omitido sufria el mismo problema
    que ``import_block`` (singular) antes de su fix en el docstring
    de arriba). Replicamos el patron de ``_h_import_block`` para
    arreglarlo.
    """
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder_raw = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(
            f"El directorio de importacion no existe o no es accesible: "
            f"'{import_dir}'."
        )

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    if target_folder_raw:
        target_plc.import_blocks(
            import_root_directory=import_dir,
            target_folder_path=target_folder_raw,
        )
    else:
        target_plc.import_blocks(import_root_directory=import_dir)
    return {"imported_from": import_dir}


def _h_import_plc_tags_xml(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa PlcTagTables en formato XML al PLC (manual §2.2.24).

    Misma regla que ``_h_import_blocks_sd`` sobre
    ``target_folder_path``: si el caller no lo pasa, NO se envia a
    TIA (default = ``None``, escaneo recursivo con match UPDATE por
    nombre preservando el subpath). Pasar ``""`` rompe el match
    UPDATE en V21. Patron identico al fix aplicado a
    ``_h_import_block`` y ``_h_import_blocks_sd``.
    """
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder_raw = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(
            f"El directorio de importacion no existe o no es accesible: "
            f"'{import_dir}'."
        )

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    if target_folder_raw:
        target_plc.import_plc_tags(
            import_root_directory=import_dir,
            target_folder_path=target_folder_raw,
        )
    else:
        target_plc.import_plc_tags(import_root_directory=import_dir)
    return {"imported_from": import_dir}


def _h_import_tag_table(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa una PlcTagTable (XML) desde disco al PLC (manual §2.2.24)."""
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder: str = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(f"El directorio no existe: '{import_dir}'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_plc.import_plc_tags(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return {"imported_from": import_dir}


def _h_import_block(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa un bloque (.s7dcl) desde disco al PLC (manual §2.2.23).

    CUIDADO: ``import_blocks`` tiene la firma
    ``import_blocks(import_root_directory: str, target_folder_path: Optional[str] = None)``
    (default = ``None``, NO string vacio). Pasar ``target_folder_path=""``
    (string vacio) hace que TIA V21 NO haga match UPDATE de bloques
    pre-existentes (replica el árbol de carpetas del PLC dentro del
    ``import_root_directory``); en su lugar intenta CREATE y falla con
    "Import failed because an object with the name X already exists".
    Validado en VM: el mismo directorio que importa OK con script
    standalone (``plc.import_blocks(import_root_directory=...)`` sin
    pasar ``target_folder_path``) falla cuando el handler pasa
    ``""``. Solucion: si el caller no pasa un ``target_folder`` no
    vacio, NO pasamos el argumento y dejamos que TIA use su default
    (``None`` = escanea recursivo, hace match UPDATE por nombre de
    bloque preservando la ruta relativa).
    """
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder_raw = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(f"El directorio no existe: '{import_dir}'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    if target_folder_raw:
        target_plc.import_blocks(
            import_root_directory=import_dir,
            target_folder_path=target_folder_raw,
        )
    else:
        target_plc.import_blocks(import_root_directory=import_dir)
    return {"imported_from": import_dir}


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
