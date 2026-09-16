"""Utilidades de texto para modificadores SimaticSD.

Funciones puras de sanitizacion y escape de comentarios del PLC.
Sin estado, sin dependencias de TIA.
"""
from __future__ import annotations

import logging
import re

from core.infrastructure.tia.tia_export_paths import EMPTY_TEXT, MAX_COMMENT_LEN


_logger = logging.getLogger(f"{__name__}")


def strip_enclosing_quotes(text: str) -> str:
    """Quita comillas envolventes si el texto empieza Y termina con la misma.

    TIA Portal exporta algunos comentarios entre comillas literales
    en el ``.s7res`` (espacios al final, comillas internas, etc.). Y
    el operario a veces pega textos del Excel con comillas envolventes
    por error. Esta funcion los limpia de forma conservadora: solo
    actua si la primera Y la ultima posicion son la MISMA comilla
    (simples o dobles). Un texto con una sola comilla al inicio o al
    final se queda tal cual.

    Ademas hace ``.strip()`` por si TIA deja espacios colgando
    despues de la comilla de cierre (caso raro pero visto en
    exports reales).
    """
    if len(text) < 2:
        return text.strip()
    first = text[0]
    last = text[-1]
    if first == last and first in ("'", '"'):
        return text[1:-1].strip()
    return text.strip()


def sanitize_comment_text(text: str | None, slot: int) -> str:
    """Limpia el texto del comentario: trim, colapsa saltos, escapa, trunca."""
    if text is None:
        text = ""
    s = text.strip()
    # Si el operario pega el comentario del Excel con comillas
    # envolventes por error, las quitamos antes de colapsar whitespace.
    s = strip_enclosing_quotes(s)
    s = re.sub(r"\s+", " ", s)
    if not s:
        s = EMPTY_TEXT
    if len(s) > MAX_COMMENT_LEN:
        _logger.warning(
            f"Comentario del slot {slot} truncado de {len(s)} a "
            f"{MAX_COMMENT_LEN} chars."
        )
        s = s[:MAX_COMMENT_LEN]
    return s


def escape_s7res_text(text: str) -> str:
    """Escapa el texto para YAML: comillas dobles como ``""``."""
    return text.replace('"', '""')


def escape_s7dcl_text(text: str) -> str:
    """Escapa el texto para SCL: comillas dobles como ``\\"``."""
    return text.replace('"', '\\"')


__all__ = [
    "strip_enclosing_quotes",
    "sanitize_comment_text",
    "escape_s7res_text",
    "escape_s7dcl_text",
]
