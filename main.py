"""Único entry point del proyecto.

Modo: bandeja con icono (pystray). Click en "Iniciar web" arranca
Flask + OB1 main loop en hilos daemon. Click "Parar web" los para.
Click "Salir" cierra todo.

Lanzamientos típicos:
  - run_app.bat            # doble click, sin consola
  - python main.py         # consola para debug
  - pythonw.exe main.py    # sin consola (manual)
"""
from __future__ import annotations

import io
import logging
import sys
import threading
import time
import traceback
from pathlib import Path

from core.application.log_paths import setup_logging

# Puerto fijo del web server (Flask + OB1 main loop).
WEB_PORT = 9484

# Setup logging ANTES de cualquier import pesado.
# Un solo archivo ``zc.log`` para toda la aplicacion (bandeja + web + TIA).
LOG_FILE = setup_logging("tray")
log = logging.getLogger("zc.tray")


def _resolve_icon_path() -> Path | None:
    """Path del .ico. Modo frozen: ``sys._MEIPASS``. Modo dev: junto al codigo."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    else:
        base = Path(__file__).parent
    icon = base / "launcher" / "icon.ico"
    return icon if icon.is_file() else None


def _force_utf8_streams() -> None:
    """Forzar UTF-8 en stdout/stderr/stdin en Windows.

    En modo frozen/windowed los streams son ``None``; el bloque
    ``try/except`` lo maneja sin caer en ``sys.stdout.buffer``.
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


def main() -> int:
    """Crea el supervisor OB1 y bloquea main thread con pystray.

    El supervisor arranca/parar Flask + OB1 main loop via callbacks
    del menu. ``on_before_exit`` se dispara antes de detener el icono
    para cerrar el web server en orden. Si pystray falla, el web
    server queda vivo (red de seguridad) hasta Ctrl+C.
    """
    _force_utf8_streams()

    log.info("=" * 60)
    log.info("ZC Automation Suite (bandeja) iniciando.")
    log.info("Python: %s | frozen=%s | pythonw=%s",
             sys.version.split()[0],
             getattr(sys, "frozen", False),
             sys.executable.endswith("pythonw.exe"))
    log.info("Log file: %s", LOG_FILE)

    from launcher.ob1_supervisor import Ob1ServiceSupervisor

    web = Ob1ServiceSupervisor(host="127.0.0.1", port=WEB_PORT, tick_period_s=0.1)
    log.info("OB1 supervisor creado: 127.0.0.1:%d (tick=100ms).", WEB_PORT)
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


if __name__ == "__main__":
    sys.exit(main())
