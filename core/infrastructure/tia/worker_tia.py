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
# Reconfiguración de I/O a UTF-8. Vive aquí (no a nivel de módulo) para no
# romper a quien importe este módulo (p. ej. tests que usan capture de pytest).
def _reconfigure_stdio_utf8() -> None:
    if sys.platform != "win32":
        return
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

    Args:
        args: Dict con:
            - ``plc_name`` (str, requerido): nombre del PLC destino.
            - ``target_dir`` (str, requerido): directorio donde escribir
              los XML exportados.
            - ``table_names`` (list[str], opcional): filtro de tablas a
              exportar. Si se pasa y no es ``None``, SOLO se exportan las
              tablas cuyo ``get_name()`` estÃ© en la lista. Si es ``None``
              o se omite, se exportan TODAS las tablas del PLC (back-compat
              con llamadas existentes).
    """
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    target_table_names: list[str] | None = args.get("table_names")

    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    tag_tables = target_plc.get_plc_tag_tables()
    for table in tag_tables:
        if target_table_names is not None:
            # Filtro selectivo: solo exportamos las tablas pedidas.
            # Usamos ``_safe_get_table_name`` (tolerante a UnicodeDecodeError
            # en tablas con caracteres no-ASCII) y comparamos contra la
            # whitelist.
            name = _safe_get_table_name(table)
            if name not in target_table_names:
                continue
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


# ─── COMMAND_REGISTRY ──────────────────────────────────────────────────────
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
    tag_tables = target_plc.get_plc_tag_tables()
    for table in tag_tables:
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
        #
        # Incluimos los ``args`` de la op que fallÃ³ (truncados a 500
        # chars) para diagnÃ³stico. Sin esto, el operario ve
        # ``Lote abortado en el paso 72 ('update_user_constant_value')``
        # pero no sabe quÃ© ``N_MAX`` ni quÃ© valor es el problemÃ¡tico.
        import json as _json
        try:
            args_str = _json.dumps(cmd_args, ensure_ascii=False, default=str)[:500]
        except Exception:
            args_str = repr(cmd_args)[:500]
        raise RuntimeError(
            f"Lote abortado en el paso {len(results_list) + 1} ('{cmd}'). "
            f"Args: {args_str}. "
            f"Rollback ejecutado. Motivo: {e}"
        )


def _cmd_commit_devices_sync(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Commit atomico N_MAX + renames + devices en UNA sola transaccion TIA.

    Este op compuesto reemplaza el flujo de 3-4 ops separadas
    (``update_user_constant_value`` x N, ``update_user_constant_name`` x N,
    ``export_plc_tags_xml``, ``import_plc_tags_xml``) por UNA sola entrada
    en el ``COMMAND_REGISTRY`` que ejecuta todo bajo una unica
    ``start_transaction`` / ``end_transaction``.

    Orden estricto (especificacion del operario, ver plan 2026-08-28):
      1. ``project.start_transaction``.
      2. N_MAX online (``_cmd_update_user_constant_value`` por cada uno).
      3. Renames online (``_cmd_update_user_constant_name`` por cada uno).
      4. Por cada ``device_change`` (tabla con adds o removes):
         a. Export selectivo de la tabla (``table.export``,
            ``keep_folder_structure=True``) a ``work_dir``.
         b. Edit XML offline (``TagTableModifier`` en el worker — modulo
            Python puro, no rompe ``.clinerules Â§1``).
         c. Import selectivo de la tabla (``target_plc.import_plc_tags``).
      5. ``project.end_transaction(rollback=False)``.

    Si CUALQUIER paso falla, se ejecuta ``end_transaction(rollback=True)``
    y se relanza la excepcion con el indice del paso que rompio el lote
    (mismo patron que ``_cmd_execute_transactional_batch``).

    Args:
        args: Dict con:
            - ``plc_name`` (str, requerido).
            - ``undo_text`` (str, opcional, default
              "Sync dispositivos (N_MAX + devices)"): texto del historial
              Undo de TIA.
            - ``work_dir`` (str, requerido): directorio donde el worker
              escribe los XML exportados/modificados. Se conserva tras la
              operacion para inspeccion manual.
            - ``nmax_ops`` (list[dict], default ``[]``): cada dict con
              ``{table_name, constant_name, new_value}``. Online.
            - ``rename_ops`` (list[dict], default ``[]``): cada dict con
              ``{table_name, current_name, new_name}``. Online.
            - ``device_changes`` (list[dict], default ``[]``): cada dict
              con ``{table_name, tia_folder, adds, removes}``. ``adds`` es
              ``list[{plc_tag, uid}]``; ``removes`` es ``list[str]`` de
              uids a eliminar. Offline (export + edit + import por tabla).

    Returns:
        Dict con shape de ``_cmd_execute_transactional_batch``:
        ``{"success": True, "operations_executed": int, "details": [...]}``.

    Raises:
        ValueError: si faltan argumentos requeridos (``plc_name``,
            ``work_dir``).
        RuntimeError: si una op falla (N_MAX, rename, export, edit,
            import). El mensaje identifica el paso exacto que rompio la
            cadena. La transaccion TIA se ha rollbackeado.
    """
    _ = ts
    project = _get_active_project(portal)
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

    target_plc = _find_plc(project, plc_name)
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    # Importacion perezosa del modifier para no introducir ciclos al
    # cargar el worker (TagTableModifier vive en ``core/infrastructure/xml``
    # y no importa ``siemens_tia_scripting``).
    from core.infrastructure.xml.modifiers import TagTableModifier

    # Acumulador de resultados: cada paso anade su retorno nativo
    # (bool de update_user_constant_*, str de export, etc.) para
    # inspeccion posterior. Mismo patron que ``_cmd_execute_transactional_batch``.
    results_list: list[dict[str, Any]] = []
    step_idx = 0
    op_label = ""

    def _record(op_name: str, result: Any) -> None:
        """Anade un paso exitoso al acumulador."""
        nonlocal step_idx
        step_idx += 1
        results_list.append(
            {"step": step_idx, "command": op_name, "result": result}
        )

    try:
        # 1. Iniciar transaccion.
        project.start_transaction(
            undo_text=undo_text, dialog_text=undo_text
        )

        # 2. N_MAX online.
        for nmax_op in nmax_ops:
            op_label = f"update_user_constant_value({nmax_op.get('constant_name')})"
            r = _cmd_update_user_constant_value(
                portal, ts, {
                    "plc_name": plc_name,
                    "table_name": nmax_op["table_name"],
                    "constant_name": nmax_op["constant_name"],
                    "new_value": nmax_op["new_value"],
                }
            )
            _record("update_user_constant_value", r)

        # 3. Renames online.
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

        # 4. Devices: export + edit + import por cada tabla.
        for dev_change in device_changes:
            table_name: str = dev_change["table_name"]
            tia_folder: str = dev_change.get("tia_folder", "")
            adds: list[dict[str, str]] = dev_change.get("adds") or []
            removes: set[str] = set(dev_change.get("removes") or [])

            # 4a. Buscar la tabla.
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

            # 4b. Export selectivo (incluye la estructura de carpetas TIA).
            op_label = f"export_plc_tags_xml({table_name})"
            table.export(
                target_directory_path=str(work_path),
                keep_folder_structure=True,
            )
            _record(
                f"export_plc_tags_xml[{table_name}]",
                str(work_path),
            )

            # 4c. Edit XML offline (dentro del worker). El export
            # escribio ``work_dir/<tia_folder>/<table_name>.xml``;
            # modificamos in-place.
            xml_path = work_path / tia_folder / f"{table_name}.xml"
            if not xml_path.is_file():
                # Fallback: buscar el XML en cualquier subdirectorio
                # de ``work_dir`` (defensivo, por si la estructura de
                # carpetas varia entre versiones de TIA).
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
            if modifier.was_modified():
                modifier.save(xml_path)
            _record(
                f"edit_xml[{table_name}]",
                {
                    "added": added_count,
                    "removed": removed_count,
                    "modified": modifier.was_modified(),
                },
            )

            # 4d. Import selectivo.
            op_label = f"import_plc_tags_xml({table_name})"
            target_plc.import_plc_tags(
                import_root_directory=str(work_path),
                target_folder_path=tia_folder,
            )
            _record(
                f"import_plc_tags_xml[{table_name}]",
                True,
            )

        # 5. Cerrar transaccion (commit).
        project.end_transaction(rollback=False)

        return {
            "success": True,
            "operations_executed": step_idx,
            "details": results_list,
        }

    except Exception as e:
        # Rollback garantizado.
        try:
            project.end_transaction(rollback=True)
        except Exception:
            pass
        # Truncar args del op que fallo para no inundar el log.
        import json as _json
        try:
            args_str = _json.dumps(
                {"op": op_label, "device_change": device_changes[-1] if device_changes else None},
                ensure_ascii=False, default=str
            )[:500]
        except Exception:
            args_str = repr(op_label)[:500]
        raise RuntimeError(
            f"commit_devices_sync abortado en el paso {step_idx + 1} "
            f"('{op_label}'). Rollback ejecutado. Motivo: {e}. "
            f"Contexto: {args_str}"
        )


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
    # â”€â”€ Commit atomico compuesto (N_MAX + renames + devices) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "commit_devices_sync": _cmd_commit_devices_sync,
}


# ─── Punto de extensión: comandos aportados por las áreas ────────────────
# Las áreas (Bounded Contexts) registradas en ``areas/*/`` aportan
# comandos transaccionales adicionales al ``COMMAND_REGISTRY`` mediante
# ``AreaSpec.contributes_tia_commands``. Dichos handlers corren
# DENTRO del proceso del worker, bajo la misma transacción atómica
# que cualquier otro comando del lote, pero NO importan
# ``siemens_tia_scripting`` directamente (cumplen la regla
# ``.clinerules`` §1: el worker es el único proceso que importa la DLL).
#
# Esta llamada se ejecuta una sola vez al import del módulo. Como
# Python cachea los imports, está OK que se invoque varias veces
# (los handlers se machacan por nombre, no se duplican).
#
# Importación al final del módulo para evitar ciclo con ``AreaRegistry``:
#   worker_tia → command_loader → AreaRegistry → areas.<area>
#     → extra_commands → (lazy) worker_tia
# Cuando este bloque se ejecuta, ``COMMAND_REGISTRY`` ya está
# completamente definido, por lo que las áreas pueden mutarlo in-place.
from core.infrastructure.tia.command_loader import load_extra_commands

load_extra_commands(COMMAND_REGISTRY)




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
