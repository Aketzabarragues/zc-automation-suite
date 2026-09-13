"""Único entry point del proyecto.

Modo: bandeja con icono (pystray). Click "Iniciar web" arranca
Flask + OB1 en hilos daemon. Click "Parar web" los para. Click
"Salir" cierra todo.

Lanzamientos típicos:
  - run_app.bat            # doble click, sin consola
  - python main.py         # consola para debug
  - pythonw.exe main.py    # sin consola (manual)
"""
from __future__ import annotations

import io
import logging
import sys
import time
import traceback
from pathlib import Path

from core.application.log_paths import setup_logging

WEB_PORT = 9484  # puerto fijo del web server (Flask + OB1 main loop)

# Un solo archivo ``zc.log`` para toda la aplicacion.
LOG_FILE = setup_logging()  # root_name = "zc"
log = logging.getLogger("zc")


def _resolve_icon_path() -> Path | None:
    """Path del .ico: ``_MEIPASS`` si frozen, junto al codigo en dev."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    else:
        base = Path(__file__).parent
    icon = base / "launcher" / "icon.ico"
    return icon if icon.is_file() else None


def _force_utf8_streams() -> None:
    """UTF-8 en stdout/stderr/stdin en Windows.

    Tolera streams ``None`` (modo windowed de PyInstaller).
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
            # Fallback: reconstruir el TextIOWrapper si el stream tiene buffer.
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

    Start/stop del web + OB1 main loop se hace via callbacks del menu.
    ``on_before_exit`` para el web server antes de quitar el icono.
    Si pystray falla, el web queda vivo hasta Ctrl+C.
    """
    _force_utf8_streams()

    log.info("=" * 60)
    log.info("ZC Automation Suite (bandeja) iniciando.")
    log.info("Python: %s | frozen=%s | pythonw=%s",
             sys.version.split()[0],
             getattr(sys, "frozen", False),
             sys.executable.endswith("pythonw.exe"))
    log.info("Log file: %s", LOG_FILE)

    from core.infrastructure.config.config_manager import ConfigManager
    from launcher.main_supervisor import MainServiceSupervisor

    # Config eager: falla rapido al arrancar si el JSON esta roto
    # o no existe, con el log ya en marcha para diagnosticar.
    config_manager = ConfigManager()
    log.info("Config cargado: %s", config_manager.path)

    web = MainServiceSupervisor(
        host="127.0.0.1",
        port=WEB_PORT,
        tick_period_s=0.1,
        config_manager=config_manager,
    )
    log.info("Supervisor creado: 127.0.0.1:%d (tick=100ms).", WEB_PORT)
    log.info("Esperando que el operario elija Iniciar web desde el menu.")

    try:
        from launcher.tray_app import run_tray
        run_tray(
            web, _resolve_icon_path(), log,
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

    log.info("Cerrando supervisor...")
    web.stop(timeout=5.0)
    log.info("Adios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

