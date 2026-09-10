"""Fase 0.5 spike: empaquetado mínimo para validar SSE.

Build mínimo con PyInstaller para producir ``dist/zc-automation-suite.exe``
a partir de ``main_tray.py``. Suficiente para el spike de Fase 0.5: el
operario arranca el ``.exe``, la bandeja aparece, la conexión SSE aguanta
>30s sin cerrarse (criterio de cierre del plan §4 Fase 0.5).

Convenciones (.clinerules §1, §9):
  - Type hints en todas las firmas.
  - ``from __future__ import annotations``.
  - NO copia el ``.pyd`` de Siemens al repo: en este spike el SDK no se
    usa (la carga perezosa real es Fase 1, ver ``.clinerules`` §2).

Uso:
    python build_exe.py

Salida:
    dist/zc-automation-suite.exe (onefile, windowed)
"""
from __future__ import annotations

import platform
import sys

import PyInstaller.__main__


# ── Separador de --add-data ─────────────────────────────────────────────
# PyInstaller usa ';' en Windows y ':' en macOS/Linux. En este proyecto
# la máquina de destino es Windows (operario), pero defendemos contra
# builds accidentales en otros SOs con este condicional.
_ADD_DATA_SEP = ";" if platform.system() == "Windows" else ":"


def main() -> int:
    """Ejecuta PyInstaller con la config mínima del spike."""
    args: list[str] = [
        "--onefile",
        "--name", "zc-automation-suite",
        # Bundlea la SPA entera en ``_MEIPASS/static``. El código en
        # runtime (futuras fases) hará ``Path(__file__).parent / "static"``
        # para resolver assets.
        "--add-data", f"interfaces/web_server/static{_ADD_DATA_SEP}static",
        # Sin consola (windowed): la bandeja maneja la UX.
        "--windowed",
        "main_tray.py",
    ]
    PyInstaller.__main__.run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
