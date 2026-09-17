"""Mutaciones de texto en .s7dcl para modificadores SimaticSD.

Funciones puras de insercion y reemplazo de bloques en el .s7dcl.
"""
from __future__ import annotations

import logging
import re

# Asegura que ``Logger.web/ok`` existen tambien fuera del arranque.
from core.infrastructure.log_web_bridge import install_web_level
install_web_level()


_logger = logging.getLogger(__name__)


def upsert_s7dcl_block(
    s7dcl: str, match: re.Match[str], block: str
) -> tuple[str, bool]:
    """Inserta un bloque MLC justo antes de ``match``.

    Retorna ``(nuevo_s7dcl, modified)`` donde ``modified`` es True
    solo si el texto cambio.
    """
    new_s7dcl = s7dcl[: match.start()] + block + s7dcl[match.start() :]
    modified = new_s7dcl != s7dcl
    # DEBUG (no web): es una funcion pura llamada una vez por slot
    # durante la actualizacion; el resumen por DB lo emite el updater
    # padre (DispCommentUpdater.update). Aqui solo registramos el diff.
    _logger.debug(
        f"upsert_s7dcl_block: match={match.group(0)[:30]!r}, "
        f"block_len={len(block)}, modified={modified}"
    )
    return new_s7dcl, modified


def build_mlc_assignment_block(indent: str, mlc_id: str) -> str:
    """Construye el bloque ``{ S7_MLC := "..." }`` con la indentacion dada."""
    return (
        f"{indent}{{\n"
        f"{indent}    S7_MLC := \"{mlc_id}\";\n"
        f"{indent}}}\n"
    )


def build_assignment_line(
    indent: str, array_name: str, slot: int
) -> str:
    """Construye una linea ``<ARRAY>[slot] := ();`` con la indentacion dada."""
    return f"{indent}{array_name}[{slot}] := ();\n"


__all__ = [
    "upsert_s7dcl_block",
    "build_mlc_assignment_block",
    "build_assignment_line",
]
