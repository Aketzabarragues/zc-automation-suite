"""Test regresivo: baktilts dentro de templates Vue ESM del shell.

Audita los 3 modulos del feature "Editor de Propiedades de Bloques PLC":
  - ``core/web_server/static/js/components/BlockPropertiesEditor.js``
  - ``core/web_server/static/js/components/ShellSidebar.js``
  - ``core/web_server/static/js/main.js``

Regla (AGENTS.md + agent memory): CUALQUIER backtick (`` ` ``) dentro
del bloque ``template: /* html */ `...` `` ROMPE el compilador de Vue 3
en runtime (``vue.esm-browser.prod.js``). Doble (`` `` ``) o simple
(``` ` ```), da igual: cualquier backtick cierra el template
prematuramente.

Los baktilts FUERA del bloque (JSDoc, comentarios de bloque, strings
normales, imports, `` ` `` en ``import``/``export``) son seguros; este
test solo audita el contenido entre los delimitadores del template.
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]


FILES_TO_CHECK = (
    "core/web_server/static/js/components/BlockPropertiesEditor.js",
    "core/web_server/static/js/components/ShellSidebar.js",
    "core/web_server/static/js/main.js",
)


def extract_template_block(text: str) -> tuple[str, int, int] | None:
    """Devuelve ``(contenido, start_line, end_line)`` del template o ``None``.

    ``start_line`` y ``end_line`` son 1-indexed sobre ``text``. El
    contenido excluye las lineas que contienen los delimitadores `` ` ``.
    """
    lines = text.split("\n")
    start_idx: int | None = None
    for i, line in enumerate(lines):
        if "template:" in line and "/* html */" in line and "`" in line:
            start_idx = i
            break
    if start_idx is None:
        return None
    end_idx: int | None = None
    for j in range(start_idx + 1, len(lines)):
        if lines[j].lstrip().startswith("`"):
            end_idx = j
            break
    if end_idx is None:
        return None
    content = "\n".join(lines[start_idx + 1:end_idx])
    return content, start_idx + 1, end_idx + 1


def count_baktilts_in_template(template: str) -> int:
    """Cuenta TODOS los `` ` `` (simples) dentro del template."""
    return template.count("`")


def _format_backtick_report(
    rel_path: str,
    template: str,
    start_line: int,
    occurrences: list[int],
) -> str:
    """Compone el mensaje de error con offset + linea relativa + contexto."""
    header = (
        f"Baktilts encontrados en {rel_path} "
        f"(template lines {start_line}-{start_line + template.count(chr(10))}):\n"
    )
    lines = template.split("\n")
    entries: list[str] = []
    for offset in occurrences:
        # Calcula numero de linea relativo al contenido del template (1-indexed).
        rel_line = template.count("\n", 0, offset) + 1
        ctx_before = template[max(0, offset - 30):offset]
        ctx_after = template[offset + 1:offset + 31]
        # Reconstruye la linea completa para mejor contexto.
        line_start = template.rfind("\n", 0, offset) + 1
        line_end = template.find("\n", offset)
        if line_end == -1:
            line_end = len(template)
        full_line = template[line_start:line_end]
        entries.append(
            f"  offset {offset} (line {rel_line}): {full_line!r}"
        )
    return header + "\n".join(entries)


@pytest.mark.parametrize("rel_path", FILES_TO_CHECK)
def test_no_baktilts_en_template_block_editor(rel_path: str) -> None:
    """Falla si el modulo del feature lleva CUALQUIER baktill dentro del template."""
    abs_path = REPO_ROOT / rel_path
    if not abs_path.is_file():
        pytest.fail(f"Fichero del feature no encontrado: {abs_path}")
    text = abs_path.read_text(encoding="utf-8")
    block = extract_template_block(text)
    if block is None:
        pytest.fail(
            f"{rel_path}: no se localizo bloque template "
            f"(pattern 'template: /* html */ ` ... `'). "
            f"Si el componente ya no usa template string, revisa el alcance del test."
        )
    template, start_line, _end_line = block
    occurrences = [m for m in range(len(template)) if template[m] == "`"]
    if not occurrences:
        return
    pytest.fail(
        _format_backtick_report(rel_path, template, start_line, occurrences)
    )