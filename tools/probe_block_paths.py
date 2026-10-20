"""Sonda de solo lectura sobre ``ProgramBlock.get_path()`` en TIA Portal.

Ejecutar con TIA Portal abierto y el proyecto cargado:

    python tools/probe_block_paths.py

Imprime, por bloque: nombre, ``get_path()``, ``get_path_full()`` y
``get_property(name="Number")``. Solo lee: no exporta ni modifica nada.

Resultado medido: ``get_path()`` devuelve SIEMPRE la jerarquia de grupos
con separador ``"/"``, vacia en la raiz. No devuelve el nombre del
bloque.

    OB1_MAIN      get_path=""                            Number=1
    OB40_...      get_path="0_Sistema"                   Number=40
    FC16_...      get_path="ZC_Controles/1_Documentado"  Number=16
    FB15051_...   get_path="ZC_Controles/3_EnDesarrollo/_CambioSCL"

``get_path_full()`` antepone el PLC y la raiz del arbol:

    ZC_PLC_STD/Bloques de programa/ZC_Controles/1_Documentado

Un valor de ``ruta`` que coincide con el nombre del bloque no viene de
TIA: viene de un consumidor que metio la clave de fila en el campo
``ruta``.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Anadir el repo al sys.path para poder importar core.infrastructure.tia.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core.infrastructure.tia.tia_loader import load_siemenstia  # noqa: E402


def _safe(fn, default="<error>"):
    """Ejecuta fn() tolerando COM exceptions."""
    try:
        return fn()
    except Exception as exc:
        return f"<{type(exc).__name__}: {exc}>"


def _probe_block(block) -> dict:
    name = _safe(lambda: block.get_name())
    path = _safe(lambda: block.get_path())
    path_full = _safe(lambda: block.get_path_full())
    number = _safe(lambda: block.get_property(name="Number"))
    return {
        "name": name,
        "get_path": path,
        "get_path_full": path_full,
        "Number": number,
    }


def walk(node, depth: int, out: list[tuple[int, dict]]) -> None:
    """Recorre bloques + grupos recursivamente, anotando la profundidad."""
    try:
        blocks = list(node.get_program_blocks() or []) \
            if hasattr(node, "get_program_blocks") \
            else list(node.get_blocks() or [])
    except Exception:
        blocks = []
    for b in blocks:
        out.append((depth, _probe_block(b)))

    try:
        groups = list(node.get_groups() or []) \
            if hasattr(node, "get_groups") else []
    except Exception:
        groups = []
    for g in groups:
        walk(g, depth + 1, out)


def main() -> int:
    ts, _vendor_dir = load_siemenstia()

    portal = ts.attach_portal()
    try:
        project = _safe(lambda: portal.get_project())
        print(f"proyecto: {_safe(lambda: project.get_name())}")

        plcs = list(_safe(lambda: project.get_plcs()) or [])
        print(f"PLCs encontrados: {len(plcs)}")

        for plc in plcs:
            plc_name = _safe(lambda: plc.get_name())
            print(f"\n{'=' * 78}")
            print(f"PLC: {plc_name}")
            print(f"{'=' * 78}")
            print(
                f"{'depth':<6} {'name':<28} {'get_path':<32} "
                f"{'get_path_full':<28} {'Number':<8}"
            )
            print(f"{'-' * 78}")

            rows: list[tuple[int, dict]] = []
            walk(plc, 0, rows)

            for depth, info in sorted(rows, key=lambda r: (r[1]["get_path_full"], r[0])):
                print(
                    f"{depth:<6} "
                    f"{str(info['name']):<28} "
                    f"{str(info['get_path']):<32} "
                    f"{str(info['get_path_full']):<28} "
                    f"{str(info['Number']):<8}"
                )

            print(f"\ntotal bloques: {len(rows)}")
            if not rows:
                print("  (el PLC no tiene bloques de programa)")

    finally:
        try:
            portal.detach()
            print("\nportal detach OK")
        except Exception as exc:
            print(f"\ndetach fallo: {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())