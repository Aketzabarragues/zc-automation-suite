"""Gestion del archivo .s7res para modificadores SimaticSD.

Funciones puras de insercion, actualizacion y poda de entradas
MultiLingualTexts (formato YAML de Siemens).
"""
from __future__ import annotations

import logging
import re

from areas.alimentacion.helpers.simatic_sd.simatic_sd_text_utils import (
    escape_s7res_text,
)


_logger = logging.getLogger(f"{__name__}")


_ENTRY_RE = re.compile(
    r"""(?xm)
    ^[ \t]*-\s*id:\s*(?P<mlc>\S+)\s*\n
    (?:[ \t]+[^\n]*\n)*?
    (?=\s*-\s*id:|\s*MultiLingualTexts:|\Z)
    """
)


def upsert_s7res_entry(s7res: str, mlc_id: str, text: str) -> tuple[str, bool]:
    """Inserta o actualiza una entrada ``- id: <mlc_id> / es-ES: <text>``.

    Si la entrada existe, reemplaza su texto ``es-ES``. Si no, la
    anade al bloque ``MultiLingualTexts`` (o lo crea si no existe).

    Retorna ``(nuevo_s7res, modified)``.
    """
    text = escape_s7res_text(text)
    pattern = re.compile(
        rf"(?xm)^(?P<indent>\s*-\s*id:\s*{re.escape(mlc_id)}\s*\n)"
        rf"(?P<inner>(?:\s+[^\n]*\n)*?)"
        rf"(?=\s*-\s*id:|\s*MultiLingualTexts:|\Z)"
    )
    m = pattern.search(s7res)
    if m is not None:
        new_inner = re.sub(
            r"es-ES:\s*[^\n]*",
            f"es-ES: {text}",
            m.group("inner"),
            count=1,
        )
        new_s7res = (
            s7res[: m.start("inner")]
            + new_inner
            + s7res[m.end("inner") :]
        )
        return new_s7res, new_s7res != s7res

    new_entry = f"  - id: {mlc_id}\n    es-ES: {text}\n"
    list_start = re.search(r"(?m)^MultiLingualTexts:\s*$", s7res)
    if list_start is None:
        new_s7res = "MultiLingualTexts:\n" + new_entry + s7res
        return new_s7res, True
    insert_pos = find_append_pos(s7res)
    new_s7res = s7res[:insert_pos] + new_entry + s7res[insert_pos:]
    return new_s7res, new_s7res != s7res


def find_append_pos(s7res: str) -> int:
    """Encuentra la posicion donde anadir una nueva entrada MultiLingualTexts.

    Estrategia: encontrar el final de la ultima entrada YAML de la
    lista (linea ``- id: MLC_xxx`` o ``es-ES: ...`` indentada), y
    devolver el offset justo despues de esa linea.
    """
    last_entry_end = 0
    for m in re.finditer(
        r"(?m)^[ \t]+(?:-\s*id:\s*|es-ES:\s*)[^\n]*\n",
        s7res,
    ):
        end = m.end()
        if end > last_entry_end:
            last_entry_end = end
    if last_entry_end == 0:
        m = re.search(r"(?m)^MultiLingualTexts:[^\n]*\n", s7res)
        if m is None:
            return 0
        return m.end()
    return last_entry_end


def prune_s7res(s7res: str, keep_mlcs: set[str]) -> tuple[str, int]:
    """Elimina del ``.s7res`` las entradas MLC que no esten en ``keep_mlcs``.

    Retorna ``(nuevo_s7res, n_removed)``.
    """
    removed = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal removed
        if m.group("mlc") in keep_mlcs:
            return m.group(0)
        removed += 1
        return ""

    new = _ENTRY_RE.sub(_repl, s7res)
    if removed:
        _logger.debug(f"s7res: {removed} entradas MLC huerfanas eliminadas.")
    return new, removed


def count_s7res_entries(s7res: str) -> int:
    """Cuenta las entradas ``- id: MLC_*`` en el .s7res."""
    return len(re.findall(r"(?m)^\s*-\s*id:\s*MLC_\S+", s7res))


__all__ = [
    "upsert_s7res_entry",
    "find_append_pos",
    "prune_s7res",
    "count_s7res_entries",
]
