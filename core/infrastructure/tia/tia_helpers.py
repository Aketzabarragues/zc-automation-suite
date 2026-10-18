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
    """Lee las propiedades extendidas del bloque via ``get_property(name=...)``.

    Aketza confirmo con smoke (script ``prop_bloques.py``) que:

      - ``block.get_properties()`` devuelve **LISTA de strings** (los nombres
        de las propiedades disponibles), NO un dict ni un objeto con
        atributos. Por eso este helper NO usa ``get_properties()`` y va
        directo a ``get_property(name=...)`` por cada campo.
      - Las propiedades relevantes son: ``HeaderName``/``HeaderAuthor``/
        ``HeaderVersion`` (header info, vacias si el bloque nunca se ha
        hecho "Release"), ``ProgrammingLanguage`` (``SCL``/``LAD``/``FBD``/
        ``STL``/``GRAPH``/``CFC``/``DB``), ``MemoryLayout``
        (``Optimized``/``Standard``).
      - ``Comment`` NO esta expuesto via ``get_property`` en NINGUN tipo de
        bloque (OB, DB, FC, FB, UDT). Solo accesible via export-XML.
        Por eso queda ``None`` en este helper y se popula en FASE 3 con
        export-XML-reimport.
      - Algunas props (e.g. ``LibraryConformanceStatus``) lanzan
        excepciones UTF-8 al leer; este helper captura **por-propiedad**
        (no global) y sigue.

    Returns:
        ``dict`` con 5 keys: ``title``, ``author``, ``version``,
        ``programming_language``, ``memory_layout``. El campo ``comment``
        del DTO sigue siendo ``None`` (no se popula aqui).
    """
    tia_to_py = {
        "HeaderName": "title",
        "HeaderAuthor": "author",
        "HeaderVersion": "version",
        "ProgrammingLanguage": "programming_language",
        "MemoryLayout": "memory_layout",
    }

    out: dict[str, Optional[str]] = {py_name: None for py_name in tia_to_py.values()}

    getter = getattr(block, "get_property", None)
    if getter is None:
        # El bloque no soporta get_property (no es ProgramBlock).
        return out

    for tia_name, py_name in tia_to_py.items():
        try:
            raw = getter(name=tia_name)
        except Exception as exc:
            # Captura por-propiedad. LibraryConformanceStatus y similares
            # pueden lanzar UTF-8 decode errors; no romper el resto.
            logger.debug(
                f"[extended_props] {tia_name} lanzo {type(exc).__name__}: {exc}"
            )
            continue
        if raw is None or raw == "":
            continue
        try:
            s = str(raw).strip()
        except Exception:
            continue
        if s:
            out[py_name] = s

    return out


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
            name = _safe_get_block_name(b)
            if name is None:
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


# ---------------------------------------------------------------------------
# Cruce de propiedades extendidas TIA + header SCL del .s7dcl
# ---------------------------------------------------------------------------
def parse_extended_props_from_sd(
    sd_path: Path | str | None,
    base_props: dict[str, Any],
) -> dict[str, Any]:
    """Overridea ``title`` y ``comment`` de ``base_props`` desde el header SCL.

    ``base_props`` proviene de ``_extract_extended_properties`` (titulo,
    autor, version, programming_language, memory_layout leidos via
    ``get_property(name=...)``). Title y Comment NO los expone la API
    .NET del wrapper, asi que se obtienen del header ``{...}`` del
    ``.s7dcl`` exportado via ``export_block``.

    Comportamiento:
      - ``sd_path`` inexistente o ``None``: retorna copia de ``base_props``
        sin tocar (no propaga ``FileNotFoundError``).
      - Si el header SCL contiene ``S7_BlockTitle``, overridea ``title``.
      - Si el header SCL contiene ``S7_BlockComment``, overridea ``comment``.
      - Los demas campos (author, version, programming_language,
        memory_layout) se preservan tal cual vienen de ``base_props``.

    Returns:
        Nuevo dict (no muta ``base_props``) con los campos actualizados.
    """
    from core.infrastructure.tia.sd_block_parser import parse_block_header

    out = dict(base_props)
    if sd_path is None:
        return out
    path = Path(sd_path)
    if not path.exists():
        return out
    header = parse_block_header(path)
    if "S7_BlockTitle" in header:
        out["title"] = header["S7_BlockTitle"]
    if "S7_BlockComment" in header:
        out["comment"] = header["S7_BlockComment"]
    return out
