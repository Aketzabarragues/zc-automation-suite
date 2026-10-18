"""core.infrastructure.tia.sd_block_parser - parser SCL plano para .s7dcl.

Lee el primer bloque ``{ ... }`` de un archivo ``.s7dcl`` (formato
SimaticSD de Siemens) y devuelve sus asignaciones ``KEY := "VALUE"``
como ``dict``. Usado por el helper ``parse_extended_props_from_sd`` para
popular ``title`` y ``comment`` del DTO ``DataBloquePLC``, campos que
``get_property()`` no expone.

Funciones puras. No levanta excepciones por contenido inesperado:
archivo vacio, sin header o con BOM se devuelven como ``{}``.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("zc.tia.sd_block_parser")

SCL_HEADER_OPEN = "{"
SCL_HEADER_CLOSE = "}"
SCL_ASSIGN_RE = re.compile(r'(\w+)\s*:=\s*"((?:[^"\\]|\\.)*)"')
BLOCK_KEYWORD_RE = re.compile(
    r'\b(DATA_BLOCK|FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|TYPE)\b'
)


def parse_block_header(path: Path) -> dict[str, str]:
    """Devuelve las asignaciones ``KEY := "VALUE"`` del primer bloque ``{...}``.

    Contrato:
        - Lee ``path`` como UTF-8 y descarta un BOM inicial.
        - Busca el primer ``{`` dentro de las primeras 50 lineas; si no
          aparece, devuelve ``{}`` y emite ``logger.debug``.
        - Aplica ``SCL_ASSIGN_RE`` sobre el cuerpo entre ``{`` y el ``}``
          inmediato siguiente (sin anidamiento).
        - Tolera espacios alrededor de ``:=`` y escapes ``\"`` / ``\\``
          dentro del valor.
        - Si la clave aparece varias veces, gana la ultima.

    Raises:
        FileNotFoundError: si ``path`` no existe (los callers usan
            ``Path.exists()`` antes si quieren tolerancia).
    """
    data = Path(path).read_text(encoding="utf-8").lstrip("\ufeff")
    head_window = "\n".join(data.splitlines()[:50])
    open_idx = head_window.find(SCL_HEADER_OPEN)
    if open_idx < 0:
        logger.debug(
            "parse_block_header: sin %s en las primeras 50 lineas de %s",
            SCL_HEADER_OPEN,
            path,
        )
        return {}
    close_idx = data.find(SCL_HEADER_CLOSE, open_idx)
    if close_idx < 0:
        logger.debug("parse_block_header: header sin cerrar en %s", path)
        return {}
    block_body = data[open_idx + 1 : close_idx]
    return dict(SCL_ASSIGN_RE.findall(block_body))
