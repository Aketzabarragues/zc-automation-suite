"""iniciar.py — desarrollo: backend + Vite + navegador.

Arranca el backend en modo desarrollo y el servidor de Vite, y abre el
navegador en la SPA. El backend se ejecuta en un hilo aparte para que Vite
pueda tomar el control de la consola.

Con ``--build`` no arranca Vite: el backend sirve el build de la SPA
(``frontend/dist``), que es como funcionara el ``.exe``.

Uso:
    python iniciar.py            # backend + Vite
    python iniciar.py --build    # backend sirviendo frontend/dist
"""

from __future__ import annotations

import argparse
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


def _backend(desarrollo: bool) -> None:
    """Arranca el backend.

    Args:
        desarrollo: si es ``True`` se admiten los origenes de Vite.
    """
    from zc_suite.nucleo.app.main import arrancar

    arrancar(host=HOST, puerto=PUERTO, desarrollo=desarrollo)


def _servir_build() -> int:
    """Arranca solo el backend, sirviendo el build de la SPA."""
    sys.path.insert(0, str(RAIZ / "backend"))

    dist = FRONTEND / "dist"
    if not (dist / "index.html").is_file():
        print("El frontend no esta compilado. Ejecuta 'npm run build' en frontend/.")
        return 1

    print(f"Backend:  http://{HOST}:{PUERTO}")
    print("Frontend: build de frontend/dist")
    print("Ctrl+C para parar.")
    webbrowser.open(f"http://{HOST}:{PUERTO}/")
    _backend(desarrollo=False)
    return 0


def main() -> int:
    """Arranca Vite y el backend, y abre el navegador."""
    parser = argparse.ArgumentParser(description="Arranca ZC Automation Suite.")
    parser.add_argument(
        "--build",
        action="store_true",
        help="Sirve el build de la SPA desde Flask, sin Vite. Es como ira en el .exe.",
    )
    argumentos = parser.parse_args()

    if argumentos.build:
        return _servir_build()

    sys.path.insert(0, str(RAIZ / "backend"))

    vite = subprocess.Popen(
        [_npm(), "run", "dev"],
        cwd=FRONTEND,
        shell=False,
    )
    backend = threading.Thread(target=_backend, args=(True,), name="zc-backend", daemon=True)
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
