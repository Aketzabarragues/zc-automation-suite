"""Único entry point del proyecto.

Modos:
  - default (sin args) -> Bandeja con icono (pystray).
  - ``--web [host:port]`` -> CLI headless: Flask + OB1 sin bandeja.
                           Ctrl+C para parar.

Lanzamientos típicos:
  - run_tray.bat            # doble click, sin consola
  - python main.py          # consola para debug
  - run_app.bat             # python main.py --web
"""
from __future__ import annotations

import io
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from core.application.log_paths import setup_logging

# Logger: nombre cambia segun modo para distinguir fuente en logs.
# Ambos modos escriben al MISMO archivo ``zc.log``.
_MODE = "web" if "--web" in sys.argv[1:] else "tray"
LOG_FILE = setup_logging(_MODE)
log = logging.getLogger(f"zc.{_MODE}")


def _resolve_icon_path() -> Path | None:
    """Ruta del .ico. Modo frozen: ``sys._MEIPASS``. Modo dev: junto al codigo."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    else:
        base = Path(__file__).parent
    icon = base / "launcher" / "icon.ico"
    return icon if icon.is_file() else None


def _read_env_int(name: str, default: int) -> int:
    """Lee una env var como int; si falla, log + default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Variable %s=%r no es int; usando default %d", name, raw, default)
        return default


def _force_utf8_streams() -> None:
    """Forzar UTF-8 en stdout/stderr/stdin en Windows.

    En modo frozen/windowed los streams son ``None``; el bloque
    ``try/except`` maneja eso sin caer en ``sys.stdout.buffer``.
    """
    if sys.platform != "win32":
        return
    for name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            continue
        except (AttributeError, Exception):
            pass
        # Fallback: reconstruir el TextIOWrapper si hay buffer.
        try:
            setattr(
                sys, name,
                io.TextIOWrapper(  # type: ignore[arg-type]
                    stream.buffer,  # type: ignore[attr-defined]
                    encoding="utf-8", errors="replace",
                ),
            )
        except (AttributeError, Exception):
            pass


def _run_cli_web_mode() -> int:
    """Modo ``--web [host:port]``: OB1 server en foreground sin bandeja.

    Bloquea el main thread hasta Ctrl+C / SIGTERM. Pensado para
    servidores headless y CI.
    """
    argv = sys.argv[1:]
    # Parsear ``--web [host:port]``.
    host_port = "127.0.0.1:8000"
    if "--web" in argv:
        idx = argv.index("--web")
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("--"):
            host_port = argv[idx + 1]
    host, _, port_str = host_port.partition(":")
    host = host or "127.0.0.1"
    port = int(port_str) if port_str else 8000

    from launcher.ob1_supervisor import Ob1ServiceSupervisor

    log.info("Modo --web: OB1 server arrancando en %s:%d.", host, port)
    web = Ob1ServiceSupervisor(host=host, port=port, tick_period_s=0.1)
    web.start()
    if not web.wait_until_alive(timeout_s=10.0):
        log.error("OB1 supervisor no arranco en 10s; abortando.")
        web.stop(timeout=2.0)
        return 1
    log.info("OB1 server vivo en http://%s:%d. Ctrl+C para parar.", host, port)

    # Bloquear main thread hasta Ctrl+C.
    shutdown = threading.Event()
    if sys.platform == "win32":
        import signal
        signal.signal(signal.SIGINT, lambda *_: shutdown.set())
        signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
    try:
        while not shutdown.is_set() and web.is_alive():
            shutdown.wait(timeout=1.0)
    except KeyboardInterrupt:
        log.info("Ctrl+C detectado; parando.")
    web.stop(timeout=5.0)
    log.info("Adios.")
    return 0


def _run_tray_mode() -> int:
    """Modo default: bandeja con icono (pystray).

    Crea el ``Ob1ServiceSupervisor`` (NO lo inicia), bloquea el main
    thread con pystray y delega start/stop a los callbacks del menu.
    """
    _force_utf8_streams()

    log.info("=" * 60)
    log.info("ZC Automation Suite (tray launcher) iniciando.")
    log.info("Python: %s | frozen=%s | pythonw=%s",
             sys.version.split()[0],
             getattr(sys, "frozen", False),
             sys.executable.endswith("pythonw.exe"))
    log.info("Log file: %s", LOG_FILE)

    from launcher.ob1_supervisor import Ob1ServiceSupervisor

    web_host = os.environ.get("ZC_WEB_HOST", "127.0.0.1")
    web_port = _read_env_int("ZC_WEB_PORT", 8000)
    tick_period_ms = _read_env_int("ZC_OB1_TICK_MS", 100)

    web = Ob1ServiceSupervisor(
        host=web_host,
        port=web_port,
        tick_period_s=tick_period_ms / 1000.0,
    )
    log.info("OB1 supervisor creado: %s:%d (tick=%dms).", web_host, web_port, tick_period_ms)
    log.info("Esperando que el operario elija Iniciar web desde el menu.")

    try:
        from launcher.tray_app import run_tray
        icon_path = _resolve_icon_path()
        run_tray(
            web, icon_path, log,
            on_before_exit=lambda: web.stop(timeout=5.0),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("El icono de bandeja falló: %s\n%s", exc, traceback.format_exc())
        log.info("Web server queda disponible. Cierre el proceso desde el Task Manager.")
        try:
            while web.is_alive():
                time.sleep(1.0)
        except KeyboardInterrupt:
            log.info("Ctrl+C detectado.")

    log.info("Cerrando OB1 supervisor...")
    web.stop(timeout=5.0)
    log.info("Adios.")
    return 0


def main() -> int:
    """Dispatch: ``--web`` -> CLI headless; sin flag -> bandeja."""
    if "--web" in sys.argv[1:]:
        return _run_cli_web_mode()
    return _run_tray_mode()


if __name__ == "__main__":
    sys.exit(main())
