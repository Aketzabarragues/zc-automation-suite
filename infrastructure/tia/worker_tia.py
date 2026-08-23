"""Motor OT efÃ­mero para interacciÃ³n con TIA Portal Openness.

Este script es ejecutado exclusivamente como un subproceso aislado por TIAProcessGateway.
NACE -> CONECTA (COM) -> EJECUTA COMANDO -> EMITE JSON A STDOUT -> DESCONECTA -> MUERE.

Reglas estricta de I/O:
- STDIN:  Recibe un JSON con 'command' (str) y 'args' (dict).
- STDOUT: Emite UNICAMENTE una lÃ­nea JSON final con {'ok': True, 'result': ...} o {'ok': False, 'error': ...}.
- STDERR: ReorientaciÃ³n de logs, trazas de excepciÃ³n y advertencias C++/CLR.

InyecciÃ³n de dependencias:
  Los handlers del COMMAND_REGISTRY reciben (portal, args). Cada handler que
  necesite un proyecto abierto debe extraerlo con _get_active_project(portal),
  que valida su existencia y centraliza el control de errores. Esto permite
  comandos de ciclo de vida (open_project) que NO requieren proyecto previo.
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, NoReturn

# Forzar UTF-8 en los streams del worker.
# El worker es un subproceso de TIAProcessGateway (vía
# asyncio.create_subprocess_exec en Windows con CreateProcess).
# La reconfigure de main.py NO se hereda al subproceso, así que
# lo hacemos también aquí. Sin esto, Pythonnet intenta convertir
# strings de TIA Portal (Latin-1) a Python UTF-8 y revienta con
# "utf-8 codec can't decode byte 0xe1 in position N".
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")



def _write_json_and_exit(payload: dict[str, Any], code: int) -> NoReturn:
    """Escribe la respuesta estructurada en stdout y finaliza el proceso."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    sys.exit(code)


def _get_active_project(portal: Any) -> Any:
    """Extrae y valida el proyecto activo del portal.

    Centraliza la lÃ³gica de extracciÃ³n y validaciÃ³n del proyecto. Antes vivÃ­a
    en main(); ahora cada handler que necesita proyecto lo invoca, lo que
    permite comandos de ciclo de vida (open_project) que NO requieren
    proyecto previo y produce errores semÃ¡nticos limpios en los demÃ¡s.
    """
    project = portal.get_project()
    if not project:
        raise RuntimeError(
            "No hay ningÃºn proyecto abierto en TIA Portal. "
            "Ejecuta 'open_project' primero."
        )
    return project


def _find_plc(project: Any, plc_name: str) -> Any:
    """Resuelve el objeto Plc por nombre dentro del proyecto activo.

    Helper centralizado para evitar duplicaciÃ³n en los handlers del dispatcher.
    Levanta RuntimeError si no existe.
    """
    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    for plc in project.get_plcs():
        if _safe_get_plc_name(plc) == plc_name:
            return plc

    raise RuntimeError(
        f"No se encontrÃ³ ningÃºn PLC con el nombre '{plc_name}' en el proyecto activo."
    )


def _safe_get_plc_name(plc) -> str | None:
    """Lee el nombre de un Plc tolerando errores de encoding.

    Algunos PLCs / tablas del proyecto tienen nombres con
    caracteres no-ASCII (Latin-1, p.ej. acentos). Pythonnet
    intenta convertir el .Name a Python str y revienta con
    UnicodeDecodeError. Como nosotros solo necesitamos comparar
    contra nombres ASCII, devolvemos None en ese caso (la
    comparaciÃ³n fallarÃ¡ y se tratarÃ¡ como "no es la que
    buscamos").
    """
    try:
        return plc.get_name()
    except UnicodeDecodeError:
        return None


def _safe_get_table_name(table) -> str | None:
    """Lee el nombre de una PlcTagTable tolerando errores de encoding.

    Ver ``_safe_get_plc_name``. Algunas PlcTagTables del proyecto
    tienen nombres con caracteres no-ASCII (Latin-1) que hacen
    fallar la conversiÃ³n a Python str via Pythonnet. Como
    nuestra tabla objetivo siempre tiene nombre ASCII, saltamos
    cualquier tabla que no se pueda decodificar.
    """
    try:
        return table.get_name()
    except UnicodeDecodeError:
        return None


def _ensure_target_dir(target_dir: str) -> Path:
    """Valida que target_dir estÃ© presente y devuelve la ruta resuelta."""
    if not target_dir:
        raise ValueError("Se requiere el argumento 'target_dir'.")
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)
    return target_path


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Handlers del dispatcher. Todos reciben (portal: Any, args: dict[str, Any]).
# Cada handler que necesite proyecto abierto invoca _get_active_project().
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _cmd_open_project(portal: Any, ts: Any, args: dict[str, Any]) -> None:
    """Abre un proyecto TIA Portal desde una ruta absoluta. Manual Â§2.4.3.

    PRECONDICIÃ“N: el portal ya estÃ¡ conectado (vÃ­a ``attach_portal`` o
    ``open_new_portal``). Para abrir proyecto desde cero (cold start),
    usar ``open_new_portal``.
    """
    _ = ts
    project_file_path: str = args.get("project_file_path", "")
    if not project_file_path:
        raise ValueError("Se requiere el argumento 'project_file_path'.")
    if not os.path.isfile(project_file_path):
        raise RuntimeError(f"El archivo de proyecto no existe: '{project_file_path}'.")
    portal.open_project(project_file_path=project_file_path)


def _cmd_attach_portal(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Hot-attach a una instancia YA EJECUTÃNDOSE de TIA Portal.

    Usa ``ts.attach_portal(portal_mode=...)`` (Manual V1.2.1 Â§2.4.2).
    Escenario tÃ­pico: el operario ya tiene TIA Portal abierto; el
    gateway se acopla a esa instancia sin abrir un proceso nuevo.

    Returns:
        ``True`` si el acople fue exitoso (``portal`` no es ``None``).
    """
    _ = portal  # se ignora: attach reemplaza la instancia
    _ = args  # sin args adicionales (el modo AnyUserInterface es implÃ­cito)
    new_portal = ts.attach_portal(
        portal_mode=ts.Enums.PortalMode.AnyUserInterface
    )
    if new_portal is None:
        raise RuntimeError(
            "Fallo crÃ­tico: attach_portal retornÃ³ None. "
            "Â¿EstÃ¡ TIA Portal abierto? Â¿El usuario pertenece al grupo Openness?"
        )
    return True


def _cmd_open_new_portal(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Cold start: lanza una instancia NUEVA de TIA Portal y abre proyecto.

    Sigue el Manual V1.2.1 Â§2.4.1:
      1. ``ts.open_portal(portal_mode=...)`` â†’ instancia del portal.
      2. ``portal.open_project(project_file_path=...)`` â†’ abre proyecto.

    Args:
        project_file_path: Ruta absoluta al .apxx.

    Returns:
        ``True`` si el portal nuevo se creÃ³ con Ã©xito.
    """
    project_file_path: str = args.get("project_file_path", "")
    if not project_file_path:
        raise ValueError(
            "open_new_portal requiere el argumento 'project_file_path'."
        )
    if not os.path.isfile(project_file_path):
        raise RuntimeError(
            f"El archivo de proyecto no existe: '{project_file_path}'."
        )
    _ = portal  # se ignora: open_portal reemplaza la instancia
    new_portal = ts.open_portal(
        portal_mode=ts.Enums.PortalMode.AnyUserInterface
    )
    if new_portal is None:
        raise RuntimeError(
            "Fallo crÃ­tico: open_portal retornÃ³ None."
        )
    new_portal.open_project(project_file_path=project_file_path)
    return True


def _cmd_save_project(portal: Any, ts: Any, args: dict[str, Any]) -> None:
    """Guarda los cambios pendientes del proyecto activo (manual Â§2.37.2)."""
    _ = ts
    project = _get_active_project(portal)
    project.save()


def _cmd_close_project(portal: Any, ts: Any, args: dict[str, Any]) -> None:
    """Cierra el proyecto activo (manual Â§2.37.3).

    ADVERTENCIA CRÃTICA: project.close() destruye permanentemente todos
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
    """Lista los nombres de los bloques de programa de un PLC especÃ­fico."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    # CoerciÃ³n defensiva (TIA Portal V21): aunque el manual define folder_path
    # como Optional[str], el wrapper .NET rechaza valores None. Forzamos "" para
    # que el binding del CLR acepte el parÃ¡metro y delegue al comportamiento
    # nativo de "raÃ­z del PLC".
    folder_path: str = args.get("folder_path") or ""

    target_plc = _find_plc(project, plc_name)
    blocks = target_plc.get_program_blocks(folder_path=folder_path)
    return [block.get_name() for block in blocks]


def _cmd_compile_plc(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Compila el software del PLC y retorna el booleano nativo de Siemens.

    SemÃ¡ntica documentada (API V1.2.1, secciÃ³n 2.2.11):
      - True  -> La compilaciÃ³n TIENE errores.
      - False -> La compilaciÃ³n NO tiene errores (Ã©xito).
    La capa de presentaciÃ³n (MCP) traduce este valor a un mensaje humano.
    """
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    target_plc = _find_plc(project, plc_name)
    return bool(target_plc.compile_software())


def _export_objects_sd(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta una colecciÃ³n de objetos TIA (Bloques o UDTs) a archivos .s7dcl.

    Espera en args: plc_name, target_dir, collection_key
    ('program_blocks' | 'user_data_types'). `ts` se inyecta desde
    `_load_siemens_wrapper()` para acceder a los enumeradores nativos
    (ts.Enums.ExportFormats.SimaticSD, etc.).

    Nota de formato: TIA Portal V21 emite archivos .s7dcl
    (Simatic Source Documents) cuando se solicita ``export_format=SimaticSD``.
    El sufijo ``.s7dcl`` es el canÃ³nico a partir de V17; el ``.scl``
    histÃ³rico queda obsoleto en esta arquitectura.
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
        # El wrapper nativo de Siemens soporta coerciÃ³n desde strings hacia
        # sus enumeradores internos (TypeError previo: "export_format must
        # be an Enum or string"). Inyectamos el literal "SimaticSD" para
        # forzar la exportaciÃ³n en formato fuente SimaticSD (.s7dcl) sin
        # depender del espacio de nombres ts.Enums.ExportFormats (no
        # expuesto en este build). Manual V1.2.1, secciones 2.10.5 y 2.15.5.
        obj.export(
            target_directory_path=str(target_path),
            export_format="SimaticSD",
            keep_folder_structure=True,
        )

    return str(target_path)


def _cmd_export_blocks_sd(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta los bloques de programa del PLC como archivos Simatic Source Documents (.s7dcl)."""
    args = {**args, "collection_key": "program_blocks"}
    return _export_objects_sd(portal, ts, args)


def _cmd_export_udts_sd(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta los User Data Types (UDTs) del PLC como archivos Simatic Source Documents (.s7dcl)."""
    args = {**args, "collection_key": "user_data_types"}
    return _export_objects_sd(portal, ts, args)


def _cmd_export_plc_tags_xml(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta las tablas de variables del PLC como XML SimaticML.

    Itera sobre plc.get_plc_tag_tables() (manual Â§2.2.8) y exporta cada
    tabla con export_format=SimaticML, export_options=WithDefaults y
    keep_folder_structure=True (preserva jerarquÃ­a de grupos del PLC).
    """
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")

    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    tag_tables = target_plc.get_plc_tag_tables()
    for table in tag_tables:
        # MitigaciÃ³n defensiva: el wrapper nativo no expone ni
        # ExportFormats ni ExportOptions en este build. SegÃºn la
        # documentaciÃ³n oficial (manual V1.2.1, secciones 2.10.5 y 2.15.5),
        # ambos parÃ¡metros son opcionales; al omitirlos, el wrapper C++
        # subyacente aplica los defaults internos (SimaticML para el
        # formato, None para las opciones).
        table.export(
            target_directory_path=str(target_path),
            keep_folder_structure=True,
        )

    return str(target_path)


def _cmd_import_blocks_sd(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Importa bloques de programa en formato Simatic Source Documents (.s7dcl) desde el disco al PLC (manual Â§2.2.23).

    TIA Portal asume que el directorio existe; si no, el CLR lanza una
    excepciÃ³n grave. Por eso validamos con os.path.isdir() ANTES de invocar
    el mÃ©todo COM.

    Nota: el nombre del comando refleja la convenciÃ³n actual (.s7dcl /
    SimaticSD); internamente el wrapper sigue invocando
    ``target_plc.import_blocks`` porque la API de Siemens mantiene
    estable el nombre del mÃ©todo independientemente de la extensiÃ³n
    del archivo.
    """
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    # CoerciÃ³n defensiva (TIA Portal V21): el wrapper .NET no acepta None para
    # target_folder_path aunque el manual lo declare Optional[str]. Forzamos "".
    target_folder: str = args.get("target_folder") or ""

    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")

    if not os.path.isdir(import_dir):
        raise RuntimeError(
            f"El directorio de importaciÃ³n no existe o no es accesible: '{import_dir}'."
        )

    target_plc = _find_plc(project, plc_name)
    target_plc.import_blocks(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return True


def _cmd_import_plc_tags_xml(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Importa tablas de variables (PLC tags) en formato XML al PLC (manual Â§2.2.24).

    ValidaciÃ³n previa con os.path.isdir() para evitar la excepciÃ³n grave
    del CLR cuando el directorio no existe.
    """
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    # CoerciÃ³n defensiva (TIA Portal V21): el wrapper .NET no acepta None para
    # target_folder_path aunque el manual lo declare Optional[str]. Forzamos "".
    target_folder: str = args.get("target_folder") or ""

    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")

    if not os.path.isdir(import_dir):
        raise RuntimeError(
            f"El directorio de importaciÃ³n no existe o no es accesible: '{import_dir}'."
        )

    target_plc = _find_plc(project, plc_name)
    target_plc.import_plc_tags(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return True


def _cmd_export_block(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta un Ãºnico bloque de programa como SimaticSD (.scl). Manual Â§2.10.5."""
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
    """Importa un Ãºnico bloque (.scl) desde disco al PLC. Manual Â§2.2.23."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    # CoerciÃ³n defensiva (TIA Portal V21): el wrapper .NET no acepta None para
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
    """Exporta una Ãºnica PlcTagTable como XML SimaticML. Manual Â§2.10.5 / Â§2.28.3."""
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
    """Importa una Ãºnica PlcTagTable (XML) desde disco al PLC. Manual Â§2.2.24."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    # CoerciÃ³n defensiva (TIA Portal V21): el wrapper .NET no acepta None para
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
    """Devuelve {value: name} de las PlcUserConstant de una tabla. Manual Â§2.28.5."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    if not table_name:
        raise ValueError("Se requiere el argumento 'table_name'.")
    target_plc = _find_plc(project, plc_name)
    tables = target_plc.get_plc_tag_tables()
    table = next((t for t in tables if _safe_get_table_name(t) == table_name), None)
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
    """Actualiza el valor de una PlcUserConstant. Manual Â§2.28."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    constant_name: str = args.get("constant_name", "")
    new_value: int = args.get("new_value", 0)
    target_plc = _find_plc(project, plc_name)
    tables = target_plc.get_plc_tag_tables()
    # FIX UTF-8: algunas PlcTagTables del PLC tienen nombres con
    # caracteres no-ASCII (latin-1, p.ej. 'Dispositivos' o
    # 'Configuracion'). Al iterar, Pythonnet intenta convertir
    # cada .get_name() a Python str y revienta con UnicodeDecodeError.
    # Como nuestra tabla objetivo tiene nombre ASCII
    # ('000_Config_Dispositivos'), podemos saltarnos las tablas
    # que fallen al decodificar su nombre; no son la nuestra.
    def _safe_get_name(t):
        try:
            return t.get_name()
        except UnicodeDecodeError:
            return None
    table = next(
        (t for t in tables if _safe_get_name(t) == table_name),
        None,
    )
    if table is None:
        raise RuntimeError(f"Tabla '{table_name}' no encontrada.")
    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == constant_name:
            constant.set_property(name="Value", value=str(new_value))
            return True
    raise RuntimeError(f"Constante '{constant_name}' no encontrada en tabla '{table_name}'.")


def _cmd_update_user_constant_name(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Renombra una PlcUserConstant. Manual Â§2.28."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    current_name: str = args.get("current_name", "")
    new_name: str = args.get("new_name", "")
    target_plc = _find_plc(project, plc_name)
    tables = target_plc.get_plc_tag_tables()
    table = next((t for t in tables if _safe_get_table_name(t) == table_name), None)
    if table is None:
        raise RuntimeError(f"Tabla '{table_name}' no encontrada.")
    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == current_name:
            constant.set_property(name="Name", value=new_name)
            return True
    raise RuntimeError(f"Constante '{current_name}' no encontrada en tabla '{table_name}'.")


def _cmd_rename_plc_tag(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Renombra un PlcTag en TIA Portal preservando referencias cruzadas.

    Motor Diff hÃ­brido (Fase 5): cuando el ``uid`` coincide pero
    ``plc_tag`` cambia, NO modificamos el XML (eso perderÃ­a las
    referencias en el programa SCL). En su lugar, usamos COM:
      1. ``table.get_plc_tags()`` itera todos los PlcTags de la tabla.
      2. Buscamos el tag cuyo ``Name`` coincide con ``old_name``.
      3. Leemos ``tag.get_property(name="Name")`` (verificaciÃ³n defensiva).
      4. ``tag.set_property(name="Name", value=new_name)``.

    Args:
        plc_name:   Nombre del PLC destino.
        old_name:   Nombre actual del PlcTag en TIA Portal.
        new_name:   Nuevo nombre a asignar (preserva referencias cruzadas).

    Returns:
        ``True`` si el rename fue exitoso.
    """
    _ = ts
    plc_name: str = args.get("plc_name", "")
    old_name: str = args.get("old_name", "")
    new_name: str = args.get("new_name", "")
    if not (plc_name and old_name and new_name):
        raise ValueError(
            "rename_plc_tag requiere 'plc_name', 'old_name' y 'new_name'."
        )

    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    # Recorremos TODAS las PlcTagTables buscando el PlcTag por old_name.
    # El uid no es nativo en TIA → el rename se identifica por Name
    # actual (que es el plc_tag histórico que el motor IT conoce).
    #
    # NOTA: ``tag.get_property`` y ``tag.set_property`` SOLO aceptan
    # keyword arguments en este wrapper de Siemens Openness (Pythonnet).
    # Llamadas posicionales como ``tag.get_property("Name")`` lanzan
    # ``TypeError: get_property() takes no positional arguments``.
    # Por consistencia con el resto de handlers del worker
    # (``_cmd_get_user_constants``, ``_cmd_update_user_constant_value``
    # y ``_cmd_update_user_constant_name``), usamos siempre keyword args.
    for table in target_plc.get_plc_tag_tables():
        for tag in table.get_plc_tags():
            current = tag.get_property(name="Name")
            if current == old_name:
                tag.set_property(name="Name", value=new_name)
                return True

    raise RuntimeError(
        f"No se encontrÃ³ PlcTag con Name='{old_name}' en PLC '{plc_name}'."
    )


def _cmd_delete_user_constant(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Borra una PlcUserConstant. Manual Â§2.34.4. snake_case: constant.delete()."""
    _ = ts
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    constant_name: str = args.get("constant_name", "")
    target_plc = _find_plc(project, plc_name)
    tables = target_plc.get_plc_tag_tables()
    table = next((t for t in tables if _safe_get_table_name(t) == table_name), None)
    if table is None:
        raise RuntimeError(f"Tabla '{table_name}' no encontrada.")
    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == constant_name:
            constant.delete()
            return True
    raise RuntimeError(f"Constante '{constant_name}' no encontrada en tabla '{table_name}'.")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Lotes transaccionales: ejecutan N comandos atÃ³micos bajo una ÃšNICA
# transacciÃ³n de TIA Portal. Si una operaciÃ³n falla, las anteriores se
# deshacen vÃ­a end_transaction(rollback=True). Esto garantiza atomicidad
# en el historial del proyecto (Undo) y previene estados intermedios
# inconsistentes.
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Comandos prohibidos dentro de un lote. CausarÃ­an:
#   - open/close_project: destruirÃ­an el portal activo a mitad del lote.
#   - save_project      : forzarÃ­a un commit parcial fuera de la transacciÃ³n.
#   - list_plcs         : no es una operaciÃ³n, es introspecciÃ³n.
#   - execute_transactional_batch: anidamiento no soportado (podrÃ­a
#     balancear transacciones de forma incorrecta sobre el RCW del project).
_TRANSACTION_FORBIDDEN_COMMANDS: frozenset[str] = frozenset(
    {
        "open_project",
        "close_project",
        "save_project",
        "list_plcs",
        "execute_transactional_batch",
        "compile_plc"
    }
)


def _cmd_execute_transactional_batch(
    portal: Any, ts: Any, args: dict[str, Any]
) -> dict[str, Any]:
    """Ejecuta mÃºltiples comandos atÃ³micos bajo una Ãºnica transacciÃ³n de TIA Portal.

    ActÃºa como ACUMULADOR DE RESULTADOS: captura el valor de retorno de cada
    handler atÃ³mico y lo agrega a `details`, evitando el "sumidero de datos"
    clÃ¡sico donde el lote ejecuta operaciones pero la capa IT queda ciega
    ante los resultados intermedios (p. ej. el booleano de compile_plc, la
    ruta de export_blocks_scl, etc.).

    AÃ­sla la cadena bajo `project.start_transaction()` / `end_transaction()`
    (manual Â§2.37.27 / Â§2.37.28). Si cualquier handler levanta excepciÃ³n,
    se invoca `end_transaction(rollback=True)` para revertir TODA la cadena
    y se propaga un RuntimeError con el paso exacto que causÃ³ el aborto.

    Args:
        portal: Instancia del portal TIA (inyectada por el dispatcher).
        ts:     MÃ³dulo Siemens inyectado (no usado directamente aquÃ­, pero
                requerido por la firma uniforme del COMMAND_REGISTRY).
        args:   Dict con:
                  - operations: list[dict] -> [{"command": str, "args": dict}, ...]
                  - undo_text:  str (opcional) -> texto del historial.

    Returns:
        {
            "success":             True,
            "operations_executed": int,
            "details": [
                {"step": int, "command": str, "result": Any},
                ...
            ],
        }

    Raises:
        ValueError: Si la lista estÃ¡ vacÃ­a, contiene un comando desconocido
                    o un comando prohibido dentro de un lote.
        RuntimeError: Si una operaciÃ³n falla; el mensaje identifica el
                      Ã­ndice (basado en pasos YA acumulados + 1) y nombre
                      del comando que rompiÃ³ el lote.
    """
    _ = ts
    project = _get_active_project(portal)
    undo_text: str = args.get("undo_text", "OperaciÃ³n por Lote")
    operations: list[dict[str, Any]] = args.get("operations", [])

    if not operations:
        raise ValueError("La lista de operaciones estÃ¡ vacÃ­a.")

    # Iniciar transacciÃ³n nativa (manual Â§2.37.27).
    project.start_transaction(undo_text=undo_text, dialog_text=undo_text)

    # Acumulador de resultados intermedios. Cada paso exitoso aÃ±ade su
    # retorno nativo (bool, str, list, dict, etc.) SIN coerciÃ³n, para
    # preservar la semÃ¡ntica exacta del wrapper de Siemens.
    results_list: list[dict[str, Any]] = []

    cmd: str = ""
    try:
        for idx, op in enumerate(operations):
            cmd = op.get("command", "")
            cmd_args: dict[str, Any] = op.get("args", {})

            if cmd not in COMMAND_REGISTRY:
                raise ValueError(f"Comando desconocido en lote: '{cmd}'")
            if cmd in _TRANSACTION_FORBIDDEN_COMMANDS:
                raise ValueError(
                    f"El comando '{cmd}' estÃ¡ prohibido dentro de un lote "
                    "transaccional."
                )

            # Ejecutar el handler atÃ³mico reinyectando portal y ts,
            # capturando su valor de retorno para inspecciÃ³n posterior.
            step_result: Any = COMMAND_REGISTRY[cmd](portal, ts, cmd_args)

            results_list.append(
                {"step": idx + 1, "command": cmd, "result": step_result}
            )

        # Confirmar transacciÃ³n si no hubo errores (manual Â§2.37.28).
        project.end_transaction(rollback=False)

        return {
            "success": True,
            "operations_executed": len(operations),
            "details": results_list,
        }

    except Exception as e:
        # ReversiÃ³n garantizada ante excepciones (manual Â§2.37.28).
        # Silenciamos fallos secundarios del rollback para no enmascarar
        # la causa raÃ­z original.
        try:
            project.end_transaction(rollback=True)
        except Exception:
            pass
        # len(results_list) marca el ÃšLTIMO paso exitoso; el fallo ocurre
        # en resultados_list + 1 (o en validaciÃ³n previa, donde len=0).
        raise RuntimeError(
            f"Lote abortado en el paso {len(results_list) + 1} ('{cmd}'). "
            f"Rollback ejecutado. Motivo: {e}"
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Sync unificado de constantes (N_MAX + Dispositivos) en UNA transacciÃ³n COM
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Directorio temporal para exportar/importar PlcTagTable durante el sync.
# El path se valida contra whitelist de subdirectorios temporales del sistema.
import tempfile  # noqa: E402  (import tardÃ­o intencional)

from infrastructure.xml.plc_tag_table_manager import PlcTagTableManager  # noqa: E402
from infrastructure.xml.user_constants_modifier import UserConstantsModifier  # noqa: E402


def _cmd_execute_unified_sync(
    portal: Any, ts: Any, args: dict[str, Any]
) -> dict[str, Any]:
    """Orquesta el sync unificado de PlcUserConstant en UNA transacciÃ³n COM.

    Pasos (idÃ©nticos al flow documentado en ``sync_constants_unified.py``):
      1. ``project.start_transaction()``
      2. ONLINE: ``update_user_constant_value`` para cada N_MAX op.
      3. ONLINE: ``update_user_constant_name`` para cada device rename.
      4. ONLINE: ``export_tag_table`` para preparar XML offline.
      5. OFFLINE: crear/eliminar PlcTagTable + aÃ±adir PlcUserConstant nuevas.
      6. ONLINE: ``import_plc_tags_xml`` para reintegrar XMLs.
      7. CIERRE: ``end_transaction(rollback=False)`` o rollback completo.

    Si el rollback ocurre, restaura los backups offline (snapshot de los
    XMLs antes de modificarlos) para garantizar atomicidad real.

    Args:
        plc_name: Nombre del PLC destino.
        nmax_ops: lista de ``{"command": "update_user_constant_value", "args": {...}}``.
        device_renames: lista de ``{"command": "update_user_constant_name", "args": {...}}``.
        device_offline_changes: lista de ``{"action": str, "table_name": str,
            "constants": list[dict], "source_template": str|None}``.
        undo_text: etiqueta para el historial de Undo.

    Returns:
        ``dict`` con ``{"success": bool, "nmax_updated": int,
        "renames_applied": int, "offline_changes": int}``.
    """
    _ = ts
    plc_name: str = args.get("plc_name", "")
    nmax_ops: list[dict[str, Any]] = args.get("nmax_ops", []) or []
    device_renames: list[dict[str, Any]] = args.get("device_renames", []) or []
    offline_changes: list[dict[str, Any]] = args.get("device_offline_changes", []) or []
    undo_text: str = args.get("undo_text", "Sync Constants Unified")

    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    # Snapshot de XMLs modificados offline para rollback manual si la
    # transacciÃ³n COM falla. Cada entrada: (path, contenido_original_bytes).
    offline_backups: list[tuple[Path, bytes]] = []
    # Tablas creadas offline (para limpieza si rollback).
    created_tables: list[Path] = []
    temp_dir: Path | None = None

    try:
        # â”€â”€ 1. START TRANSACTION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        project.start_transaction(undo_text=undo_text, dialog_text=undo_text)

        # â”€â”€ 2. ONLINE: update_user_constant_value (N_MAX) â”€â”€â”€â”€
        nmax_results: list[dict[str, Any]] = []
        for op in nmax_ops:
            cmd_args = op.get("args", {})
            _cmd_update_user_constant_value(portal, ts, cmd_args)
            nmax_results.append(
                {"constant": cmd_args.get("constant_name"), "ok": True}
            )

        # â”€â”€ 3. ONLINE: update_user_constant_name (Devices) â”€â”€â”€
        rename_results: list[dict[str, Any]] = []
        for op in device_renames:
            cmd_args = op.get("args", {})
            _cmd_update_user_constant_name(portal, ts, cmd_args)
            rename_results.append(
                {
                    "old": cmd_args.get("current_name"),
                    "new": cmd_args.get("new_name"),
                    "ok": True,
                }
            )

        # â”€â”€ 4. ONLINE: export_tag_table (preparar offline) â”€â”€â”€
        # Solo exportamos si hay cambios offline que lo requieran.
        tables_to_offline = {
            change["table_name"]
            for change in offline_changes
            if change.get("action") in ("add_constants", "delete")
        }
        # Crear tempdir una sola vez.
        if offline_changes:
            temp_dir = Path(tempfile.mkdtemp(prefix="tia_unified_sync_"))
            for table_name in tables_to_offline:
                _cmd_export_tag_table(
                    portal, ts, {"plc_name": plc_name, "table_name": table_name, "target_dir": str(temp_dir)}
                )

        # â”€â”€ 5. OFFLINE: modificar XMLs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        for change in offline_changes:
            action = change.get("action")
            table_name = change.get("table_name", "")
            if action == "add_constants" and table_name and temp_dir is not None:
                xml_path = temp_dir / f"{table_name}.xml"
                if not xml_path.is_file():
                    raise RuntimeError(
                        f"XML exportado no encontrado para tabla '{table_name}': {xml_path}"
                    )
                # Backup antes de modificar (rollback offline).
                offline_backups.append((xml_path, xml_path.read_bytes()))
                modifier = UserConstantsModifier(xml_path)
                for const in change.get("constants", []) or []:
                    modifier.add_user_constant(
                        name=str(const.get("name", "")),
                        value=int(const.get("value", 0)),
                        comment=str(const.get("comment", "")),
                    )
                modifier.save()
            elif action == "create":
                # Crear PlcTagTable nueva (estructura canÃ³nica vacÃ­a).
                if temp_dir is None:
                    temp_dir = Path(tempfile.mkdtemp(prefix="tia_unified_sync_"))
                mgr = PlcTagTableManager()
                new_path = mgr.create_empty_table(
                    table_name=table_name,
                    target_dir=temp_dir,
                    source_template_path=change.get("source_template"),
                )
                created_tables.append(new_path)
            elif action == "delete":
                # Eliminar PlcTagTable por COM (dentro de la transacciÃ³n).
                target_table = None
                for tbl in target_plc.get_plc_tag_tables():
                    if tbl.get_name() == table_name:
                        target_table = tbl
                        break
                if target_table is not None:
                    target_table.delete()

        # â”€â”€ 6. ONLINE: import_plc_tags_xml â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if temp_dir is not None and temp_dir.is_dir() and any(temp_dir.iterdir()):
            # Solo importamos si hay archivos en temp_dir.
            _cmd_import_plc_tags_xml(
                portal, ts, {"plc_name": plc_name, "import_dir": str(temp_dir)}
            )

        # â”€â”€ 7. CIERRE: success â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        project.end_transaction(rollback=False)
        return {
            "success": True,
            "nmax_updated": len(nmax_results),
            "renames_applied": len(rename_results),
            "offline_changes": len(offline_changes),
            "details": {
                "nmax": nmax_results,
                "renames": rename_results,
            },
        }

    except Exception as e:
        # â”€â”€ 7. CIERRE: rollback atÃ³mico â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            project.end_transaction(rollback=True)
        except Exception:
            pass
        # Restaurar backups offline (rollback manual).
        for path, backup_bytes in offline_backups:
            try:
                path.write_bytes(backup_bytes)
            except Exception as restore_err:
                sys.stderr.write(
                    f"[WORKER] Error restaurando backup {path}: {restore_err}\n"
                )
        # Eliminar tablas creadas offline (rollback manual).
        for created_path in created_tables:
            try:
                if created_path.exists():
                    created_path.unlink()
            except Exception as cleanup_err:
                sys.stderr.write(
                    f"[WORKER] Error eliminando tabla creada {created_path}: {cleanup_err}\n"
                )
        raise RuntimeError(
            f"Sync unificado abortado. Rollback completo aplicado. "
            f"N_MAX={len(nmax_ops)}, renames={len(device_renames)}, "
            f"offline={len(offline_changes)}. Motivo: {e}"
        )
    finally:
        # Limpiar tempdir si existe.
        if temp_dir is not None and temp_dir.is_dir():
            try:
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


COMMAND_REGISTRY: dict[str, Callable[[Any, Any, dict[str, Any]], Any]] = {
    # â”€â”€ Ciclo de vida del proyecto â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "attach_portal": _cmd_attach_portal,
    "open_new_portal": _cmd_open_new_portal,
    "open_project": _cmd_open_project,
    "save_project": _cmd_save_project,
    "close_project": _cmd_close_project,
    # â”€â”€ InspecciÃ³n â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "list_plcs": _cmd_list_plcs,
    "list_blocks": _cmd_list_blocks,
    # â”€â”€ MutaciÃ³n / compilaciÃ³n â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "compile_plc": _cmd_compile_plc,
    # â”€â”€ Rename COM (motor diff hÃ­brido) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "rename_plc_tag": _cmd_rename_plc_tag,
    # â”€â”€ ExportaciÃ³n masiva Simatic Source Documents (.s7dcl) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "export_blocks_sd": _cmd_export_blocks_sd,
    "export_udts_sd": _cmd_export_udts_sd,
    # â”€â”€ ExportaciÃ³n masiva SimaticML (XML) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "export_plc_tags_xml": _cmd_export_plc_tags_xml,
    # â”€â”€ ImportaciÃ³n masiva desde disco (cierre del ciclo I/O) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "import_blocks_sd": _cmd_import_blocks_sd,
    "import_plc_tags_xml": _cmd_import_plc_tags_xml,
    # â”€â”€ Bloques granulares â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "export_block": _cmd_export_block,
    "import_block": _cmd_import_block,
    # â”€â”€ Tablas de variables granulares â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "export_tag_table": _cmd_export_tag_table,
    "import_tag_table": _cmd_import_tag_table,
    # â”€â”€ Constantes de usuario (N_MAX, dimensionamiento) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "get_user_constants": _cmd_get_user_constants,
    "update_user_constant_value": _cmd_update_user_constant_value,
    "update_user_constant_name": _cmd_update_user_constant_name,
    "delete_user_constant": _cmd_delete_user_constant,
    # â”€â”€ Lotes transaccionales (rollback automÃ¡tico) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "execute_transactional_batch": _cmd_execute_transactional_batch,
    # â”€â”€ Sync unificado (N_MAX + Dispositivos en UNA transacciÃ³n) â”€â”€â”€â”€â”€â”€
    "execute_unified_sync": _cmd_execute_unified_sync,
}




def _load_siemens_wrapper() -> Any:
    """Carga nativa del wrapper de Siemens vÃ­a inyecciÃ³n en sys.path.

    Mecanismo heredado del proyecto anterior, superior a importlib.util
    para binarios .pyd con dependencias CLR/Pythonnet: en lugar de fabricar
    un spec sintÃ©tico, expone la ruta de _MEIPASS al loader nativo de
    Python (`_imp`) para que la DLL se cargue por el camino estÃ¡ndar,
    ejecutando correctamente su cÃ³digo de inicializaciÃ³n y registrando
    submÃ³dulos como `ts.Enums`.

    Modo producciÃ³n (PyInstaller --onefile):
      - Inyecta sys._MEIPASS en sys.path (prioridad).
      - AÃ±ade la ruta a la variable de entorno PATH.
      - En Windows 3.8+, registra la ruta vÃ­a os.add_dll_directory para
        que las dependencias nativas sean localizables.

    Modo desarrollo:
      - El mÃ³dulo ya estÃ¡ disponible vÃ­a el venv del usuario; se importa
        directamente con la lÃ³gica estÃ¡ndar.

    Retorna el mÃ³dulo ya inicializado. Lanza ImportError si la DLL no
    se encuentra o falla su carga.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        # InyecciÃ³n prioritaria para el loader nativo.
        if meipass not in sys.path:
            sys.path.insert(0, meipass)

        os.environ["PATH"] = meipass + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(meipass)

        import siemens_tia_scripting as ts
        return ts

    # Modo desarrollo: import estÃ¡ndar del venv.
    import siemens_tia_scripting as ts
    return ts


def main() -> None:
    # 1. Carga dinÃ¡mica tardÃ­a del wrapper nativo (SecciÃ³n 1.7.1 V1.2.1).
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
            {"ok": False, "error": f"Payload STDIN invÃ¡lido (JSON malformado): {e}"},
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
        #    instancias headless (manual V1.2.1 Â§2.4.2). De este modo el
        #    proceso aislado puede reengancharse a la sesiÃ³n ya abierta
        #    por el usuario sin colisionar con su estado.
        portal = ts.attach_portal(
            portal_mode=ts.Enums.PortalMode.AnyUserInterface
        )
        if portal is None:
            raise RuntimeError(
                "Fallo crÃ­tico: attach_portal retornÃ³ una referencia nula. "
                "AsegÃºrate de que TIA Portal estÃ¡ abierto o implementa open_portal."
            )

        # 5. Despacho al handler. La extracciÃ³n del proyecto es responsabilidad
        #    del propio handler (vÃ­a _get_active_project) si lo requiere.
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
        # 6. LiberaciÃ³n estricta de punteros RCW de .NET.
        if portal is not None:
            try:
                portal.detach()
            except Exception as e:
                sys.stderr.write(f"[WORKER DETACH ERROR] {e}\n")


if __name__ == "__main__":
    main()
