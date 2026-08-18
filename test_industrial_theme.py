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

    print("\n--- Verificacion ConsolaLogs.js (INTACTO) ---")
    cl = (BASE / "js/components/ConsolaLogs.js").read_text(encoding="utf-8")
    if "bg-black" in cl and "bg-slate-900" in cl and "text-slate-200" in cl:
        print("  OK: footer con bg-black + bg-slate-900 + text-slate-200")
    else:
        print("  FAIL: ConsolaLogs.js parece haberse modificado")
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
