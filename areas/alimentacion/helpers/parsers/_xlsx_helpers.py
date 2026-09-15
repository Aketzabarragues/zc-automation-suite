"""Helpers compartidos para los parsers del Excel corporativo.

Este mÃ³dulo concentra utilidades usadas por **todos** los parsers de
software y de hardware del subdominio ``alimentacion`` (los mini parsers
creados en las Fases 1-5 del plan
``_plan/04_excel_cache_phased_plan.md``). Su objetivo es eliminar
duplicaciÃ³n de cÃ³digo entre parsers (cada uno abrÃ­a el workbook,
localizaba la ``ListObject``, iteraba filas, descartaba vacÃ­as...) y
unificar la **semÃ¡ntica defensiva** del cast de valores (``_safe_str``
/ ``_safe_int`` / ``_safe_float``).

ConvenciÃ³n del helper:
    * ``_safe_str`` **NUNCA** devuelve ``None`` (devuelve ``""``). Esto
      es coherente con los DTOs ``frozen=True`` del subdominio (todos
      tienen ``str = ""`` como default) y con el comportamiento del
      parser consolidado ``AlimentacionExcelParser`` (que tambiÃ©n
      normaliza a ``""``).
    * ``_safe_int`` y ``_safe_float`` aceptan ``None``/``bool``/
      ``int``/``float``/``str`` numÃ©rico. ``bool`` se trata como
      ``int``/``float`` para no perder ``True``/``False`` legÃ­timos.
    * ``extract_list_object_rows`` es la Ãºnica puerta de entrada a las
      ``ListObject`` (Tablas Nombradas). Si la hoja o la tabla no
      existen, devuelve ``[]`` (no lanza) â€” polÃ­tica coherente con el
      R1 del plan.

RestricciÃ³n arquitectÃ³nica: este mÃ³dulo es OFFLINE; no importa
``siemens_tia_scripting``. Ãšnica dependencia externa: ``openpyxl``.
"""
from __future__ import annotations

import logging
from typing import Any

from openpyxl import Workbook
from openpyxl.utils.cell import range_boundaries


logger = logging.getLogger(__name__)


# â”€â”€ Cast defensivo de valores â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _safe_str(val: Any) -> str:
    """Convierte ``val`` a ``str``. NUNCA devuelve ``None``.

    Reglas:
        * ``None`` â†’ ``""``
        * ``"nan"`` / ``"NaN"`` / ``"None"`` / ``"null"`` (case
          insensitive) â†’ ``""``
        * Cadena vacÃ­a o solo whitespace â†’ ``""``
        * Resto â†’ ``str(val).strip()``

    Esta semÃ¡ntica es coherente con los DTOs ``frozen=True`` del
    subdominio (todos tienen ``str = ""`` como default) y garantiza
    que las claves ``cfg_*`` y los nombres de PlcTag lleguen
    literales a la SPA sin ``None`` que rompan el template.
    """
    if val is None:
        return ""
    text = str(val).strip()
    if text.lower() in ("nan", "none", "null", ""):
        return ""
    return text


def _safe_int(val: Any, default: int = 0) -> int:
    """Convierte ``val`` a ``int`` con fallback a ``default``.

    Acepta:
        * ``None`` â†’ ``default``
        * ``bool`` â†’ ``int(val)`` (``True`` â†’ 1, ``False`` â†’ 0)
        * ``int`` â†’ ``val`` (sin cambios)
        * ``str`` numÃ©rico (``"5"``, ``"5.0"``) â†’ ``int``
        * ``float`` â†’ ``int(val)`` (truncado, no redondeado)

    Cualquier otro caso (ej. ``"Pendiente"``) devuelve ``default`` en
    lugar de lanzar. Esto es **defensivo**: un Excel malformado no debe
    tumbar la carga.
    """
    if val is None:
        return default
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convierte ``val`` a ``float`` con fallback a ``default``.

    Acepta coma decimal (``"1,5"`` â†’ ``1.5``) â€” el Excel del
    operario usa coma como separador decimal en algunas hojas
    (tÃ­picamente las de rangos/escalado de ``DispEA`` / ``DispSA``).
    """
    if val is None:
        return default
    if isinstance(val, bool):
        return float(val)
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).strip().replace(",", "."))
    except (ValueError, TypeError):
        return default


def _safe_num_lista(value: Any) -> int | str:
    """None/NaN/vacÃ­o â†’ 0. NumÃ©rico â†’ int. Texto no numÃ©rico â†’ str.

    Helper **especÃ­fico** de los parsers de parÃ¡metros (Fase 2 y 3
    del plan ``_plan/04_excel_cache_phased_plan.md``). La columna
    ``Num.Lista`` del Excel corporativo puede contener **dos clases
    de valores**:

        * Valores numÃ©ricos (``0``, ``1``, ``2``, â€¦) que el operario
          usa como Ã­ndice de selecciÃ³n en una lista HMI.
        * Texto literal (``"N/A"``, ``"TODOS"``, â€¦) que el operario
          usa como marcador semÃ¡ntico (sin lista asociada, todos
          los items, etc.).

    Reglas:
        * ``None`` / ``""`` / ``"nan"`` / ``"None"`` / ``"null"`` /
          whitespace puro â†’ ``0`` (interpretado como "sin lista").
        * ``int`` / ``float`` / ``str`` numÃ©rico (``"5"``,
          ``"5.0"``) â†’ ``int`` (truncado, no redondeado).
        * Cualquier otro texto (``"N/A"``, ``"TODOS"``, â€¦) se
          preserva literal como ``str``.

    Diferencia con ``_safe_int``: ``_safe_int`` cae a ``0`` para
    texto no numÃ©rico, lo cual serÃ­a destructivo para los
    marcadores semÃ¡nticos del operario. AquÃ­ se preserva el texto
    para que el DTO ``DataParamRealPLC.num_lista: int | str`` refleje
    fielmente el Excel.
    """
    cleaned = _safe_str(value)
    if not cleaned:
        return 0
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return cleaned


# â”€â”€ ExtracciÃ³n de ListObjects (Tablas Nombradas) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def extract_list_object_rows(
    wb: Workbook,
    sheet: str,
    table: str,
) -> list[dict[str, Any]]:
    """Lee la ``ListObject`` ``table`` de la hoja ``sheet`` y devuelve filas como dicts.

    Args:
        wb: workbook de openpyxl **ya abierto** (no se cierra aquÃ­;
            la responsabilidad es del caller / loader).
        sheet: nombre literal de la hoja (case-sensitive en openpyxl).
        table: nombre de la ``ListObject`` (Tabla_*).

    Returns:
        Lista de ``{cabecera_literal: valor, ...}`` con una entrada
        por fila de datos. Las filas completamente vacÃ­as
        (``all(cell is None)``) se descartan. Las cabeceras vacÃ­as
        (``""`` o ``None``) se omiten del dict.

    PolÃ­tica defensiva (R1 del plan):
        * Si la hoja no existe â†’ ``[]``.
        * Si la tabla no existe en la hoja â†’ ``[]``.
        * Si el ``ref`` de la tabla es invÃ¡lido â†’ ``[]``.
        * Si ``range_boundaries`` lanza â†’ ``[]``.

    **NUNCA** lanza: un Excel malformado o una hoja renombrada
    simplemente devuelve lista vacÃ­a. El caller (parser) emite WARNING
    si lo necesita, pero ``extract_list_object_rows`` no se queja.
    """
    if sheet not in wb.sheetnames:
        return []
    worksheet = wb[sheet]
    tables = getattr(worksheet, "tables", None) or {}
    table_obj = tables.get(table)
    if table_obj is None:
        return []
    ref = getattr(table_obj, "ref", None)
    if not ref or not isinstance(ref, str) or ":" not in ref:
        return []

    try:
        min_col, min_row, max_col, max_row = range_boundaries(ref)
    except Exception:  # pragma: no cover - defensivo
        return []

    # â”€â”€ Cabeceras literales (1Âª fila del rango) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    header_cells = next(
        worksheet.iter_rows(
            min_row=min_row,
            max_row=min_row,
            min_col=min_col,
            max_col=max_col,
            values_only=True,
        )
    )
    headers: list[str] = [
        str(h).strip() if h is not None and str(h).strip() else ""
        for h in header_cells
    ]

    # â”€â”€ Datos (resto del rango) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    rows: list[dict[str, Any]] = []
    for row in worksheet.iter_rows(
        min_row=min_row + 1,
        max_row=max_row,
        min_col=min_col,
        max_col=max_col,
        values_only=True,
    ):
        if row is None or all(c is None for c in row):
            continue
        item: dict[str, Any] = {}
        for header_name, value in zip(headers, row):
            if not header_name:
                continue
            item[header_name] = value
        if item:
            rows.append(item)
    return rows


__all__ = [
    "_safe_str",
    "_safe_int",
    "_safe_float",
    "_safe_num_lista",
    "extract_list_object_rows",
]
