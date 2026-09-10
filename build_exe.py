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
        # --collect-all + --hidden-import son obligatorios para que
        # PyInstaller incluya el paquete ``core.web`` y sus routers.
        # Sin esto, el .exe incluye index.html (vía --add-data) pero
        # NO el código Python de los routers: el endpoint /api/v1/ping
        # y /api/v1/events devuelven 404. PyInstaller tiene un bug
        # conocido con paquetes que tienen __init__.py vacíos (no
        # detecta dependencias transitivas). Ver:
        # https://github.com/pyinstaller/pyinstaller/issues/5568
        "--collect-all", "core",
        "--hidden-import", "core.web.app",
        "--hidden-import", "core.web.routers.spike",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "anyio",
        "--hidden-import", "anyio._backends",
        "--hidden-import", "anyio._backends._asyncio",
        # Sin consola (windowed): la bandeja maneja la UX.
        # El logging de uvicorn se desactiva con ``log_config=None`` en
        # main_tray.py (sino falla con stdout=None).
        "--windowed",
        "main_tray.py",
    ]
    PyInstaller.__main__.run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
