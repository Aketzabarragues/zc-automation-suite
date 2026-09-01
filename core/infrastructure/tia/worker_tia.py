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
import logging
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NoReturn

from core.models.bloque_plc import BloquePLC

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


_logger = logging.getLogger(__name__)



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


def _cmd_get_project_info(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Devuelve propiedades básicas del proyecto TIA activo como primitivos.

    Lee un set acotado de propiedades del proyecto que son útiles para
    que la SPA muestre al operario a qué proyecto está enganchado. NO
    devuelve objetos nativos TIA (siempre primitivos, por AGENTS.md §Datos).

    Si una propiedad lanza al leerla (p. ej. PermissionDenied o
    EncodingError), se omite del payload en lugar de tumbar el handler:
    la SPA recibe un dict parcial y renderiza solo lo disponible.

    Args:
        portal: Instancia de TIA Portal ya enganchada.
        ts: Módulo ``siemens_tia_scripting`` (no se usa directamente;
            el handler opera sobre el ``portal`` ya inicializado).
        args: Argumentos del comando (no se usan; no se requiere
            configuración del caller).

    Returns:
        ``dict`` con al menos la key ``name``. Opcionalmente también
        ``path``, ``author``, ``creation_time``, ``last_modified``,
        ``last_modified_by`` y ``version``, omitidas si no están
        disponibles o si su lectura lanza. Los datetimes .NET se
        serializan como strings ISO 8601.
    """
    _ = ts
    project = _get_active_project(portal)

    def _safe_get(name: str) -> Any:
        try:
            return project.get_property(name=name)
        except Exception:
            return None

    result: dict[str, Any] = {"name": _safe_get("Name")}

    # Propiedades opcionales. Si una no está activa o falla, se omite.
    for prop_name, out_key in (
        ("Path", "path"),
        ("Author", "author"),
        ("CreationTime", "creation_time"),
        ("LastModified", "last_modified"),
        ("LastModifiedBy", "last_modified_by"),
        ("Version", "version"),
    ):
        value = _safe_get(prop_name)
        if value is None:
            continue
        # Normalizar a primitivo: datetime/DateTime .NET → ISO 8601 string.
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        result[out_key] = value

    return result


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


def _safe_get_block_name(block) -> str | None:
    """Lee el nombre de un bloque tolerando UnicodeDecodeError.

    Algunos bloques del PLC tienen nombres con caracteres no-ASCII
    (Latin-1) que hacen fallar la conversion a Python str via Pythonnet.
    Como nosotros solo necesitamos nombres ASCII para nuestros caches,
    devolvemos ``None`` y dejamos que el caller descarte el bloque
    silenciosamente (el worker loguea a debug).
    """
    try:
        if hasattr(block, "get_name"):
            return block.get_name()
        if hasattr(block, "Name"):
            return block.Name
    except UnicodeDecodeError:
        return None
    except Exception:
        return None
    return None


def _safe_get_block_path(block) -> str:
    """Lee la ruta jerarquica de un bloque tolerando COM exceptions.

    El escaner silenció COM exceptions menores al leer la ruta de un
    bloque (legacy ``scanner.py`` lineas 156-169): TIA Portal las
    detecta y envenena la transaccion si esto ocurre DENTRO del
    ``with transaccion()``. Como ahora el escaneo se hace fuera de
    cualquier transaccion activa, solo logueamos a debug y devolvemos
    ``""`` para que el bloque siga siendo cacheado con su nombre.
    """
    try:
        if hasattr(block, "get_path"):
            return str(block.get_path())
        if hasattr(block, "Path"):
            return str(block.Path)
    except Exception as e:
        _logger.debug(
            "No se pudo obtener la ruta del bloque '%s' (estado temporal): %s",
            getattr(block, "get_name", lambda: getattr(block, "Name", "?"))()
            if not isinstance(
                getattr(block, "get_name", lambda: getattr(block, "Name", "?")), bytes
            )
            else "?",
            e,
        )
        return ""
    return ""


def _scan_block_group_recursive(group_or_blocks: Any) -> list[dict[str, Any]]:
    """Recorre recursivamente un grupo o coleccion de bloques y devuelve DTOs.

    Estrategia (espejo del legacy ``scanner._scan_group_recursive``):
      1. Extrae la lista plana de bloques via ``get_blocks()`` (preferred)
         o ``.Blocks`` (fallback). Si ninguno, intenta ``__iter__``.
      2. Procesa cada bloque: nombre, ruta, derivar tipo y numero.
      3. Extrae sub-grupos via ``get_groups()`` / ``.Groups`` y recurre.

    Returns:
        Lista de ``dict`` con shape ``BloquePLC.to_dict()``.
        Bloques con nombre inaccesible (UnicodeDecodeError) se omiten
        silenciosamente (logueados a debug).
    """
    blocks_iter: list[Any] = []
    try:
        if hasattr(group_or_blocks, "get_blocks"):
            blocks_iter = list(group_or_blocks.get_blocks() or [])
        elif hasattr(group_or_blocks, "Blocks"):
            blocks_iter = list(group_or_blocks.Blocks or [])
        elif hasattr(group_or_blocks, "__iter__"):
            blocks_iter = list(group_or_blocks)
    except Exception as e:
        _logger.warning("No se pudieron obtener bloques del grupo: %s", e)
        blocks_iter = []

    out: list[dict[str, Any]] = []
    for block in blocks_iter:
        nombre = _safe_get_block_name(block)
        if not nombre:
            _logger.debug("Bloque sin nombre legible: omitido.")
            continue
        ruta = _safe_get_block_path(block)
        tipo = BloquePLC.detect_tipo(nombre)
        match = re.match(r"^(DB|FB|FC|OB|UDT)(\d+)", nombre, re.IGNORECASE)
        numero = int(match.group(2)) if match else 0
        out.append(
            BloquePLC(
                nombre=str(nombre),
                numero=numero,
                tipo=tipo,
                ruta=ruta,
            ).to_dict()
        )

    groups: list[Any] = []
    try:
        if hasattr(group_or_blocks, "get_groups"):
            groups = list(group_or_blocks.get_groups() or [])
        elif hasattr(group_or_blocks, "Groups"):
            groups = list(group_or_blocks.Groups or [])
    except Exception as e:
        _logger.warning("No se pudieron obtener subgrupos: %s", e)
        groups = []

    for sub in groups:
        out.extend(_scan_block_group_recursive(sub))

    return out


def _cmd_scan_blocks(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Escanea recursivamente TODOS los bloques, tag tables y UDTs de un PLC.

    Devuelve un dict primitivo serializable (lista de bloques + lista de
    tablas + lista de UDTs + timestamp ISO 8601 + nombre del PLC). El IT
    reconstruye ``BloqueCache`` a partir de este payload.

    Args:
        portal: instancia del portal TIA (inyectada por el dispatcher).
        ts: modulo Siemens (no usado directamente aqui).
        args: dict con ``plc_name`` (str, requerido).

    Returns:
        ``{
            "plc_name":   str,
            "blocks":     [ {nombre, numero, tipo, ruta}, ... ],
            "tag_tables": [ {nombre, numero, tipo, ruta}, ... ],
            "udts":       [ {nombre, numero, tipo, ruta}, ... ],
            "scanned_at": str (ISO 8601 UTC),
        }``

    Raises:
        ValueError: si ``plc_name`` falta o esta vacio.
        RuntimeError: si no hay proyecto activo o el PLC no existe.
    """
    _ = ts
    plc_name: str = args.get("plc_name", "")
    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    # Bloques: recorrido recursivo (espejo del legacy scanner).
    program_blocks = target_plc.get_program_blocks()
    blocks_list = _scan_block_group_recursive(program_blocks)

    # Tag tables: llamada SIN folder_path para que TIA recorra todo el
    # arbol recursivamente (Manual V1.2.1 §2.2.8).
    tag_tables_objs: list[Any] = []
    try:
        tag_tables_objs = list(target_plc.get_plc_tag_tables() or [])
    except Exception as e:
        _logger.warning(
            "No se pudieron listar PlcTagTables del PLC '%s': %s", plc_name, e
        )

    tag_tables_list: list[dict[str, Any]] = []
    for table in tag_tables_objs:
        nombre = _safe_get_table_name(table)
        if not nombre:
            continue
        ruta = _safe_get_block_path(table)
        tag_tables_list.append(
            BloquePLC(
                nombre=str(nombre),
                numero=0,
                tipo="OTHER",
                ruta=ruta,
            ).to_dict()
        )

    # UDTs (User Data Types): coleccion distinta de program_blocks.
    # Manual V1.2.1 §2.2.9: ``plc.get_user_data_types()`` devuelve la
    # raiz del arbol de UDTs (puede ser un grupo/carpeta anidada, asi
    # que reaprovechamos el walker recursivo). Es defensivo: si TIA no
    # expone el metodo (builds antiguos, proyecto vacio) o lanza una
    # excepcion, devolvemos ``udts=[]`` y dejamos que blocks/tag_tables
    # sigan devolviendo su contenido. El operario ve un tab UDTs vacio
    # en la SPA en vez de un error de scan completo.
    udts_list: list[dict[str, Any]] = []
    try:
        user_data_types = target_plc.get_user_data_types()
        udts_list = _scan_block_group_recursive(user_data_types)
    except Exception as e:
        _logger.warning(
            "No se pudieron listar User Data Types del PLC '%s': %s",
            plc_name,
            e,
        )
        udts_list = []

    return {
        "plc_name": plc_name,
        "blocks": blocks_list,
        "tag_tables": tag_tables_list,
        "udts": udts_list,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


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
        "compile_plc",
        # Comandos del ciclo de vida de la instancia TIA: gestionan su
        # propia conexión con el portal. No pueden ejecutarse DENTRO de
        # una transacción de proyecto (romperían el RCW / no tendría
        # sentido enlazarlos con operaciones de proyecto).
        "attach_portal",
        "open_new_portal",
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


COMMAND_REGISTRY: dict[str, Callable[[Any, Any, dict[str, Any]], Any]] = {
    # â”€â”€ Ciclo de vida del proyecto â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "attach_portal": _cmd_attach_portal,
    "open_new_portal": _cmd_open_new_portal,
    "open_project": _cmd_open_project,
    "save_project": _cmd_save_project,
    "close_project": _cmd_close_project,
    # â”€â”€ InspecciÃ³n â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "list_plcs": _cmd_list_plcs,
    "get_project_info": _cmd_get_project_info,
    "list_blocks": _cmd_list_blocks,
    "scan_blocks": _cmd_scan_blocks,
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
    # â”€â”€ Ops atomicos de las areas (registrados via load_extra_commands
    # al arrancar el worker): ``update_disp_comments_db_<hw>`` y
    # ``commit_devices_sync``. Ver ``core.infrastructure.tia.command_loader``.
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
    # Ruta del log: misma logica que ``zc_tray.log`` (ver
    # ``main_tray.py``), para que ambos acaben en la misma
    # carpeta (``<exe_dir>/logs/`` en produccion, ``<cwd>/logs/``
    # en dev) con el mismo override por env var y el mismo
    # fallback a AppData. El fallback al CWD que se ve mas abajo
    # es un ultimo recurso si ``set_logging`` rechaza el path
    # absoluto (caso muy raro, p.ej. permiso denegado de Siemens).
    from core.application.log_paths import resolve_log_dir
    _log_path = resolve_log_dir() / "worker_openness.log"
    try:
        ts.set_logging(path=str(_log_path), console=False)
    except Exception:
        # Fallback: path relativo al CWD (comportamiento original).
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
        # 4. Enganche al portal. Los comandos del ciclo de vida de la
        #    instancia TIA (attach_portal, open_new_portal) gestionan
        #    su propia conexiÃ³n: NO hacemos attach previo porque
        #    romperÃ­a precisamente el caso cold-start (open_new_portal
        #    sobre una instancia aÃºn no lanzada) y serÃ­a redundante
        #    para attach_portal (el handler rehace el attach).
        if command not in ("attach_portal", "open_new_portal"):
            # Usamos AnyUserInterface para que el filtro de instancias
            # COM acepte tanto TIA Portal con GUI activa como
            # instancias headless (manual V1.2.1 Â§2.4.2). De este modo
            # el proceso aislado puede reengancharse a la sesiÃ³n ya
            # abierta por el usuario sin colisionar con su estado.
            portal = ts.attach_portal(
                portal_mode=ts.Enums.PortalMode.AnyUserInterface
            )
            if portal is None:
                raise RuntimeError(
                    "Fallo crÃ­tico: attach_portal retornÃ³ una referencia nula. "
                    "AsegÃºrate de que TIA Portal estÃ¡ abierto."
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
