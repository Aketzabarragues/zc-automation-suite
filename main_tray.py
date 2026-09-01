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
# Prioridad de localizacion del log (operario puede forzar con env var):
#   1. ``ZC_LOG_DIR`` (override explicito).
#   2. Modo frozen (.exe): junto al ejecutable (``<exe_dir>/logs/``).
#      Asi el operario tiene todos los artefactos (.exe, .build_cache,
#      logs/) en la misma carpeta.
#   3. Modo dev (``python main_tray.py``): junto al CWD (``./logs/``).
#   4. Fallback legacy: ``%LocalAppData%\zc-automation-suite\logs\``
#      (solo si las opciones anteriores no se pueden crear, p.ej. permisos).
if getattr(sys, "frozen", False):
    DEFAULT_LOG_DIR = Path(sys.executable).parent / "logs"
else:
    DEFAULT_LOG_DIR = Path.cwd() / "logs"
LOG_DIR = Path(os.environ.get("ZC_LOG_DIR", DEFAULT_LOG_DIR))
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # Fallback al AppData legacy si no podemos escribir en la ruta
    # por defecto (permisos, etc.). El operario lo encontrara en
    # la ruta clasica de Windows.
    LOG_DIR = (
        Path.home() / "AppData" / "Local" / "zc-automation-suite" / "logs"
    )
    LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "zc_tray.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        # En dev (python.exe) también a stdout. En modo windowed
        # (PyInstaller ``console=False``) ``sys.stdout`` es ``None``;
        # crear un ``StreamHandler(None)`` provoca un ``AttributeError``
        # en cada ``emit()`` porque ``None.write`` no existe. Se filtra
        # explícitamente para que el .exe windowed solo escriba al
        # log file (``%LocalAppData%\zc-automation-suite\logs\zc_tray.log``).
        *(
            [logging.StreamHandler(sys.stdout)]
            if sys.stdout is not None
            else []
        ),
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

        # Reconfigurar loggers de uvicorn: por defecto añaden un
        # ``StreamHandler(sys.stderr)`` a sus loggers (``uvicorn``,
        # ``uvicorn.error``, ``uvicorn.access``). Como acabamos de
        # redirigir ``sys.stderr`` al logger ``zc_tray`` a nivel
        # ``ERROR``, las ``INFO`` de uvicorn se recapturan como
        # ``ERROR`` y aparecen en el log con el tag equivocado
        # (ej. ``[ERROR] zc_tray: INFO:     Started server process``).
        # Solución: quitar los handlers de uvicorn y dejar que
        # propaguen al root (``zc_tray``), que ya tiene el
        # ``FileHandler`` con el formato consistente. Así, un INFO
        # de uvicorn se loguea como ``[INFO] uvicorn: ...``.
        for _uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            _uv_logger = logging.getLogger(_uv_name)
            # Filtrar solo los StreamHandler a stderr capturable.
            # Otros handlers (p.ej. FileHandler propios) se preservan.
            _uv_logger.handlers = [
                h for h in _uv_logger.handlers
                if not (
                    isinstance(h, logging.StreamHandler)
                    and getattr(h, "stream", None) in (None, sys.__stderr__)
                )
            ]
            _uv_logger.propagate = True


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
    # ── Dispatch --worker (subprocess OT) ANTES de cualquier setup ───
    # Cuando el .exe frozen se lanza con `--worker`, el gateway
    # (``infrastructure/gateway.py``) nos está invocando como
    # subproceso efímero para ejecutar una tarea contra TIA Portal.
    # En ese caso saltamos TODA la inicialización de la bandeja
    # (logging a fichero, pystray, supervisor, etc.) y delegamos
    # directamente en el motor OT. El worker tiene su propio setup
    # de logging/UTF-8 en ``worker_tia.py``.
    if "--worker" in sys.argv[1:]:
        from core.infrastructure.tia.worker_tia import main as worker_main

        worker_main()
        return 0

    # Forzar UTF-8 (mismo patrón que main.py / worker_tia.py).
    # IMPORTANTE: en modo frozen/windowed (``console=False`` en el .spec
    # de PyInstaller), ``sys.stdout`` / ``stderr`` / ``stdin`` son ``None``
    # porque no hay consola asignada. El bloque ``try`` falla con
    # ``AttributeError`` (``NoneType.reconfigure``); el ``except`` no debe
    # entonces intentar ``sys.stdout.buffer`` (que también es ``None``)
    # o vuelve a romper. Se filtra por ``None`` antes de cada reconfigure
    # y, si nada es reconfigurable, ``_setup_logging_redirect()`` más
    # abajo redirige la salida al log file (``%LocalAppData%\...\zc_tray.log``).
    if sys.platform == "win32":
        for _stream_name in ("stdout", "stderr", "stdin"):
            _stream = getattr(sys, _stream_name, None)
            if _stream is None:
                # Modo windowed: el stream no existe. _setup_logging_redirect
                # se encargará de la salida. No hacemos nada.
                continue
            try:
                _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            except (AttributeError, Exception):
                # Stream sin ``reconfigure`` (Python <3.7). Intentamos
                # reconstruir el TextIOWrapper, pero solo si tiene ``buffer``.
                try:
                    setattr(
                        sys,
                        _stream_name,
                        io.TextIOWrapper(  # type: ignore[arg-type]
                            _stream.buffer,  # type: ignore[attr-defined]
                            encoding="utf-8",
                            errors="replace",
                        ),
                    )
                except (AttributeError, Exception):
                    # Sin buffer tampoco (p.ej. stream cerrado). Seguimos
                    # sin UTF-8 forzado en este stream concreto.
                    pass

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
    # El hook ``on_before_exit`` se dispara desde el menú "Salir" ANTES
    # de detener el icono, para que la bandeja y el web server se
    # cierren en el orden correcto (web primero, icono después). Si
    # ``run_tray`` levanta antes de que el operario clique Salir, el
    # hook no se habrá llamado y el ``web.stop`` posterior actúa como
    # red de seguridad.
    try:
        from launcher.tray_app import run_tray

        icon_path = _resolve_icon_path()
        run_tray(
            web,
            icon_path,
            log,
            on_before_exit=lambda: web.stop(timeout=5.0),
        )
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
