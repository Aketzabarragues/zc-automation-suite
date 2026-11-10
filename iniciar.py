"""iniciar.py — desarrollo: backend + Vite + navegador.

Arranca el backend en modo desarrollo y el servidor de Vite, y abre el
navegador en la SPA. El backend se ejecuta en un hilo aparte para que
Vite pueda tomar el control de la consola.

Uso:
    python iniciar.py
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
FRONTEND = RAIZ / "frontend"
HOST = "127.0.0.1"
PUERTO = 9484
PUERTO_VITE = 5173


def _npm() -> str:
    """Ruta del ejecutable de npm en Windows."""
    return "npm.cmd" if sys.platform == "win32" else "npm"


def _esperar_vite(segundos: float = 30.0) -> bool:
    """Espera a que el servidor de Vite responda."""
    import urllib.error
    import urllib.request

    limite = time.monotonic() + segundos
    url = f"http://localhost:{PUERTO_VITE}/"
    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as respuesta:
                if respuesta.status < 500:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


def _backend() -> None:
    """Arranca el backend en modo desarrollo."""
    from zc_suite.main import arrancar

    arrancar(host=HOST, puerto=PUERTO, desarrollo=True)


def main() -> int:
    """Arranca Vite y el backend, y abre el navegador."""
    sys.path.insert(0, str(RAIZ / "backend"))

    vite = subprocess.Popen(
        [_npm(), "run", "dev"],
        cwd=FRONTEND,
        shell=False,
    )
    backend = threading.Thread(target=_backend, name="zc-backend", daemon=True)
    backend.start()

    if not _esperar_vite():
        print("El servidor de Vite no ha respondido a tiempo.")
        vite.terminate()
        return 1

    url = f"http://localhost:{PUERTO_VITE}/"
    print(f"Backend:  http://{HOST}:{PUERTO}")
    print(f"Frontend: {url}")
    print("Ctrl+C para parar.")
    webbrowser.open(url)

    try:
        vite.wait()
    except KeyboardInterrupt:
        pass
    finally:
        vite.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
