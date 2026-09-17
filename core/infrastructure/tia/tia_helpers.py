"""core.infrastructure.tia.tia_helpers - utilities defensivas del SDK .NET.

Helpers reutilizados por todos los handlers del subsistema TIA. Cada uno
encapsula una validacion o un try/except contra el wrapper
siemens_tia_scripting.pyd (acentos Latin-1, COM transients, etc.).

Categoria:
  - Validacion de argumentos y de proyecto/PLC activos.
  - Lectura tolerante a fallos (acentos, COM).
  - Deteccion de COM/RPC para re-attach defensivo.
  - Generacion de request_id y export masivo SD.

Funciones puras (sin estado). Se importan desde tia_handlers y desde
el dispatcher de tia_loop.
"""
from __future__ import annotations

import functools
import itertools
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from core.data.data_block_plc import DataBloquePLC
from core.infrastructure.log_web_bridge import WEB_LEVEL

if TYPE_CHECKING:
    from core.infrastructure.tia.tia_loop import SyncTIAClient

logger = logging.getLogger("zc.tia_loop")


# ---------------------------------------------------------------------------
# Validacion: proyecto activo y PLC existente
# ---------------------------------------------------------------------------
def _get_active_project(portal: Any) -> Any:
    """Devuelve el proyecto abierto del portal o lanza RuntimeError."""
    project = portal.get_project()
    if not project:
        raise RuntimeError(
            "No hay ningun proyecto abierto en TIA Portal. "
            "Ejecuta 'open_project' primero."
        )
    return project


def _find_plc(project: Any, plc_name: str) -> Any:
    """Resuelve el objeto Plc por nombre dentro del proyecto activo.

    Levanta ValueError si plc_name vacio; RuntimeError si no existe.
    """
    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    for plc in project.get_plcs():
        if _safe_get_plc_name(plc) == plc_name:
            return plc

    raise RuntimeError(
        f"No se encontro ningun PLC con el nombre '{plc_name}' "
        "en el proyecto activo."
    )


def _find_plc_tag_table(target_plc: Any, table_name: str) -> Any:
    """Resuelve una PlcTagTable por nombre en el PLC objetivo.

    Usa _safe_get_table_name para tolerar UnicodeDecodeError.
    Levanta RuntimeError si no existe.
    """
    if not table_name:
        raise ValueError("Se requiere el argumento 'table_name'.")
    for table in target_plc.get_plc_tag_tables():
        if _safe_get_table_name(table) == table_name:
            return table
    raise RuntimeError(
        f"Tabla '{table_name}' no encontrada en PLC."
    )


# ---------------------------------------------------------------------------
# Lectura tolerante: nombres y paths del wrapper .NET
# ---------------------------------------------------------------------------
def _safe_get_plc_name(plc: Any) -> str | None:
    """Lee el nombre de un PLC tolerando UnicodeDecodeError y COM."""
    try:
        return plc.get_name()
    except UnicodeDecodeError:
        return None
    except Exception:
        return None


def _safe_short_designation(plc: Any) -> str | None:
    """Lee ``ShortDesignation`` del PLC defensivamente.

    Devuelve None si: la property no existe, devuelve None/vacio, o el
    read lanza (COM, PermissionDenied, etc.).
    """
    getter = getattr(plc, "get_property", None)
    if getter is None:
        return None
    try:
        value = getter(name="ShortDesignation")
    except Exception:
        return None
    if value is None:
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    return s if s else None


def _safe_get_block_name(block: Any) -> str | None:
    """Lee el nombre de un bloque tolerando UnicodeDecodeError y COM."""
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


def _safe_get_block_path(block: Any) -> str:
    """Lee la ruta jerarquica de un bloque tolerando COM exceptions.

    Devuelve "" si falla (el bloque sigue siendo cacheado con su nombre).
    """
    try:
        if hasattr(block, "get_path"):
            return str(block.get_path())
        if hasattr(block, "Path"):
            return str(block.Path)
    except Exception:
        return ""
    return ""


def _safe_get_table_name(table: Any) -> str | None:
    """Lee el nombre de una PlcTagTable tolerando UnicodeDecodeError."""
    try:
        return table.get_name()
    except UnicodeDecodeError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Recursion sobre arbol de bloques
# ---------------------------------------------------------------------------
def _scan_block_group_recursive(group_or_blocks: Any) -> list[dict]:
    """Recorre recursivamente un grupo o coleccion de bloques -> DTOs dict.

    Returns:
        Lista de dicts con shape DataBloquePLC.to_dict(). Bloques con
        nombre inaccesible (UnicodeDecodeError) se omiten.
    """
    blocks_iter: list = []
    try:
        if hasattr(group_or_blocks, "get_blocks"):
            blocks_iter = list(group_or_blocks.get_blocks() or [])
        elif hasattr(group_or_blocks, "Blocks"):
            blocks_iter = list(group_or_blocks.Blocks or [])
        elif hasattr(group_or_blocks, "__iter__"):
            blocks_iter = list(group_or_blocks)
    except Exception:
        blocks_iter = []

    out: list[dict] = []
    for block in blocks_iter:
        nombre = _safe_get_block_name(block)
        if not nombre:
            continue
        ruta = _safe_get_block_path(block)
        tipo = DataBloquePLC.detect_tipo(nombre)
        match = re.match(r"^(DB|FB|FC|OB|UDT)(\d+)", nombre, re.IGNORECASE)
        numero = int(match.group(2)) if match else 0
        out.append(
            DataBloquePLC(
                nombre=str(nombre),
                numero=numero,
                tipo=tipo,
                ruta=ruta,
            ).to_dict()
        )

    groups: list = []
    try:
        if hasattr(group_or_blocks, "get_groups"):
            groups = list(group_or_blocks.get_groups() or [])
        elif hasattr(group_or_blocks, "Groups"):
            groups = list(group_or_blocks.Groups or [])
    except Exception:
        groups = []

    for sub in groups:
        out.extend(_scan_block_group_recursive(sub))

    return out


# ---------------------------------------------------------------------------
# Re-attach defensivo: deteccion de COM/RPC disconnect
# ---------------------------------------------------------------------------
def _is_com_disconnect(exc: BaseException) -> bool:
    """Heuristica: parece que TIA Portal se cerro y hay que re-attachar.

    Detectar esto de forma exacta no es viable (depende del build del
    wrapper, de si murio el subproceso o solo el RCW quedo invalido).
    Aceptamos falsos positivos: re-attachar de mas es mejor que dejar
    al loop usando un portal muerto.
    """
    name = type(exc).__name__
    if "COM" in name or "RPC" in name:
        return True
    if hasattr(exc, "hresult"):
        return True
    return False


def _try_reattach(client: "SyncTIAClient") -> bool:
    """Intenta re-attachar al portal si esta muerto.

    Si ``client._wrapper`` ya responde a ``get_process_id()``, retorna
    True sin tocar nada. Si falla o no hay wrapper, intenta
    ``ts.attach_portal(AnyUserInterface)`` y deja el wrapper listo.
    """
    if client._wrapper is not None:  # noqa: SLF001
        try:
            client._wrapper.get_process_id()
            return True
        except Exception:
            client.attach_wrapper(None)
    ts = client._ts  # noqa: SLF001
    if ts is None:
        return False
    try:
        new_portal = ts.attach_portal(
            portal_mode=ts.Enums.PortalMode.AnyUserInterface,
        )
    except Exception as exc:
        logger.warning(
            "re-attach fallo: %s: %s", type(exc).__name__, exc,
        )
        return False
    if new_portal is None:
        logger.warning("re-attach fallo: attach_portal retorno None.")
        return False
    try:
        new_portal.get_process_id()
    except Exception as exc:
        logger.warning(
            "re-attach: get_process_id fallo tras attach: %s: %s",
            type(exc).__name__, exc,
        )
        client.attach_wrapper(None)
        return False
    client.attach_wrapper(new_portal)
    logger.info("re-attach OK.")
    return True


# ---------------------------------------------------------------------------
# Request IDs (correlacion submit_and_wait / resp_q)
# ---------------------------------------------------------------------------
_request_id_counter = itertools.count(1)


def _next_request_id() -> int:
    """IDs unicos monotonos para correlar request/response."""
    return next(_request_id_counter)


# ---------------------------------------------------------------------------
# Helpers de export
# ---------------------------------------------------------------------------
def _ensure_target_dir(target_dir: str) -> Path:
    """Valida target_dir y devuelve la ruta resuelta (crea el dir si falta).

    Usado por export_blocks_sd, export_udts_sd, export_plc_tags_xml.
    """
    if not target_dir:
        raise ValueError("Se requiere el argumento 'target_dir'.")
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)
    return target_path


def _export_objects_sd(
    target_plc: Any,
    target_path: Path,
    collection_key: str,
) -> dict:
    """Exporta una coleccion de objetos TIA (Bloques o UDTs) a .s7dcl.

    Args:
        collection_key: 'program_blocks' | 'user_data_types'.

    Returns:
        ``{"exported_to": str, "count": int}``.

    TIA Portal V17+ emite archivos .s7dcl cuando se pasa
    ``export_format='SimaticSD'``.
    """
    if collection_key == "program_blocks":
        objects = target_plc.get_program_blocks()
    elif collection_key == "user_data_types":
        objects = target_plc.get_user_data_types()
    else:
        raise ValueError(
            f"collection_key desconocido: '{collection_key}'. "
            "Use 'program_blocks' o 'user_data_types'."
        )

    count = 0
    for obj in objects:
        obj.export(
            target_directory_path=str(target_path),
            export_format="SimaticSD",
            keep_folder_structure=True,
        )
        count += 1

    return {"exported_to": str(target_path), "count": count}


# ---------------------------------------------------------------------------
# Decorador de trazabilidad para handlers OT (Zona D, paso 1)
# ---------------------------------------------------------------------------
def log_ot_command(
    name: str, level: int = WEB_LEVEL
) -> Callable[..., Any]:
    """Decorador: emite entry/exit alrededor de cada handler OT.

    Patrón instrumentación estándar: log al entrar + log al salir. NO
    captura excepciones: el caller (``_execute_one``) ya las gestiona
    con ``logger.warning`` + traceback, duplicar sería ruido.

    Args:
        name: identificador del comando OT (mismo nombre que el
            registro en el ``COMMAND_REGISTRY``). Lo usa el operario
            para correlacionar logs y comparar con el árbol de
            comandos de la SPA.
        level: nivel de logging para los mensajes entry/exit. Default
            ``WEB_LEVEL`` (25) -> mensaje llega a archivo + consola web
            (verde al cerrar). Si se pasa ``logging.DEBUG`` (10),
            el mensaje solo va al archivo (no satura la web cuando el
            handler se llama muchas veces por sync, p.ej. export_block
            por cada DB de dispositivos).

    Output (en el nivel configurado):
      - entry: ``OT[{name}] args={resumen_args}``.
      - exit OK: ``OT[{name}] OK en {ms}ms ({resumen_result})``.
    """
    def deco(handler: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(handler)
        def wrapper(args: dict, tia_client: Any) -> dict:
            logger.log(level, f"OT[{name}] args={_sanitize_args(args)}")
            t0 = time.monotonic()
            result = handler(args, tia_client)
            ms = (time.monotonic() - t0) * 1000
            logger.log(
                level,
                f"OT[{name}] OK en {ms:.0f}ms "
                f"({_summarize_result(result)})",
            )
            return result
        return wrapper
    return deco


def _sanitize_args(args: dict) -> str:
    """Resumen corto de los args: keys + tipo/longitud (sin valores grandes).

    Formato: ``"plc_name='ZC_PLC_STD', blocks=[3], options={2 keys}"``.
    """
    if not args:
        return "{}"
    parts: list[str] = []
    for k, v in args.items():
        if isinstance(v, (str, int, float, bool, type(None))):
            parts.append(f"{k}={v!r}")
        elif isinstance(v, list):
            parts.append(f"{k}=[{len(v)}]")
        elif isinstance(v, dict):
            parts.append(f"{k}={{{len(v)} keys}}")
        else:
            parts.append(f"{k}=<{type(v).__name__}>")
    return ", ".join(parts)


def _summarize_result(result: dict) -> str:
    """Resumen corto del resultado de un handler.

    Formato:
      - ``ok=False``: ``ERROR=<mensaje truncado>``.
      - ``ok=True``: lista de campos principales con su longitud o
        string truncado a 40 chars (para no inundar el log).
      - Otros tipos: nombre de la clase.
    """
    if not isinstance(result, dict):
        return type(result).__name__
    if result.get("ok") is False:
        return f"ERROR={str(result.get('error', '?'))[:80]}"
    parts: list[str] = []
    for k, v in result.items():
        if k == "ok":
            continue
        if isinstance(v, list):
            parts.append(f"{k}=[{len(v)}]")
        elif isinstance(v, dict):
            parts.append(f"{k}={{{len(v)} keys}}")
        else:
            parts.append(f"{k}={str(v)[:40]}")
    return ", ".join(parts) or "ok"
