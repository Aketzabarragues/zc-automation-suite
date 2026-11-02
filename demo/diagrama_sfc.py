"""Generador de diagramas SFC de un Function Block.

El diagrama se dibuja desde la MISMA declaracion que ejecuta el motor:
en el formato A son los metodos marcados con ``@step``; en el formato
antiguo es la tabla ``STAGES``. No hay una tercera lista que mantener.

    python demo/diagrama_sfc.py             -> diagrama ASCII + mermaid
    python demo/diagrama_sfc.py --mermaid   -> solo mermaid
    python demo/diagrama_sfc.py --todos     -> el de antes y el de despues

Nada de esto toca la aplicacion: es material de analisis.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any

ANCHO_MIN = 78
INDENT = "  "


def _de_stages(stages: Any) -> list[dict[str, Any]]:
    """Normaliza la tabla ``STAGES`` (tuplas o dicts) a la misma forma."""
    pasos: list[dict[str, Any]] = []
    for item in stages:
        if isinstance(item, dict):
            pasos.append(
                {
                    "n": item.get("n") or len(pasos) + 1,
                    "nombre": item.get("nombre", ""),
                    "descripcion": item.get("descripcion", ""),
                    "metodo": item.get("handler") or item.get("metodo", ""),
                }
            )
        else:
            n, nombre, metodo = item
            pasos.append(
                {
                    "n": n,
                    "nombre": nombre,
                    "descripcion": "",
                    "metodo": metodo,
                }
            )
    return pasos


def pasos_de(cls: type) -> list[dict[str, Any]]:
    """Los pasos del FB, sea cual sea el formato de la declaracion."""
    declarados = getattr(cls, "pasos_declarados", None)
    if callable(declarados):
        specs = declarados()
        if specs:
            return [
                {
                    "n": i + 1,
                    "nombre": spec.nombre,
                    "descripcion": spec.descripcion,
                    "metodo": spec.metodo,
                }
                for i, spec in enumerate(specs)
            ]
    stages = getattr(cls, "STAGES", None)
    if stages:
        return _de_stages(stages)
    return []


def _titulo(cls: type) -> str:
    doc = (cls.__doc__ or "").strip().splitlines()
    return doc[0].strip() if doc else ""


def _ancho(pasos: list[dict[str, Any]]) -> int:
    """Ancho de las cajas: el que pide el nombre mas largo."""
    ancho = ANCHO_MIN
    for p in pasos:
        ancho = max(ancho, 10 + len(p["nombre"]) + 2)
    return ancho


def _caja(paso: dict[str, Any], ancho: int, detail: str = "") -> list[str]:
    interior = ancho - 4
    nombre = paso["nombre"]
    lineas: list[str] = []

    prefijo = f"┌─ S{paso['n']} ─ {nombre} "
    relleno = "─" * max(0, ancho - len(prefijo) - 1)
    lineas.append(prefijo + relleno + "┐")

    descripcion = (paso.get("descripcion") or "").strip()
    if descripcion:
        for trozo in textwrap.wrap(descripcion, interior) or [""]:
            lineas.append("│ " + trozo.ljust(interior) + " │")
    else:
        lineas.append("│ " + "(sin descripcion)".ljust(interior) + " │")

    metodo = paso.get("metodo")
    if metodo:
        lineas.append("│ " + f"-> {metodo}".ljust(interior) + " │")
    if detail:
        lineas.append("│ " + detail.ljust(interior) + " │")

    lineas.append("└" + "─" * (ancho - 2) + "┘")
    return lineas


def _detail_del_fb(cls: type, nombre: str) -> str:
    """De donde sale el detail de un step, segun el formato de la clase.

    En el formato antiguo el detail no lo da el paso: lo da un
    ``if/elif`` aparte, por nombre literal. En el formato nuevo lo
    devuelve el propio paso, asi que no hay nada que dibujar.
    """
    modulo = sys.modules.get(cls.__module__)
    if modulo is not None and hasattr(modulo, "_step_summary"):
        return f'detail: _step_summary(ctx, "{nombre}")'
    return ""


def diagrama_ascii(cls: type) -> str:
    """Diagrama SFC en texto plano."""
    pasos = pasos_de(cls)
    if not pasos:
        return f"{cls.__name__}: sin pasos declarados"

    ancho = _ancho(pasos)
    cabecera = [
        "╔" + "═" * (ancho - 2) + "╗",
        "║ " + cls.__name__.ljust(ancho - 4) + " ║",
        "║ " + _titulo(cls).ljust(ancho - 4) + " ║",
        "╚" + "═" * (ancho - 2) + "╝",
    ]

    cuerpo: list[str] = []
    for i, paso in enumerate(pasos):
        if i:
            cuerpo.append(INDENT + "    │")
            cuerpo.append(INDENT + "    ▼")
        cuerpo.extend(
            INDENT + linea
            for linea in _caja(paso, ancho, _detail_del_fb(cls, paso["nombre"]))
        )

    return "\n".join(cabecera + [""] + cuerpo)


def diagrama_mermaid(cls: type) -> str:
    """Diagrama SFC en mermaid (para el README o una wiki)."""
    pasos = pasos_de(cls)
    if not pasos:
        return "```mermaid\nflowchart TD\n    EMPTY[\"sin pasos declarados\"]\n```"

    ids = [f"S{p['n']}" for p in pasos]
    lineas = ["```mermaid", "flowchart TD"]
    for paso, sid in zip(pasos, ids):
        texto = f"{sid} · {paso['nombre']}"
        if paso.get("descripcion"):
            texto += "<br/>" + paso["descripcion"]
        texto = texto.replace('"', "'")
        lineas.append(f'    {sid}["{texto}"]')
    for origen, destino in zip(ids, ids[1:]):
        lineas.append(f"    {origen} --> {destino}")
    lineas.append("```")
    return "\n".join(lineas)


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from demo.antes_fb_disp_sincronizar import (
        FunctionDispSincronizar as FB_Antes,
    )
    from demo.despues_fb_disp_sincronizar import (
        FunctionDispSincronizar as FB_Despues,
    )

    solo_mermaid = "--mermaid" in sys.argv
    todos = "--todos" in sys.argv

    if todos and not solo_mermaid:
        print(diagrama_ascii(FB_Antes))
        print()
        print(diagrama_ascii(FB_Despues))
        print()

    if solo_mermaid:
        print(diagrama_mermaid(FB_Despues))
        return 0

    print(diagrama_ascii(FB_Despues))
    print()
    print(diagrama_mermaid(FB_Despues))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
