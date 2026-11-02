"""Ejecuta el FB de la demo de punta a punta (sin TIA).

Muestra lo que veria el operario: el flujo de steps y el detail de cada
uno. El dispatch lo hace el motor; el FB solo declara sus pasos.

    python demo/demo_disp_sync.py

No toca TIA ni la aplicacion: la logica de negocio de los pasos esta
resumida en ``demo/despues_fb_disp_sincronizar.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.despues_fb_disp_sincronizar import FunctionDispSincronizar
from demo.despues_function_base import TrackerConsola


def main() -> int:
    tracker = TrackerConsola()
    fb = FunctionDispSincronizar(tracker=tracker)

    print(f"FB: {fb.nombre} -- {fb.titulo}")
    print(f"steps declarados: {len(fb.steps)}")
    for s in fb.steps:
        print(f"  S{s['handler']}: {s['nombre']}")

    fb.execute(plc_name="DEMO_S7-1500")

    print(f"\nnStep={fb.nStep}  error={fb.error_msg}")
    print(f"result={fb.result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
