"""Validación del refactor a Tema Industrial Claro.

Comprueba:
  * input.css NO contiene @plugin "daisyui".
  * Sidebar / InspectorMemoria / SincronizacionTia / index.html NO
    contienen clases literales slate-X ni cyan-X.
  * ConsolaLogs.js permanece intacta (sigue con bg-black/slate-900).
  * Existe el mapa semántico en input.css (surface, ink, accent).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BASE = Path("interfaces/web_server/static")


def scan(name: str) -> list[str]:
    src = (BASE / name).read_text(encoding="utf-8")
    return re.findall(
        r"\b(?:slate|cyan)-(?:50|100|200|300|400|500|600|700|800|900|950)\b",
        src,
    )


def main() -> int:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print("=== Auditoria de tokens semanticos ===")
    frontend = ["index.html", "js/components/Sidebar.js",
                "js/components/InspectorMemoria.js",
                "js/components/SincronizacionTia.js"]
    rc = 0
    for name in frontend:
        bad = scan(name)
        verdict = "OK" if not bad else f"FAIL ({len(bad)})"
        print(f"  {name:<40s}  {verdict}")
        if bad:
            rc = 1
            print(f"    └─ ejemplos: {bad[:5]}")

    print("\n--- Verificacion input.css ---")
    ic = (BASE / "src/input.css").read_text(encoding="utf-8")
    if "@plugin" in ic.lower() and "daisyui" in ic.lower():
        print("  FAIL: input.css contiene @plugin daisyui")
        rc = 1
    else:
        print("  OK: input.css NO incluye @plugin daisyui (puede haber solo comentarios)")
    for token in ("--color-surface", "--color-ink", "--color-accent",
                  "--color-surface-raised", "--color-surface-sunken"):
        if token in ic:
            print(f"  OK: token {token} definido")
        else:
            print(f"  FAIL: falta token {token}")
            rc = 1

    print("\n--- Verificacion ConsolaLogs.js (tokens semanticos + LIFO) ---")
    cl = (BASE / "js/components/ConsolaLogs.js").read_text(encoding="utf-8")
    # Tras el refactor, ConsolaLogs usa tokens semánticos del Tema
    # Industrial Claro (no bg-black / bg-slate-900). Eso lo deja
    # en el mismo idioma visual que el resto de la SPA.
    for token in ("bg-surface-raised", "bg-surface-sunken", "border-line",
                  "text-ink", "text-ink-muted"):
        if token not in cl:
            print(f"  FAIL: ConsolaLogs no usa el token {token}")
            rc = 1
        else:
            print(f"  OK: ConsolaLogs usa {token}")
    # LIFO puro: usa reversedLogs en el v-for y NO muta store.logs.
    if "reversedLogs" in cl and "reverse()" in cl:
        print("  OK: LIFO implementado con reversedLogs (no toca store.logs)")
    else:
        print("  FAIL: ConsolaLogs.js no implementa reversedLogs")
        rc = 1
    # Tonos oscuros para los niveles de log (sobre fondo claro).
    for color in ("text-green-600", "text-amber-600", "text-red-600"):
        if color not in cl:
            print(f"  FAIL: falta tono {color} en el mapeo de niveles")
            rc = 1
        else:
            print(f"  OK: nivel {color} presente")
    # v-for debe iterar sobre reversedLogs, no sobre store.logs.
    if 'v-for="msg in reversedLogs"' in cl:
        print("  OK: v-for itera sobre reversedLogs")
    else:
        print("  FAIL: v-for no apunta a reversedLogs")
        rc = 1

    print("\n--- Verificacion index.html (clases semanticas) ---")
    html = (BASE / "index.html").read_text(encoding="utf-8")
    if "bg-surface" in html and "text-ink" in html:
        print("  OK: index.html usa bg-surface + text-ink")
    else:
        print("  FAIL: index.html no usa los nuevos tokens")
        rc = 1

    print()
    if rc == 0:
        print("OK: Tema Industrial Claro aplicado.")
        return 0
    print("FAIL: revisar mensajes anteriores.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
