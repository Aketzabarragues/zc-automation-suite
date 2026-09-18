"""Regresion: Ningun template Vue 3 ESM del repo debe contener
backticks (`` ` ``) dentro de comentarios HTML (``<!-- ... -->``).

Por que: los templates Vue 3 ESM son template literals de
JavaScript (``template: `...` ``). Los comentarios HTML son
comentarios para HTML, NO para JavaScript: el parser JS ve los
backticks sueltos y los interpreta como apertura/cierre del
template literal. Resultado: el template se cierra
prematuramente y se lanza::

    SyntaxError: Unexpected identifier 'X'    (backticks impares)
    TypeError: "<header>... is not a function" (backticks pares)

Este test barre TODOS los .js con template literal en
``core/web_server/static/js/`` y falla si encuentra
backticks en comentarios HTML.

Antes : escaneaba ``interfaces/web_server/static/js/``
(path borrado en commits 0-7 del refactor de interfaces
-> core). Actualizado al nuevo path.

Regla para autores: dentro de comentarios HTML en templates
Vue 3 ESM, NO uses backticks. Si necesitas resaltar ``code``,
usa comillas dobles (``"texto"``) o simples (``'texto'``),
chevrons (``«texto»``), o simplemente texto sin marcadores.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

def _resolve_repo_root() -> Path:
    """Raiz del repo. Sube hasta encontrar ``main.py``.

    Robusto frente a movimientos del test entre subdirectorios
    de ``tests/`` .
    """
    here = Path(__file__).resolve().parent
    for candidate in [here, *here.parents]:
        if (candidate / "main.py").is_file():
            return candidate
    return here.parents[len(here.parents) - 4]


REPO_ROOT = _resolve_repo_root()
JS_DIR = REPO_ROOT / "core" / "web_server" / "static" / "js"


# Patrones:
# - Comentario HTML: <!-- ... -->
# - Buscamos backticks dentro.
# ANTES (defectuoso, ): <!--[^>]*?`[^>]*?-->
#   El [^>]*? antes del ` falla cuando hay un `>` en el contenido
#   del comentario (e.g. `store.plcs.length > 0` en ShellTopbar.js v2.2),
#   porque el `[^>]` excluye `>` y el regex se para antes de llegar al
#   backtick. Resultado: el test pasaba con archivos que tenian
#   backticks en comentarios HTML (bug del navegador silencioso).
# AHORA : <!--[^`]*?`.*?-->
#   El [^`]*? matchea cualquier cosa que no sea un backtick, no
#   importa si hay `>` en medio. Asi el regex matchea correctamente
#   comentarios con `>` arbitrarios.
COMMENT_WITH_BACKTICK = re.compile(
    r"<!--[^`]*?`.*?-->",
    re.DOTALL,
)
# Template literal Vue 3: `template: (opcional /* html */) ` ... `,`
TEMPLATE_LITERAL = re.compile(
    r"template:\s*(?:/\*\s*html\s*\*/)?\s*`",
)


def _find_files_with_template_literals() -> list[Path]:
    """Devuelve los .js bajo JS_DIR que tienen al menos un
    ``template: `...` `` (template literal Vue 3)."""
    found: list[Path] = []
    for js_path in sorted(JS_DIR.rglob("*.js")):
        # Saltamos vendor/ (Vue runtime, etc.)
        if "vendor" in js_path.parts:
            continue
        try:
            text = js_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if TEMPLATE_LITERAL.search(text):
            found.append(js_path)
    return found


FILES = _find_files_with_template_literals()


@pytest.mark.parametrize("js_path", FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_backticks_inside_html_comments_in_template(js_path: Path) -> None:
    """Verifica que el archivo .js ``js_path`` no tenga backticks
    dentro de comentarios HTML en su template Vue 3 literal.

    Si los tiene, el navegador lanzara ``TypeError: '... is not
    a function'`` o ``SyntaxError: Unexpected identifier 'X'``
    al renderizar el componente.
    """
    text = js_path.read_text(encoding="utf-8")
    matches = COMMENT_WITH_BACKTICK.findall(text)
    assert not matches, (
        f"{js_path.relative_to(REPO_ROOT)} tiene backticks dentro de "
        f"comentarios HTML, lo que cierra prematuramente el template "
        f"literal de Vue 3. Comentarios ofensivos:\n"
        + "\n---\n".join(m[:200] for m in matches)
        + "\n\nRegla: dentro de comentarios HTML en templates Vue 3 "
        "ESM, NO uses backticks. Usa comillas, chevrons o nada."
    )
