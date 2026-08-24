"""Composition Root del launcher (modo dev) con system tray.

Este módulo es el entry point para ejecutar el tray launcher en dev:
    Doble clic sobre run_tray.bat   # ← SIN consola (recomendado)
    pythonw.exe main_tray.py        # ← SIN consola (manual)
    python main_tray.py             # ← CON consola (debug)

NO es el composition root de la aplicación (ese sigue siendo ``main.py``).
NO es la versión empaquetada — eso es Fase 2 (PyInstaller).

Responsabilidades exclusivas de esta capa:
  1. Configurar logging a fichero.
  2. Leer variables de entorno para host/puerto del web server.
  3. Crear el supervisor del web (NO iniciarlo — el operario decide).
  4. Bloquear el main thread con el icono de bandeja (pystray lo
     requiere así en Windows).
  5. Al salir (menú "Salir"), detener el web server limpiamente.

Lo que esta capa NO hace:
  - NO instancia el gateway directamente (lo hace el supervisor al
    construir la app FastAPI, igual que ``main.py --web``).
  - NO lanza workers persistentes: el patrón process-per-call del
    gateway es intocable.
  - NO modifica nada de ``application/``, ``core/``, ``infrastructure/``
    ni ``interfaces/``.
"""
from __future__ import annotations

import io
import logging
import os
import sys
import time
import traceback
from pathlib import Path


# ── Configuración de logging ANTES de cualquier import "pesado" ────
DEFAULT_LOG_DIR = (
    Path.home() / "AppData" / "Local" / "zc-automation-suite" / "logs"
)
LOG_DIR = Path(os.environ.get("ZC_LOG_DIR", DEFAULT_LOG_DIR))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "zc_tray.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        # En dev (python.exe) también a stdout. Con pythonw.exe no
        # hay stdout, asi que se ignora silenciosamente.
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("zc_tray")


def _setup_logging_redirect() -> None:
    """En modo frozen/windowed, reemplaza stdout/stderr por logger.

    En dev (no frozen) no hace nada: stdout es terminal real.
    Documentado para Fase 2; en este modo es no-op.
    """
    if getattr(sys, "frozen", False):
        class _StreamToLogger:
            def __init__(self, logger, level):
                self._logger = logger
                self._level = level
                self._buffer = ""

            def write(self, msg):
                self._buffer += msg
                while "\n" in self._buffer:
                    line, _, self._buffer = self._buffer.partition("\n")
                    if line and not line.isspace():
                        self._logger.log(self._level, line.rstrip())
                return len(msg)

            def flush(self):
                if self._buffer and not self._buffer.isspace():
                    self._logger.log(self._level, self._buffer.rstrip())
                    self._buffer = ""

            def isatty(self) -> bool:
                return False

            def fileno(self) -> int:
                raise OSError("_StreamToLogger has no file descriptor")

        sys.stdout = _StreamToLogger(log, logging.INFO)  # type: ignore[assignment]
        sys.stderr = _StreamToLogger(log, logging.ERROR)  # type: ignore[assignment]


def _resolve_icon_path() -> Path | None:
    """Resuelve la ruta del .ico.

    Modo frozen (Fase 2): vive dentro de ``sys._MEIPASS``.
    Modo dev: vive junto al código fuente.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    else:
        base = Path(__file__).parent
    icon = base / "launcher" / "icon.ico"
    return icon if icon.is_file() else None


def _read_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Variable %s=%r no es int; usando default %d", name, raw, default)
        return default


def main() -> int:
    # Forzar UTF-8 (mismo patrón que main.py / worker_tia.py).
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, Exception):
            sys.stdout = io.TextIOWrapper(  # type: ignore[assignment]
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
            sys.stderr = io.TextIOWrapper(  # type: ignore[assignment]
                sys.stderr.buffer, encoding="utf-8", errors="replace"
            )
            sys.stdin = io.TextIOWrapper(  # type: ignore[assignment]
                sys.stdin.buffer, encoding="utf-8", errors="replace"
            )

    _setup_logging_redirect()
    log.info("=" * 60)
    log.info("ZC Automation Suite (tray launcher) iniciando.")
    log.info("Python: %s | frozen=%s | pythonw=%s",
             sys.version.split()[0],
             getattr(sys, "frozen", False),
             sys.executable.endswith("pythonw.exe"))
    log.info("Log file: %s", LOG_FILE)

    from launcher.web_supervisor import WebServiceSupervisor

    web_host = os.environ.get("ZC_WEB_HOST", "127.0.0.1")
    web_port = _read_env_int("ZC_WEB_PORT", 8000)

    web = WebServiceSupervisor(host=web_host, port=web_port)
    log.info("Web supervisor creado: %s:%d", web_host, web_port)
    log.info("Esperando que el operario elija Iniciar web desde el menu.")

    # Bloquear main thread con pystray.
    try:
        from launcher.tray_app import run_tray

        icon_path = _resolve_icon_path()
        run_tray(web, icon_path, log)
    except Exception as exc:  # noqa: BLE001
        log.error("El icono de bandeja falló: %s\n%s", exc, traceback.format_exc())
        log.info(
            "Web server queda disponible. Cierre el proceso desde el Task Manager."
        )
        try:
            while web.is_alive():
                time.sleep(1.0)
        except KeyboardInterrupt:
            log.info("Ctrl+C detectado.")

    log.info("Cerrando web supervisor...")
    web.stop(timeout=5.0)
    log.info("Adios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
