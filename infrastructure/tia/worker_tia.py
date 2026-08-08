"""Motor OT efímero para interacción con TIA Portal Openness.

Este script es ejecutado exclusivamente como un subproceso aislado por TIAProcessGateway.
NACE -> CONECTA (COM) -> EJECUTA COMANDO -> EMITE JSON A STDOUT -> DESCONECTA -> MUERE.

Reglas estricta de I/O:
- STDIN:  Recibe un JSON con 'command' (str) y 'args' (dict).
- STDOUT: Emite UNICAMENTE una línea JSON final con {'ok': True, 'result': ...} o {'ok': False, 'error': ...}.
- STDERR: Reorientación de logs, trazas de excepción y advertencias C++/CLR.

Inyección de dependencias:
  Los handlers del COMMAND_REGISTRY reciben (portal, args). Cada handler que
  necesite un proyecto abierto debe extraerlo con _get_active_project(portal),
  que valida su existencia y centraliza el control de errores. Esto permite
  comandos de ciclo de vida (open_project) que NO requieren proyecto previo.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, NoReturn


def _write_json_and_exit(payload: dict[str, Any], code: int) -> NoReturn:
    """Escribe la respuesta estructurada en stdout y finaliza el proceso."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    sys.exit(code)


def _get_active_project(portal: Any) -> Any:
    """Extrae y valida el proyecto activo del portal.

    Centraliza la lógica de extracción y validación del proyecto. Antes vivía
    en main(); ahora cada handler que necesita proyecto lo invoca, lo que
    permite comandos de ciclo de vida (open_project) que NO requieren
    proyecto previo y produce errores semánticos limpios en los demás.
    """
    project = portal.get_project()
    if not project:
        raise RuntimeError(
            "No hay ningún proyecto abierto en TIA Portal. "
            "Ejecuta 'open_project' primero."
        )
    return project


def _find_plc(project: Any, plc_name: str) -> Any:
    """Resuelve el objeto Plc por nombre dentro del proyecto activo.

    Helper centralizado para evitar duplicación en los handlers del dispatcher.
    Levanta RuntimeError si no existe.
    """
    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    for plc in project.get_plcs():
        if plc.get_name() == plc_name:
            return plc

    raise RuntimeError(
        f"No se encontró ningún PLC con el nombre '{plc_name}' en el proyecto activo."
    )


def _ensure_target_dir(target_dir: str) -> Path:
    """Valida que target_dir esté presente y devuelve la ruta resuelta."""
    if not target_dir:
        raise ValueError("Se requiere el argumento 'target_dir'.")
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)
    return target_path


# ──────────────────────────────────────────────────────────────────────────
# Handlers del dispatcher. Todos reciben (portal: Any, args: dict[str, Any]).
# Cada handler que necesite proyecto abierto invoca _get_active_project().
# ──────────────────────────────────────────────────────────────────────────

def _cmd_open_project(portal: Any, ts: Any, args: dict[str, Any]) -> None:
    """Abre un proyecto TIA Portal desde una ruta absoluta. Manual §2.4.3."""
    _ = ts
    project_file_path: str = args.get("project_file_path", "")
    if not project_file_path:
        raise ValueError("Se requiere el argumento 'project_file_path'.")
    if not os.path.isfile(project_file_path):
        raise RuntimeError(f"El archivo de proyecto no existe: '{project_file_path}'.")
    portal.open_project(project_file_path=project_file_path)


def _cmd_save_project(portal: Any, ts: Any, args: dict[str, Any]) -> None:
    """Guarda los cambios pendientes del proyecto activo (manual §2.37.2)."""
    _ = ts
    project = _get_active_project(portal)
    project.save()


def _cmd_close_project(portal: Any, ts: Any, args: dict[str, Any]) -> None:
    """Cierra el proyecto activo (manual §2.37.3).

    ADVERTENCIA CRÍTICA: project.close() destruye permanentemente todos
    los cambios no guardados del proyecto. El caller es responsable de
    haber invocado save() antes si la persistencia era necesaria.
    """
    _ = ts
    project = _get_active_project(portal)
    project.close()


def _cmd_list_plcs(portal: Any, ts: Any, args: dict[str, Any]) -> list[str]:
    """Lista los nombres de los PLCs del proyecto activo."""
    _ = ts
    project = _get_active_project(portal)
    plcs = project.get_plcs()
    return [plc.get_name() for plc in plcs]


def _cmd_list_blocks(portal: Any, ts: Any, args: dict[str, Any]) -> list[str]:
    """Lista los nombres de los bloques de programa de un PLC específico."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    # Coerción defensiva (TIA Portal V21): aunque el manual define folder_path
    # como Optional[str], el wrapper .NET rechaza valores None. Forzamos "" para
    # que el binding del CLR acepte el parámetro y delegue al comportamiento
    # nativo de "raíz del PLC".
    folder_path: str = args.get("folder_path") or ""

    target_plc = _find_plc(project, plc_name)
    blocks = target_plc.get_program_blocks(folder_path=folder_path)
    return [block.get_name() for block in blocks]


def _cmd_compile_plc(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Compila el software del PLC y retorna el booleano nativo de Siemens.

    Semántica documentada (API V1.2.1, sección 2.2.11):
      - True  -> La compilación TIENE errores.
      - False -> La compilación NO tiene errores (éxito).
    La capa de presentación (MCP) traduce este valor a un mensaje humano.
    """
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    target_plc = _find_plc(project, plc_name)
    return bool(target_plc.compile_software())


def _export_objects_scl(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta una colección de objetos TIA (Bloques o UDTs) a archivos .scl.

    Espera en args: plc_name, target_dir, collection_key
    ('program_blocks' | 'user_data_types'). `ts` se inyecta desde
    `_load_siemens_wrapper()` para acceder a los enumeradores nativos
    (ts.Enums.ExportFormats.SimaticSD, etc.).
    """
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    collection_key: str = args.get("collection_key", "program_blocks")

    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    if collection_key == "program_blocks":
        objects = target_plc.get_program_blocks()
    elif collection_key == "user_data_types":
        objects = target_plc.get_user_data_types()
    else:
        raise ValueError(
            f"collection_key desconocido: '{collection_key}'. "
            "Use 'program_blocks' o 'user_data_types'."
        )

    for obj in objects:
        # El wrapper nativo de Siemens soporta coerción desde strings hacia
        # sus enumeradores internos (TypeError previo: "export_format must
        # be an Enum or string"). Inyectamos el literal "SimaticSD" para
        # forzar la exportación en formato fuente (.scl) sin depender del
        # espacio de nombres ts.Enums.ExportFormats (no expuesto en este
        # build). Manual V1.2.1, secciones 2.10.5 y 2.15.5.
        obj.export(
            target_directory_path=str(target_path),
            export_format="SimaticSD",
            keep_folder_structure=True,
        )

    return str(target_path)


def _cmd_export_blocks_scl(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta los bloques de programa del PLC como archivos fuente SimaticSD."""
    args = {**args, "collection_key": "program_blocks"}
    return _export_objects_scl(portal, ts, args)


def _cmd_export_udts_scl(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta los User Data Types (UDTs) del PLC como archivos fuente SimaticSD."""
    args = {**args, "collection_key": "user_data_types"}
    return _export_objects_scl(portal, ts, args)


def _cmd_export_plc_tags_xml(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta las tablas de variables del PLC como XML SimaticML.

    Itera sobre plc.get_plc_tag_tables() (manual §2.2.8) y exporta cada
    tabla con export_format=SimaticML, export_options=WithDefaults y
    keep_folder_structure=True (preserva jerarquía de grupos del PLC).
    """
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")

    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    tag_tables = target_plc.get_plc_tag_tables()
    for table in tag_tables:
        # Mitigación defensiva: el wrapper nativo no expone ni
        # ExportFormats ni ExportOptions en este build. Según la
        # documentación oficial (manual V1.2.1, secciones 2.10.5 y 2.15.5),
        # ambos parámetros son opcionales; al omitirlos, el wrapper C++
        # subyacente aplica los defaults internos (SimaticML para el
        # formato, None para las opciones).
        table.export(
            target_directory_path=str(target_path),
            keep_folder_structure=True,
        )

    return str(target_path)


def _cmd_import_blocks_scl(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Importa bloques de programa (.scl) desde el disco al PLC (manual §2.2.23).

    TIA Portal asume que el directorio existe; si no, el CLR lanza una
    excepción grave. Por eso validamos con os.path.isdir() ANTES de invocar
    el método COM.
    """
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    # Coerción defensiva (TIA Portal V21): el wrapper .NET no acepta None para
    # target_folder_path aunque el manual lo declare Optional[str]. Forzamos "".
    target_folder: str = args.get("target_folder") or ""

    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")

    if not os.path.isdir(import_dir):
        raise RuntimeError(
            f"El directorio de importación no existe o no es accesible: '{import_dir}'."
        )

    target_plc = _find_plc(project, plc_name)
    target_plc.import_blocks(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return True


def _cmd_import_plc_tags_xml(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Importa tablas de variables (PLC tags) en formato XML al PLC (manual §2.2.24).

    Validación previa con os.path.isdir() para evitar la excepción grave
    del CLR cuando el directorio no existe.
    """
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    # Coerción defensiva (TIA Portal V21): el wrapper .NET no acepta None para
    # target_folder_path aunque el manual lo declare Optional[str]. Forzamos "".
    target_folder: str = args.get("target_folder") or ""

    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")

    if not os.path.isdir(import_dir):
        raise RuntimeError(
            f"El directorio de importación no existe o no es accesible: '{import_dir}'."
        )

    target_plc = _find_plc(project, plc_name)
    target_plc.import_plc_tags(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return True


def _cmd_export_block(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta un único bloque de programa como SimaticSD (.scl). Manual §2.10.5."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    block_name: str = args.get("block_name", "")
    target_dir: str = args.get("target_dir", "")
    if not block_name:
        raise ValueError("Se requiere el argumento 'block_name'.")
    target_path = _ensure_target_dir(target_dir)
    target_plc = _find_plc(project, plc_name)
    blocks = target_plc.get_program_blocks()
    for block in blocks:
        if block.get_name() == block_name:
            block.export(
                target_directory_path=str(target_path),
                export_format="SimaticSD",
                keep_folder_structure=False,
            )
            return str(target_path)
    raise RuntimeError(f"Bloque '{block_name}' no encontrado en PLC '{plc_name}'.")


def _cmd_import_block(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Importa un único bloque (.scl) desde disco al PLC. Manual §2.2.23."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    # Coerción defensiva (TIA Portal V21): el wrapper .NET no acepta None para
    # target_folder_path aunque el manual lo declare Optional[str]. Forzamos "".
    target_folder: str = args.get("target_folder") or ""
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(f"El directorio no existe: '{import_dir}'.")
    target_plc = _find_plc(project, plc_name)
    target_plc.import_blocks(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return True


def _cmd_export_tag_table(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta una única PlcTagTable como XML SimaticML. Manual §2.10.5 / §2.28.3."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    target_dir: str = args.get("target_dir", "")
    if not table_name:
        raise ValueError("Se requiere el argumento 'table_name'.")
    target_path = _ensure_target_dir(target_dir)
    target_plc = _find_plc(project, plc_name)
    tables = target_plc.get_plc_tag_tables()
    for table in tables:
        if table.get_name() == table_name:
            table.export(
                target_directory_path=str(target_path),
                keep_folder_structure=False,
            )
            return str(target_path)
    raise RuntimeError(f"Tabla '{table_name}' no encontrada en PLC '{plc_name}'.")


def _cmd_import_tag_table(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Importa una única PlcTagTable (XML) desde disco al PLC. Manual §2.2.24."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    # Coerción defensiva (TIA Portal V21): el wrapper .NET no acepta None para
    # target_folder_path aunque el manual lo declare Optional[str]. Forzamos "".
    target_folder: str = args.get("target_folder") or ""
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(f"El directorio no existe: '{import_dir}'.")
    target_plc = _find_plc(project, plc_name)
    target_plc.import_plc_tags(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return True


def _cmd_get_user_constants(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, str]:
    """Devuelve {value: name} de las PlcUserConstant de una tabla. Manual §2.28.5."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    if not table_name:
        raise ValueError("Se requiere el argumento 'table_name'.")
    target_plc = _find_plc(project, plc_name)
    tables = target_plc.get_plc_tag_tables()
    table = next((t for t in tables if t.get_name() == table_name), None)
    if table is None:
        raise RuntimeError(f"Tabla '{table_name}' no encontrada en PLC '{plc_name}'.")
    result: dict[str, str] = {}
    for constant in table.get_user_constants():
        raw_value = constant.get_property(name="Value")
        try:
            int_value = int(str(raw_value).strip())
        except (TypeError, ValueError):
            continue
        name = constant.get_property(name="Name")
        result[str(int_value)] = str(name)
    return result


def _cmd_update_user_constant_value(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Actualiza el valor de una PlcUserConstant. Manual §2.28."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    constant_name: str = args.get("constant_name", "")
    new_value: int = args.get("new_value", 0)
    target_plc = _find_plc(project, plc_name)
    tables = target_plc.get_plc_tag_tables()
    table = next((t for t in tables if t.get_name() == table_name), None)
    if table is None:
        raise RuntimeError(f"Tabla '{table_name}' no encontrada.")
    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == constant_name:
            constant.set_property(name="Value", value=str(new_value))
            return True
    raise RuntimeError(f"Constante '{constant_name}' no encontrada en tabla '{table_name}'.")


def _cmd_update_user_constant_name(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Renombra una PlcUserConstant. Manual §2.28."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    current_name: str = args.get("current_name", "")
    new_name: str = args.get("new_name", "")
    target_plc = _find_plc(project, plc_name)
    tables = target_plc.get_plc_tag_tables()
    table = next((t for t in tables if t.get_name() == table_name), None)
    if table is None:
        raise RuntimeError(f"Tabla '{table_name}' no encontrada.")
    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == current_name:
            constant.set_property(name="Name", value=new_name)
            return True
    raise RuntimeError(f"Constante '{current_name}' no encontrada en tabla '{table_name}'.")


def _cmd_delete_user_constant(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Borra una PlcUserConstant. Manual §2.34.4. snake_case: constant.delete()."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    constant_name: str = args.get("constant_name", "")
    target_plc = _find_plc(project, plc_name)
    tables = target_plc.get_plc_tag_tables()
    table = next((t for t in tables if t.get_name() == table_name), None)
    if table is None:
        raise RuntimeError(f"Tabla '{table_name}' no encontrada.")
    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == constant_name:
            constant.delete()
            return True
    raise RuntimeError(f"Constante '{constant_name}' no encontrada en tabla '{table_name}'.")


# ──────────────────────────────────────────────────────────────────────────
# Lotes transaccionales: ejecutan N comandos atómicos bajo una ÚNICA
# transacción de TIA Portal. Si una operación falla, las anteriores se
# deshacen vía end_transaction(rollback=True). Esto garantiza atomicidad
# en el historial del proyecto (Undo) y previene estados intermedios
# inconsistentes.
# ──────────────────────────────────────────────────────────────────────────

# Comandos prohibidos dentro de un lote. Causarían:
#   - open/close_project: destruirían el portal activo a mitad del lote.
#   - save_project      : forzaría un commit parcial fuera de la transacción.
#   - list_plcs         : no es una operación, es introspección.
#   - execute_transactional_batch: anidamiento no soportado (podría
#     balancear transacciones de forma incorrecta sobre el RCW del project).
_TRANSACTION_FORBIDDEN_COMMANDS: frozenset[str] = frozenset(
    {
        "open_project",
        "close_project",
        "save_project",
        "list_plcs",
        "execute_transactional_batch",
    }
)


def _cmd_execute_transactional_batch(
    portal: Any, ts: Any, args: dict[str, Any]
) -> dict[str, Any]:
    """Ejecuta múltiples comandos atómicos bajo una única transacción de TIA Portal.

    Itera sobre el propio COMMAND_REGISTRY delegando en los handlers ya
    testados, aislando todo el lote dentro de project.start_transaction() /
    project.end_transaction(). Si cualquier handler levanta excepción, se
    invoca end_transaction(rollback=True) para revertir TODA la cadena
    y se propaga un RuntimeError con la operación que causó el aborto.

    Args:
        portal: Instancia del portal TIA (inyectada por el dispatcher).
        ts:     Módulo Siemens inyectado (no usado directamente aquí, pero
                requerido por la firma uniforme del COMMAND_REGISTRY).
        args:   Dict con:
                  - operations: list[dict] -> [{"command": str, "args": dict}, ...]
                  - undo_text:  str (opcional) -> texto del historial.

    Returns:
        {"success": True, "operations_executed": int}

    Raises:
        ValueError: Si la lista está vacía, contiene un comando desconocido
                    o un comando prohibido dentro de un lote.
        RuntimeError: Si una operación falla; el mensaje identifica el
                      índice y nombre del comando que rompió el lote.
    """
    _ = ts
    project = _get_active_project(portal)
    undo_text: str = args.get("undo_text", "Operación por Lote")
    operations: list[dict[str, Any]] = args.get("operations", [])

    if not operations:
        raise ValueError("La lista de operaciones está vacía.")

    project.start_transaction(undo_text=undo_text, dialog_text=undo_text)
    executed = 0
    cmd: str = ""
    try:
        for op in operations:
            cmd = op.get("command", "")
            cmd_args: dict[str, Any] = op.get("args", {})

            if cmd not in COMMAND_REGISTRY:
                raise ValueError(f"Comando desconocido en lote: '{cmd}'")
            if cmd in _TRANSACTION_FORBIDDEN_COMMANDS:
                raise ValueError(
                    f"El comando '{cmd}' está prohibido dentro de un lote "
                    "transaccional."
                )

            # Ejecutar el handler atómico reinyectando portal y ts.
            COMMAND_REGISTRY[cmd](portal, ts, cmd_args)
            executed += 1

        project.end_transaction(rollback=False)
        return {"success": True, "operations_executed": executed}

    except Exception as e:
        # Cualquier fallo (validación, COM, OS) aborta el lote y restaura
        # el estado previo del proyecto. Silenciamos fallos secundarios
        # del rollback para no enmascarar la causa raíz original.
        try:
            project.end_transaction(rollback=True)
        except Exception:
            pass
        raise RuntimeError(
            f"Lote abortado en la operación {executed + 1} ('{cmd}'). "
            f"Rollback ejecutado. Motivo: {e}"
        )


COMMAND_REGISTRY: dict[str, Callable[[Any, Any, dict[str, Any]], Any]] = {
    # ── Ciclo de vida del proyecto ────────────────────────────────────────
    "open_project": _cmd_open_project,
    "save_project": _cmd_save_project,
    "close_project": _cmd_close_project,
    # ── Inspección ──────────────────────────────────────────────────────
    "list_plcs": _cmd_list_plcs,
    "list_blocks": _cmd_list_blocks,
    # ── Mutación / compilación ──────────────────────────────────────────
    "compile_plc": _cmd_compile_plc,
    # ── Exportación masiva SimaticSD ─────────────────────────────────────
    "export_blocks_scl": _cmd_export_blocks_scl,
    "export_udts_scl": _cmd_export_udts_scl,
    # ── Exportación masiva SimaticML (XML) ───────────────────────────────
    "export_plc_tags_xml": _cmd_export_plc_tags_xml,
    # ── Importación masiva desde disco (cierre del ciclo I/O) ─────────────
    "import_blocks_scl": _cmd_import_blocks_scl,
    "import_plc_tags_xml": _cmd_import_plc_tags_xml,
    # ── Bloques granulares ──────────────────────────────────────────────
    "export_block": _cmd_export_block,
    "import_block": _cmd_import_block,
    # ── Tablas de variables granulares ──────────────────────────────────
    "export_tag_table": _cmd_export_tag_table,
    "import_tag_table": _cmd_import_tag_table,
    # ── Constantes de usuario (N_MAX, dimensionamiento) ─────────────────
    "get_user_constants": _cmd_get_user_constants,
    "update_user_constant_value": _cmd_update_user_constant_value,
    "update_user_constant_name": _cmd_update_user_constant_name,
    "delete_user_constant": _cmd_delete_user_constant,
    # ── Lotes transaccionales (rollback automático) ────────────────────
    "execute_transactional_batch": _cmd_execute_transactional_batch,
}


def _load_siemens_wrapper() -> Any:
    """Carga nativa del wrapper de Siemens vía inyección en sys.path.

    Mecanismo heredado del proyecto anterior, superior a importlib.util
    para binarios .pyd con dependencias CLR/Pythonnet: en lugar de fabricar
    un spec sintético, expone la ruta de _MEIPASS al loader nativo de
    Python (`_imp`) para que la DLL se cargue por el camino estándar,
    ejecutando correctamente su código de inicialización y registrando
    submódulos como `ts.Enums`.

    Modo producción (PyInstaller --onefile):
      - Inyecta sys._MEIPASS en sys.path (prioridad).
      - Añade la ruta a la variable de entorno PATH.
      - En Windows 3.8+, registra la ruta vía os.add_dll_directory para
        que las dependencias nativas sean localizables.

    Modo desarrollo:
      - El módulo ya está disponible vía el venv del usuario; se importa
        directamente con la lógica estándar.

    Retorna el módulo ya inicializado. Lanza ImportError si la DLL no
    se encuentra o falla su carga.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        # Inyección prioritaria para el loader nativo.
        if meipass not in sys.path:
            sys.path.insert(0, meipass)

        os.environ["PATH"] = meipass + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(meipass)

        import siemens_tia_scripting as ts
        return ts

    # Modo desarrollo: import estándar del venv.
    import siemens_tia_scripting as ts
    return ts


def main() -> None:
    # 1. Carga dinámica tardía del wrapper nativo (Sección 1.7.1 V1.2.1).
    try:
        ts = _load_siemens_wrapper()
    except (ImportError, FileNotFoundError) as e:
        _write_json_and_exit(
            {"ok": False, "error": f"Fallo al cargar 'siemens_tia_scripting': {e}"},
            code=1,
        )

    # 2. Silenciado absoluto de la consola nativa C++.
    ts.set_logging(path="worker_openness.log", console=False)

    # 3. Lectura del payload de entrada.
    try:
        raw_stdin = sys.stdin.read().strip()
        payload = json.loads(raw_stdin) if raw_stdin else {}
    except Exception as e:
        _write_json_and_exit(
            {"ok": False, "error": f"Payload STDIN inválido (JSON malformado): {e}"},
            code=1,
        )

    command = payload.get("command")
    args = payload.get("args", {})

    if not command or command not in COMMAND_REGISTRY:
        _write_json_and_exit(
            {"ok": False, "error": f"Comando no reconocido o ausente: '{command}'"},
            code=1,
        )

    portal = None
    try:
        # 4. Enganche al portal. Usamos AnyUserInterface para que el filtro
        #    de instancias COM acepte tanto TIA Portal con GUI activa como
        #    instancias headless (manual V1.2.1 §2.4.2). De este modo el
        #    proceso aislado puede reengancharse a la sesión ya abierta
        #    por el usuario sin colisionar con su estado.
        portal = ts.attach_portal(
            portal_mode=ts.Enums.PortalMode.AnyUserInterface
        )

        # 5. Despacho al handler. La extracción del proyecto es responsabilidad
        #    del propio handler (vía _get_active_project) si lo requiere.
        handler = COMMAND_REGISTRY[command]
        result = handler(portal, ts, args)

        _write_json_and_exit({"ok": True, "result": result}, code=0)

    except Exception as exc:
        sys.stderr.write(f"[WORKER ERROR] {traceback.format_exc()}\n")
        _write_json_and_exit(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
            code=1,
        )
    finally:
        # 6. Liberación estricta de punteros RCW de .NET.
        if portal is not None:
            try:
                portal.detach()
            except Exception as e:
                sys.stderr.write(f"[WORKER DETACH ERROR] {e}\n")


if __name__ == "__main__":
    main()