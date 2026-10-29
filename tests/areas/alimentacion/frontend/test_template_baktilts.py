"""Tests que previenen baktilts dentro de templates Vue ESM.

Regla (AGENTS.md + agent memory): CUALQUIER backtick (`` ` ``) dentro
del string ``template: `...` `` ROMPE el compilador en runtime de
``vue.esm-browser.prod.js``:
  - Doble (`` `` ``): se cierra el template prematuramente.
  - Simple (``` ` ```): tambien, porque cualquier backtick cierra.

El caso real del operario: Entidades.js tenia ``ENT`` y
luego `ENT` en un comentario HTML. El primero fallo con
"TypeError ... is not a function", el segundo con
"SyntaxError: Unexpected identifier 'ENT'".

Este test audita TODOS los componentes Vue ESM del area alimentacion
y rompe si encuentra CUALQUIER backtick dentro del template string.
Cubre el bug en una sola pieza: si alguien anade un baktill
(simiple o doble) al refactorizar un componente, el test falla.

Para reproducir localmente:
  python _audit_templates.py
"""
from __future__ import annotations

import re
from pathlib import Path


COMPONENTS_DIR = Path(
    r"D:\Zeus Control\Proyectos\GitHub\zc-automation-suite\areas\alimentacion\frontend\components"
)


def _extract_template(text: str) -> tuple[int, int] | None:
    """Localiza el rango ``[start, end)`` del template string.

    Pattern de los componentes del area:
        template: /* html */ `
            ...
        `,
    """
    m_start = re.search(r"template:\s*/\*\s*html\s*\*/\s*`", text)
    m_end = re.search(r"`,\s*\};\s*$", text)
    if not m_start or not m_end:
        return None
    return (m_start.end(), m_end.start())


def test_no_backticks_en_templates_alimentacion():
    """NINGUN componente Vue ESM del area puede tener backticks dentro
    del template string.

    Audita todos los ``*.js`` de ``components/``. Si CUALQUIER archivo
    tiene un baktill dentro de ``template: `...` ``, el test FALLA con
    el contexto exacto para que el siguiente developer vea donde esta.
    """
    failures: list[str] = []
    files_audited = 0

    for path in sorted(COMPONENTS_DIR.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        rng = _extract_template(text)
        if rng is None:
            # No todos los componentes tienen template string (algunos
            # son solo data-driven). Auditar solo los que tienen uno.
            continue
        files_audited += 1
        s, e = rng
        template = text[s:e]
        for ind in [m.start() for m in re.finditer(r"`", template)]:
            ctx = template[max(0, ind - 30):ind + 30]
            failures.append(
                f"\n  {path.name} offset {ind}: {ctx!r}"
            )

    assert not failures, (
        f"Baktilts encontrados dentro de templates Vue ESM "
        f"(rompen el compilador en runtime de vue.esm-browser.prod.js).\n"
        f"Archivos auditados: {files_audited}.\n"
        f"Fix: usar HTML entities (&quot; o &#34;) o comillas rectas, "
        f"NUNCA backticks dentro de template: `...`."
        + "\n".join(failures)
    )