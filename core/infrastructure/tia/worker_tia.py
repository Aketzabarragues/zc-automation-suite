"""Subproceso OT para TIA Portal Openness. Ejecutado por TIAProcessGateway.

Hay dos modos de uso, según los argumentos:
  - main(): un solo comando por stdin/stdout y termina (modo 1-shot).
  - main_persistent_loop(): se queda vivo leyendo comandos hasta EOF
    o "exit" (modo persistente, usado por el gateway web).

Reglas de I/O del modo 1-shot:
- STDIN: un JSON con 'command' (str) y 'args' (dict).
- STDOUT: una línea JSON final con {'ok': True, 'result': ...} o {'ok': False, 'error': ...}.
- STDERR: logs y trazas de excepción.

Reglas de I/O del modo persistente: ver main_persistent_loop.

Los handlers del COMMAND_REGISTRY reciben (portal, ts, args). Si
necesitan proyecto abierto lo extraen con _get_active_project(portal).
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NoReturn

from core.models.bloque_plc import BloquePLC

# Forzar UTF-8 en los streams del worker.
# El worker es un subproceso de TIAProcessGateway (v�a
# asyncio.create_subprocess_exec en Windows con CreateProcess).
# La reconfigure de main.py NO se hereda al subproceso, as� que
# lo hacemos tambi�n aqu�. Sin esto, Pythonnet intenta convertir
# strings de TIA Portal (Latin-1) a Python UTF-8 y revienta con
# "utf-8 codec can't decode byte 0xe1 in position N".
# Reconfiguraci�n de I/O a UTF-8. Vive aqu� (no a nivel de m�dulo) para no
# romper a quien importe este m�dulo (p. ej. tests que usan capture de pytest).
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
        if _safe_get_plc_name(plc) == plc_name:
            return plc

    raise RuntimeError(
        f"No se encontró ningún PLC con el nombre '{plc_name}' en el proyecto activo."
    )


def _safe_get_plc_name(plc) -> str | None:
    """Lee el nombre de un Plc tolerando errores de encoding.

    Algunos PLCs / tablas del proyecto tienen nombres con
    caracteres no-ASCII (Latin-1, p.ej. acentos). Pythonnet
    intenta convertir el .Name a Python str y revienta con
    UnicodeDecodeError. Como nosotros solo necesitamos comparar
    contra nombres ASCII, devolvemos None en ese caso (la
    comparación fallará y se tratará como "no es la que
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
    fallar la conversión a Python str via Pythonnet. Como
    nuestra tabla objetivo siempre tiene nombre ASCII, saltamos
    cualquier tabla que no se pueda decodificar.
    """
    try:
        return table.get_name()
    except UnicodeDecodeError:
        return None


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
    """Abre un proyecto TIA Portal desde una ruta absoluta. Manual §2.4.3.

    PRECONDICIÓN: el portal ya está conectado (vía ``attach_portal`` o
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


# attach_portal se gestiona dentro de main_persistent_loop, no aqu�.
# No lo a�adas al COMMAND_REGISTRY.


def _cmd_open_new_portal(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Cold start: lanza una instancia NUEVA de TIA Portal y abre proyecto.

    Sigue el Manual V1.2.1 §2.4.1:
      1. ``ts.open_portal(portal_mode=...)`` → instancia del portal.
      2. ``portal.open_project(project_file_path=...)`` → abre proyecto.

    Args:
        project_file_path: Ruta absoluta al .apxx.

    Returns:
        ``True`` si el portal nuevo se creó con éxito.
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
            "Fallo crítico: open_portal retornó None."
        )
    new_portal.open_project(project_file_path=project_file_path)
    return True


def _cmd_save_project(portal: Any, ts: Any, args: dict[str, Any]) -> None:
    """Guarda los cambios pendientes del proyecto activo (manual §2.37.2)."""
    _ = ts
    project = _get_active_project(portal)
    project.save()


def _cmd_close_project(portal: Any, ts: Any, args: dict[str, Any]) -> None:
    """Cierra el proyecto activo (manual §2.37.3).

    ADVERTENCIA CR�?TICA: project.close() destruye permanentemente todos
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


def _cmd_ping(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Verifica si la conexi�n con TIA Portal sigue activa.

    Implementaci�n: ``portal.get_process_id()`` (secci�n 2.5.1 del
    manual de Siemens). Si retorna un PID, ``ok=True`` con el PID.
    Si lanza excepci�n COM/RPC (TIA cerrado), ``ok=False``.

    Primitiva del heartbeat (PR 4) y de la reconexi�n manual (PR 6)
    del design doc del worker persistente
    (``_plan/12_worker_persistent_design.md`` �3.3).

    Returns:
        ``{"ok": True, "pid": <int>}`` si el portal responde.
        ``{"ok": False, "error": "..."}`` si no responde o no hay portal.
    """
    _ = ts
    if portal is None:
        return {"ok": False, "error": "No hay portal attached"}
    try:
        pid = portal.get_process_id()
        return {"ok": True, "pid": int(pid)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _cmd_get_project_info(portal: Any, ts: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Devuelve propiedades b�sicas del proyecto TIA activo como primitivos.

    Lee un set acotado de propiedades del proyecto que son �tiles para
    que la SPA muestre al operario a qu� proyecto est� enganchado. NO
    devuelve objetos nativos TIA (siempre primitivos, por AGENTS.md �Datos).

    Si una propiedad lanza al leerla (p. ej. PermissionDenied o
    EncodingError), se omite del payload en lugar de tumbar el handler:
    la SPA recibe un dict parcial y renderiza solo lo disponible.

    Args:
        portal: Instancia de TIA Portal ya enganchada.
        ts: M�dulo ``siemens_tia_scripting`` (no se usa directamente;
            el handler opera sobre el ``portal`` ya inicializado).
        args: Argumentos del comando (no se usan; no se requiere
            configuraci�n del caller).

    Returns:
        ``dict`` con al menos la key ``name``. Opcionalmente tambi�n
        ``path``, ``author``, ``creation_time``, ``last_modified``,
        ``last_modified_by`` y ``version``, omitidas si no est�n
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

    # Propiedades opcionales. Si una no est� activa o falla, se omite.
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
        # Normalizar a primitivo: datetime/DateTime .NET ? ISO 8601 string.
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        result[out_key] = value

    return result


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


def _export_objects_sd(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta una colección de objetos TIA (Bloques o UDTs) a archivos .s7dcl.

    Espera en args: plc_name, target_dir, collection_key
    ('program_blocks' | 'user_data_types'). `ts` se inyecta desde
    `_load_siemens_wrapper()` para acceder a los enumeradores nativos
    (ts.Enums.ExportFormats.SimaticSD, etc.).

    Nota de formato: TIA Portal V21 emite archivos .s7dcl
    (Simatic Source Documents) cuando se solicita ``export_format=SimaticSD``.
    El sufijo ``.s7dcl`` es el canónico a partir de V17; el ``.scl``
    histórico queda obsoleto en esta arquitectura.
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
        # forzar la exportación en formato fuente SimaticSD (.s7dcl) sin
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

    Itera sobre plc.get_plc_tag_tables() (manual §2.2.8) y exporta cada
    tabla con export_format=SimaticML, export_options=WithDefaults y
    keep_folder_structure=True (preserva jerarquía de grupos del PLC).

    Args:
        args: Dict con:
            - ``plc_name`` (str, requerido): nombre del PLC destino.
            - ``target_dir`` (str, requerido): directorio donde escribir
              los XML exportados.
            - ``table_names`` (list[str], opcional): filtro de tablas a
              exportar. Si se pasa y no es ``None``, SOLO se exportan las
              tablas cuyo ``get_name()`` esté en la lista. Si es ``None``
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


def _cmd_import_blocks_sd(portal: Any, ts: Any, args: dict[str, Any]) -> bool:
    """Importa bloques de programa en formato Simatic Source Documents (.s7dcl) desde el disco al PLC (manual §2.2.23).

    TIA Portal asume que el directorio existe; si no, el CLR lanza una
    excepción grave. Por eso validamos con os.path.isdir() ANTES de invocar
    el método COM.

    Nota: el nombre del comando refleja la convención actual (.s7dcl /
    SimaticSD); internamente el wrapper sigue invocando
    ``target_plc.import_blocks`` porque la API de Siemens mantiene
    estable el nombre del método independientemente de la extensión
    del archivo.
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

    El escaner silenci� COM exceptions menores al leer la ruta de un
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
    # arbol recursivamente (Manual V1.2.1 �2.2.8).
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
    # Manual V1.2.1 �2.2.9: ``plc.get_user_data_types()`` devuelve la
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


# ??? COMMAND_REGISTRY ??????????????????????????????????????????????????????
# attach_portal y detach_portal se gestionan dentro de
# main_persistent_loop, no aqu�. No los a�adas al registry.


def _cmd_export_tag_table(portal: Any, ts: Any, args: dict[str, Any]) -> str:
    """Exporta una �nica PlcTagTable como XML SimaticML. Manual �2.10.5 / �2.28.3."""
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
    """Actualiza el valor de una PlcUserConstant. Manual §2.28."""
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
    """Renombra una PlcUserConstant. Manual §2.28."""
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
    """Borra una PlcUserConstant. Manual §2.34.4. snake_case: constant.delete()."""
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
        "compile_plc",
        # Comandos del ciclo de vida de la instancia TIA: gestionan su
        # propia conexi�n con el portal. No pueden ejecutarse DENTRO de
        # una transacci�n de proyecto (romper�an el RCW / no tendr�a
        # sentido enlazarlos con operaciones de proyecto).
        "attach_portal",
        "open_new_portal",
    }
)


def _cmd_execute_transactional_batch(
    portal: Any, ts: Any, args: dict[str, Any]
) -> dict[str, Any]:
    """Ejecuta varios comandos bajo una sola transacci�n de TIA Portal.

    Si cualquier handler falla se hace rollback de toda la cadena y se
    lanza RuntimeError con el paso que rompi�. Captura el retorno de
    cada paso en ``details`` para que la IT vea los resultados intermedios.
    """
    _ = ts
    project = _get_active_project(portal)
    undo_text: str = args.get("undo_text", "Operación por Lote")
    operations: list[dict[str, Any]] = args.get("operations", [])

    if not operations:
        raise ValueError("La lista de operaciones está vacía.")

    # Iniciar transacción nativa (manual §2.37.27).
    project.start_transaction(undo_text=undo_text, dialog_text=undo_text)

    # Acumulador de resultados intermedios. Cada paso exitoso añade su
    # retorno nativo (bool, str, list, dict, etc.) SIN coerción, para
    # preservar la semántica exacta del wrapper de Siemens.
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
                    f"El comando '{cmd}' está prohibido dentro de un lote "
                    "transaccional."
                )

            # Ejecutar el handler atómico reinyectando portal y ts,
            # capturando su valor de retorno para inspección posterior.
            step_result: Any = COMMAND_REGISTRY[cmd](portal, ts, cmd_args)

            results_list.append(
                {"step": idx + 1, "command": cmd, "result": step_result}
            )

        # Confirmar transacción si no hubo errores (manual §2.37.28).
        project.end_transaction(rollback=False)

        return {
            "success": True,
            "operations_executed": len(operations),
            "details": results_list,
        }

    except Exception as e:
        # Reversión garantizada ante excepciones (manual §2.37.28).
        # Silenciamos fallos secundarios del rollback para no enmascarar
        # la causa raíz original.
        try:
            project.end_transaction(rollback=True)
        except Exception:
            pass
        # len(results_list) marca el ÚLTIMO paso exitoso; el fallo ocurre
        # en resultados_list + 1 (o en validación previa, donde len=0).
        #
        # Incluimos los ``args`` de la op que falló (truncados a 500
        # chars) para diagnóstico. Sin esto, el operario ve
        # ``Lote abortado en el paso 72 ('update_user_constant_value')``
        # pero no sabe qué ``N_MAX`` ni qué valor es el problemático.
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
    # ?? Ciclo de vida del proyecto ????????????????????????????????????????
    "open_new_portal": _cmd_open_new_portal,
    "open_project": _cmd_open_project,
    "save_project": _cmd_save_project,
    "close_project": _cmd_close_project,
    # ── Inspección ─────────────────────────────────────────────
    "list_plcs": _cmd_list_plcs,
    "get_project_info": _cmd_get_project_info,
    "list_blocks": _cmd_list_blocks,
    "scan_blocks": _cmd_scan_blocks,
    # ── Mutación / compilación ────────────────────────────────────
    "compile_plc": _cmd_compile_plc,
    # ── Exportación masiva Simatic Source Documents (.s7dcl) ──────────
    "export_blocks_sd": _cmd_export_blocks_sd,
    "export_udts_sd": _cmd_export_udts_sd,
    # ── Exportación masiva SimaticML (XML) ───────────────────────────────
    "export_plc_tags_xml": _cmd_export_plc_tags_xml,
    # ── Importación masiva desde disco (cierre del ciclo I/O) ─────────────
    "import_blocks_sd": _cmd_import_blocks_sd,
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
    # ── Health check (PR 1 worker persistente) ───────────────────────
    # Primitiva del heartbeat (PR 4) y de la reconexión manual (PR 6).
    # NO requiere proyecto abierto: detecta si el portal TIA sigue vivo
    # via ``portal.get_process_id()``.
    "ping": _cmd_ping,
    # ── Ops atomicos de las areas (registrados via load_extra_commands
    # al arrancar el worker): ``update_disp_comments_db_<hw>`` y
    # ``commit_devices_sync``. Ver ``core.infrastructure.tia.command_loader``.
}


# ??? Punto de extensi�n: comandos aportados por las �reas ????????????????
# Las �reas (Bounded Contexts) registradas en ``areas/*/`` aportan
# comandos transaccionales adicionales al ``COMMAND_REGISTRY`` mediante
# ``AreaSpec.contributes_tia_commands``. Dichos handlers corren
# DENTRO del proceso del worker, bajo la misma transacci�n at�mica
# que cualquier otro comando del lote, pero NO importan
# ``siemens_tia_scripting`` directamente (cumplen la regla
# ``.clinerules`` �1: el worker es el �nico proceso que importa la DLL).
#
# Esta llamada se ejecuta una sola vez al import del m�dulo. Como
# Python cachea los imports, est� OK que se invoque varias veces
# (los handlers se machacan por nombre, no se duplican).
#
# Importaci�n al final del m�dulo para evitar ciclo con ``AreaRegistry``:
#   worker_tia ? command_loader ? AreaRegistry ? areas.<area>
#     ? extra_commands ? (lazy) worker_tia
# Cuando este bloque se ejecuta, ``COMMAND_REGISTRY`` ya est�
# completamente definido, por lo que las �reas pueden mutarlo in-place.
from core.infrastructure.tia.command_loader import load_extra_commands

load_extra_commands(COMMAND_REGISTRY)




def _load_siemens_wrapper() -> Any:
    """Carga el wrapper nativo de Siemens. En producci�n lo inyecta desde _MEIPASS; en dev, del venv."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        # PyInstaller onefile: a�adimos la ruta del bundle a sys.path
        # y al PATH del sistema para que las DLLs nativas se localicen.
        if meipass not in sys.path:
            sys.path.insert(0, meipass)

        os.environ["PATH"] = meipass + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(meipass)

        import siemens_tia_scripting as ts
        return ts

    import siemens_tia_scripting as ts
    return ts

def _is_com_disconnect(exc: BaseException) -> bool:
    """Heur�stica: parece que TIA Portal se cerr� y hay que re-attachar.

    Detectar esto de forma exacta no es viable (depende del build del
    wrapper, de si muri� el subproceso o solo el RCW qued� inv�lido).
    Aceptamos falsos positivos: re-attachar de m�s es mejor que dejar
    al loop usando un portal muerto.
    """
    name = type(exc).__name__
    if "COM" in name or "RPC" in name:
        return True
    if hasattr(exc, "hresult"):
        return True
    return False


def main_persistent_loop() -> None:
    """Loop principal del worker OT persistente.

    El subproceso se invoca con ``--worker-persistent`` y se queda
    vivo entre comandos. Lee JSON de stdin l�nea a l�nea, lo despacha
    al ``COMMAND_REGISTRY`` y escribe la respuesta con el mismo
    ``id`` a stdout.

    Estados: idle (sin portal) ? connected (tras attach_portal) ?
    idle (tras detach_portal). El subproceso no muere entre comandos.

    ``attach_portal`` y ``detach_portal`` se gestionan aqu� (no en
    el ``COMMAND_REGISTRY``) porque necesitan reasignar la variable
    local ``portal``.
    """
    # 1. Carga del wrapper nativo.
    try:
        ts = _load_siemens_wrapper()
    except (ImportError, FileNotFoundError) as e:
        _write_json_and_exit(
            {"ok": False, "error": f"Fallo al cargar 'siemens_tia_scripting': {e}"},
            code=1,
        )
        return  # _write_json_and_exit es NoReturn, pero el type checker lo agradece

    # 2. Estado inicial: idle. El worker arranca sin portal; el gateway
    # le env�a un attach_portal cuando el operario pulse "Conectar".
    portal: Any = None

    # 2.5 Signal "ready_idle" (id=0, reservado). El gateway lo lee antes
    # de enviar el primer comando para saber que el subproceso est� vivo.
    try:
        ready_payload: dict[str, Any] = {
            "id": 0,
            "ok": True,
            "result": "ready_idle",
        }
        sys.stdout.write(json.dumps(ready_payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception as exc:
        # Si no podemos escribir el ready (e.g. stdout cerrado), el
        # gateway lo detectara por timeout. No morimos.
        sys.stderr.write(
            f"[WORKER READY ERROR] {type(exc).__name__}: {exc}\n"
        )
        sys.stderr.flush()

    # 3. Helpers locales para el state machine.

    def _try_reattach() -> bool:
        """Re-attacha el portal TIA tras un cierre de TIA a media sesi�n.

        Devuelve True si el portal queda vivo, False en caso contrario.
        Limitaci�n conocida: si el operario acaba de pulsar "Desconectar"
        y el heartbeat lee el portal justo en ese momento, este re-attach
        puede revivir un portal que el operario quer�a desconectar. El
        caso es raro y de bajo impacto (basta un re-disconnect para
        arreglarlo).
        """
        nonlocal portal
        if portal is not None:
            try:
                portal.get_process_id()
                return True
            except Exception:
                portal = None
        try:
            portal = ts.attach_portal(
                portal_mode=ts.Enums.PortalMode.AnyUserInterface
            )
        except Exception:
            portal = None
            return False
        if portal is None:
            return False
        try:
            portal.get_process_id()
            return True
        except Exception:
            portal = None
            return False

    def _handle_attach(args: dict[str, Any]) -> dict[str, Any]:
        """Conecta con TIA Portal. Devuelve ``{"pid": <int>}`` o ``{"error": "..."}``.

        ``args["mode"]`` puede ser ``"WithGraphicalUserInterface"`` o
        ``"WithoutGraphicalUserInterface"``. Default: con GUI.
        """
        nonlocal portal
        if portal is not None:
            # Ya hay portal attached. Devolvemos el PID actual para
            # que el gateway confirme el estado.
            try:
                pid = int(portal.get_process_id())
                return {"pid": pid}
            except Exception:
                # El portal est� vivo pero get_process_id falla
                # (TIA cerrada mid-session). Forzamos detach y re-attach.
                try:
                    portal.detach()
                except Exception:
                    pass
                portal = None
        mode_name = (args or {}).get("mode", "WithGraphicalUserInterface")
        # Resoluci�n del enum por nombre para no acoplarnos al espacio
        # ts.Enums.PortalMode (no expuesto en todos los builds).
        try:
            portal_mode = getattr(
                ts.Enums.PortalMode, mode_name
            )
        except AttributeError:
            return {
                "error": (
                    f"PortalMode invalido: {mode_name!r}. "
                    "Use 'WithGraphicalUserInterface' o "
                    "'WithoutGraphicalUserInterface'."
                )
            }
        try:
            new_portal = ts.attach_portal(portal_mode=portal_mode)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        if new_portal is None:
            return {
                "error": (
                    "attach_portal retorno None. �Esta TIA Portal "
                    "abierto? �El usuario pertenece al grupo Openness?"
                )
            }
        portal = new_portal
        try:
            pid = int(portal.get_process_id())
        except Exception:
            # Attach OK pero el PID no se puede leer (TIA en estado raro).
            pid = None
        return {"pid": pid}

    def _handle_detach(args: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        """Desconecta de TIA Portal. Idempotente.

        Si no hay portal attached devuelve ``{"detached": false}``.
        Si lo hay llama ``portal.detach()`` (best-effort: si falla por
        TIA cerrada se loguea como WARNING) y devuelve ``{"detached": true}``.
        """
        nonlocal portal
        if portal is None:
            return {"detached": False}
        try:
            portal.detach()
        except Exception as exc:
            # TIA ya cerrada o RCW stale. Logueamos para que el operario
            # pueda correlacionarlo con un TIA que se cerr� de golpe.
            _logger.warning(
                "detach_portal best-effort fallo: %s: %s",
                type(exc).__name__,
                exc,
            )
        portal = None
        return {"detached": True}

    # 4. Loop principal.
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                # stdin cerrado (el IT cerr� el pipe). Salida limpia.
                break
            stripped = line.strip()
            if not stripped:
                # L�nea vac�a: seguimos leyendo.
                continue
            payload = json.loads(stripped)
            request_id = payload.get("id", 0)
            command = payload.get("command", "")
            args = payload.get("args", {}) or {}

            if command == "exit":
                break

            if command == "attach_portal":
                result = _handle_attach(args)
                ok = "error" not in result
                response = (
                    {"id": request_id, "ok": ok, "result": result}
                    if ok
                    else {"id": request_id, "ok": False, "error": result["error"]}
                )
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                continue
            if command == "detach_portal":
                result = _handle_detach(args)
                response = {"id": request_id, "ok": True, "result": result}
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                continue

            # El resto de comandos necesitan portal attached. Si no
            # hay, respondemos con un error claro en vez de dejar
            # que el handler reviente con NoneType.
            if portal is None:
                response = {
                    "id": request_id,
                    "ok": False,
                    "error": (
                        "Portal no attached. Conectar primero."
                    ),
                }
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                continue

            # Re-attach defensivo: si el portal muri� desde el �ltimo
            # comando, intentamos re-attachar una vez antes de fallar.
            try:
                portal.get_process_id()
            except Exception:
                if not _try_reattach():
                    response = {
                        "id": request_id,
                        "ok": False,
                        "error": (
                            "Portal no disponible y re-attach fallo"
                        ),
                    }
                    sys.stdout.write(
                        json.dumps(response, ensure_ascii=False) + "\n"
                    )
                    sys.stdout.flush()
                    continue

            try:
                handler = COMMAND_REGISTRY.get(command)
                if handler is None:
                    raise ValueError(f"Comando desconocido: {command!r}")
                result = handler(portal, ts, args)
                response = {"id": request_id, "ok": True, "result": result}
            except Exception as exc:
                # Si parece COM/RPC marcamos el portal como None para
                # forzar re-attach en el siguiente comando. Si es un
                # error de aplicaci�n (e.g. args inv�lidos) lo dejamos vivo.
                if _is_com_disconnect(exc):
                    portal = None
                response = {
                    "id": request_id,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

            # Siempre con id (para que el reader del gateway matchee)
            # y siempre con flush (para no bloquear la task de lectura).
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            # Error parseando JSON o leyendo stdin. Salimos del loop;
            # el gateway detectar� EOF y marcar� el estado como error.
            sys.stderr.write(
                f"[WORKER LOOP ERROR] {type(exc).__name__}: {exc}\n"
            )
            sys.stderr.flush()
            break

    # 5. Limpieza al salir. Si quedaba portal attached lo soltamos
    # (best-effort; si falla el OS libera al morir el subproceso).
    if portal is not None:
        try:
            portal.detach()
        except Exception:
            pass


def main() -> None:
    # -- Dispatch del modo persistente (PR 2/3) --
    # Si el subproceso se invoca con --worker-persistent (modo web,
    # gateway con persistent=True), entramos en el loop persistente:
    # 1 attach al inicio + N comandos por stdin/stdout. La implementacion
    # completa del loop viene en PR 3 del refactor
    # (_plan/13_persistent_worker_impl.md); por ahora es un
    # NotImplementedError con la referencia al plan para que un caller
    # que active el flag por error reciba un mensaje accionable.
    if "--worker-persistent" in sys.argv:
        main_persistent_loop()
        return

    # 1. Carga dinámica tardía del wrapper nativo (Sección 1.7.1 V1.2.1).
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
    # ?? M�tricas de timing (observabilidad PR, no cambian comportamiento) ??
    # time.monotonic() es inmune a saltos NTP. Cada t_X_end se inicializa
    # a None para distinguir "no se ejecut�" (null en el JSON) de
    # "se ejecut� en 0ms" (0 entero). Los timings se emiten a stderr al
    # final del bucle, en el finally, para capturar tambi�n los errores.
    t_load_dll_start: float | None = None
    t_load_dll_end: float | None = None
    t_attach_start: float | None = None
    t_attach_end: float | None = None
    t_handler_start: float | None = None
    t_handler_end: float | None = None
    t_detach_start: float | None = None
    t_detach_end: float | None = None
    try:
        # 1'. Marca de carga del wrapper nativo. La carga efectiva
        #     sucede arriba (l�nea ~1175), pero para que las cuatro
        #     mediciones sumen coherentemente al total del worker
        #     partimos de aqu�: el handler ya tiene `ts` enlazado
        #     cuando entra a este bloque. En producci�n el grueso
        #     del coste de import .pyd ya est� pagado; a�n as� lo
        #     medimos para detectar regresiones en frozen vs dev.
        t_load_dll_start = time.monotonic()
        t_load_dll_end = time.monotonic()

        # 4. Enganche al portal. Los comandos del ciclo de vida de la
        #    instancia TIA (attach_portal, open_new_portal) gestionan
        #    su propia conexión: NO hacemos attach previo porque
        #    rompería precisamente el caso cold-start (open_new_portal
        #    sobre una instancia aún no lanzada) y sería redundante
        #    para attach_portal (el handler rehace el attach).
        if command not in ("attach_portal", "open_new_portal"):
            # Usamos AnyUserInterface para que el filtro de instancias
            # COM acepte tanto TIA Portal con GUI activa como
            # instancias headless (manual V1.2.1 §2.4.2). De este modo
            # el proceso aislado puede reengancharse a la sesión ya
            # abierta por el usuario sin colisionar con su estado.
            t_attach_start = time.monotonic()
            portal = ts.attach_portal(
                portal_mode=ts.Enums.PortalMode.AnyUserInterface
            )
            t_attach_end = time.monotonic()
            if portal is None:
                raise RuntimeError(
                    "Fallo crítico: attach_portal retornó una referencia nula. "
                    "Asegúrate de que TIA Portal está abierto."
                )

        # 5. Despacho al handler. La extracción del proyecto es responsabilidad
        #    del propio handler (vía _get_active_project) si lo requiere.
        handler = COMMAND_REGISTRY[command]
        t_handler_start = time.monotonic()
        result = handler(portal, ts, args)
        t_handler_end = time.monotonic()

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
            t_detach_start = time.monotonic()
            try:
                portal.detach()
            except Exception as e:
                sys.stderr.write(f"[WORKER DETACH ERROR] {e}\n")
            t_detach_end = time.monotonic()

        # 7. Emisi�n de timings como JSON estructurado a stderr.
        #    stderr y NO stdout: stdout es el canal del JSON response
        #    que parsea el gateway. Mezclar ah� romper�a la
        #    comunicaci�n. Cada campo null = fase no ejecutada
        #    (p.ej. attach_portal_ms es null para attach_portal /
        #    open_new_portal, que no hacen attach previo).
        def _ms(end, start):
            if end is None or start is None:
                return None
            return round((end - start) * 1000)

        timings = {
            "event": "worker_timing",
            "command": command,
            "load_dll_ms": _ms(t_load_dll_end, t_load_dll_start),
            "attach_portal_ms": _ms(t_attach_end, t_attach_start),
            "handler_ms": _ms(t_handler_end, t_handler_start),
            "detach_ms": _ms(t_detach_end, t_detach_start),
        }
        sys.stderr.write(f"[WORKER TIMING] {json.dumps(timings)}\n")


if __name__ == "__main__":
    main()
