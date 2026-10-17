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

import itertools
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from core.data.data_block_plc import DataBloquePLC
from core.helpers.tia.tia_block_classifier import classify_block
from core.infrastructure.log.log_web_bridge import WEB_LEVEL

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
def _extract_extended_properties(block: Any) -> dict[str, Optional[str]]:
    """Lee las 6 propiedades extendidas del bloque via ``get_properties()``.

    El manual TIA (§2.29.11) confirma que ``ProgramBlock.get_properties()``
    existe pero NO documenta la shape exacta del retorno: puede ser un
    objeto con atributos directos (``props.Title``), un dict
    (``props["Title"]``), o un objeto con propiedades anidadas. Esta
    implementacion es defensiva y prueba multiples paths antes de rendirse.

    Estrategia de acceso por propiedad:
      1. ``getattr(props, candidate, None)`` (objeto con atributos).
      2. ``props.get(candidate, None)`` si ``props`` expone un ``get``
         callable (dict-like o atributo custom).

    Si ``get_properties()`` lanza, devuelve todos los campos a ``None``
    pero loggea el tipo de excepcion en debug para que el operario sepa
    que ha pasado. En la primera llamada de la sesion loggea ademas las
    claves disponibles para guiar el siguiente commit de mapeo.

    Keys (snake_case): ``title``, ``comment``, ``author``, ``version``,
    ``programming_language``, ``memory_layout``.
    """
    fields = ("title", "comment", "author", "version",
              "programming_language", "memory_layout")
    empty: dict[str, Optional[str]] = {k: None for k in fields}

    getter = getattr(block, "get_properties", None)
    if getter is None:
        return empty
    try:
        props = getter()
    except Exception as exc:
        logger.debug(
            f"[extended_props] get_properties() lanzo {type(exc).__name__}: {exc}"
        )
        return empty
    if props is None:
        return empty

    # Diagnostico: una vez por sesion, loggear que keys expone realmente
    # el objeto devuelto por get_properties(). Asi el operario puede ver
    # en logs si la shape es distinta de la esperada.
    if not getattr(_extract_extended_properties, "_logged_keys", False):
        try:
            if hasattr(props, "__dict__") and props.__dict__:
                available = sorted(vars(props).keys())
            elif hasattr(props, "keys"):
                available = sorted(props.keys())
            else:
                available = f"tipo_desconocido:{type(props).__name__}"
            logger.debug(
                f"[extended_props] Primer get_properties() de la sesion. "
                f"Tipo: {type(props).__name__}. Claves disponibles: {available}"
            )
        except Exception:
            logger.debug(
                "[extended_props] No se pudo introspeccionar la shape de props"
            )
        _extract_extended_properties._logged_keys = True

    # Mapeo principal (PascalCase -> snake_case) y variantes alternativas
    # por si la shape real usa otro casing o separador.
    tia_to_py = {
        "Title": "title",
        "Comment": "comment",
        "Author": "author",
        "Version": "version",
        "ProgrammingLanguage": "programming_language",
        "MemoryLayout": "memory_layout",
    }
    alt_candidates: dict[str, list[str]] = {
        "title": ["title"],
        "comment": ["comment"],
        "author": ["author"],
        "version": ["version"],
        "programming_language": ["programmingLanguage", "programming_language"],
        "memory_layout": ["memoryLayout", "memory_layout"],
    }

    def _read(tia_name: str, py_name: str) -> Optional[str]:
        """Lee una propiedad probando getattr y luego dict-style.

        Semantica:
          - El main candidate (PascalCase) tiene prioridad absoluta.
          - Si el main devuelve ``None`` (atributo no presente), se
            prueban alt candidates (camelCase / snake_case) y dict.
          - Si el main devuelve ``""`` se respeta como valor valido
            (no se buscan alts): un bloque con comentario vacio NO
            debe caer al path camelCase ni auto-crear nada.
          - El path dict-like solo se prueba si ``props`` es realmente
            un ``dict`` (no cualquier callable ``.get``) para evitar
            falsos positivos con ``MagicMock`` u objetos que exponen
            ``.get`` por巧合.
        """
        candidates = [tia_name] + alt_candidates.get(py_name, [])
        props_is_dict = isinstance(props, dict)

        raw: Any = None

        # 1. Main candidate: primero atributo, luego dict.
        try:
            raw = getattr(props, tia_name, None)
        except Exception:
            raw = None
        if raw is None and props_is_dict:
            try:
                raw = props.get(tia_name)
            except Exception:
                raw = None

        # 2. Solo si el main no estaba, buscar en alt candidates.
        if raw is None and len(candidates) > 1:
            for candidate in candidates[1:]:
                try:
                    raw = getattr(props, candidate, None)
                except Exception:
                    raw = None
                if raw is not None:
                    break
                if props_is_dict:
                    try:
                        raw = props.get(candidate)
                    except Exception:
                        raw = None
                    if raw is not None:
                        break

        if raw is None or raw == "":
            return None
        try:
            s = str(raw).strip()
        except Exception:
            return None
        return s if s else None

    return {
        py_name: _read(tia_name, py_name)
        for tia_name, py_name in tia_to_py.items()
    }


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
        tipo = classify_block(block)
        match = re.match(r"^(DB|FB|FC|OB|UDT)(\d+)", nombre, re.IGNORECASE)
        numero = int(match.group(2)) if match else 0
        extended = _extract_extended_properties(block)
        out.append(
            DataBloquePLC(
                nombre=str(nombre),
                numero=numero,
                tipo=tipo,
                ruta=ruta,
                **extended,
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


def _find_block_in_plc(plc: Any, block_name: str, block_path: str) -> Any:
    """Resuelve un PlcBlock por nombre + jerarquía dentro de un PLC.

    Itera recursivamente sobre el árbol de bloques/grupos del PLC buscando
    un bloque cuyo ``name`` coincida con ``block_name``. Si ``block_path``
    es vacío, busca solo en el nivel raíz; si tiene segmentos separados
    por ``"\\"``, navega primero por la jerarquía de grupos.

    Args:
        plc: instancia ``Plc`` (objeto nativo TIA vía ``siemens_tia_scripting``).
        block_name: nombre del bloque SIN ruta (e.g. ``"DB1"``).
        block_path: jerarquía TIA con separador ``"\\"``. ``""`` si está
            en el nivel raíz del PLC.

    Returns:
        El ``PlcBlock`` encontrado.

    Raises:
        RuntimeError: si el bloque no se encuentra o el path no resuelve.
            El handler ``update_block_property`` confía en este raise para
            hacer rollback de la transacción.
    """
    def _norm(s: str) -> str:
        return (s or "").replace("/", "\\").strip()

    target_path = _norm(block_path)

    candidates_groups: list[Any] = [plc]

    if target_path:
        for segment in target_path.split("\\"):
            segment = segment.strip()
            if not segment:
                continue
            next_groups: list[Any] = []
            for grp in candidates_groups:
                try:
                    sub = grp.get_groups() if hasattr(grp, "get_groups") else []
                except Exception:
                    sub = []
                for g in sub:
                    name = getattr(g, "name", None)
                    if name is None:
                        try:
                            name = str(g.Name)
                        except Exception:
                            name = None
                    if name == segment:
                        next_groups.append(g)
                        break
            if not next_groups:
                raise RuntimeError(
                    f"_find_block_in_plc: no se encontró grupo "
                    f"{segment!r} en path {block_path!r}"
                )
            candidates_groups = next_groups

    for grp in candidates_groups:
        try:
            blocks = grp.get_program_blocks() if hasattr(grp, "get_program_blocks") else (
                grp.get_blocks() if hasattr(grp, "get_blocks") else []
            )
        except Exception:
            blocks = []

        for b in blocks:
            name = getattr(b, "name", None)
            if name is None:
                try:
                    name = str(b.Name)
                except Exception:
                    continue
            if name == block_name:
                return b

    raise RuntimeError(
        f"_find_block_in_plc: no se encontró bloque {block_name!r} "
        f"en path {block_path!r}"
    )


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
    keep_folder_structure: bool = True,
) -> dict:
    """Exporta una coleccion de objetos TIA (Bloques o UDTs) a .s7dcl.

    Args:
        collection_key: 'program_blocks' | 'user_data_types'.
        keep_folder_structure: si ``True`` (default), exporta conservando la
            jerarquia de subcarpetas del PLC en TIA Portal (e.g.
            ``<target>/2000_Dispositivos/<obj>.s7dcl``). Si ``False``,
            exporta FLAT a ``<target>/<obj>.s7dcl``. Por defecto ``True``
            (compatibilidad con callers existentes).

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
            keep_folder_structure=keep_folder_structure,
        )
        count += 1

    return {"exported_to": str(target_path), "count": count}


# ---------------------------------------------------------------------------
# Decorador de trazabilidad para handlers OT (Zona D, paso 1)
# ---------------------------------------------------------------------------
# Tras el giro 'DEBUG by default' el decorador
# @log_ot_command se ha eliminado: los handlers se invocan sin
# instrumentacion automatica. Si el operario quiere un log en la
# consola web para un comando concreto, lo anade manualmente con
# ``logger.web(...)`` / ``logger.ok(...)`` dentro del cuerpo del
# handler (no en el CALLER). Ver seccion 4.5 del plan living
# TRAZABILIDAD_LOGGING.md.


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
