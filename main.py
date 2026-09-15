"""Único entry point del proyecto.

Modo: bandeja con icono (pystray). Click "Iniciar web" arranca
Flask + OB1 en hilos daemon. Click "Parar web" los para. Click
"Salir" cierra todo.

Lanzamientos típicos:
  - run_app.bat                            # doble click, sin consola
  - python main.py                         # consola para debug
  - python main.py --web 127.0.0.1:8000    # puerto custom
  - pythonw.exe main.py                    # sin consola (manual)

Argumentos:
  --web HOST:PORT    bind del web server (default: 127.0.0.1:9484)
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
import time
import traceback
from pathlib import Path

from core.infrastructure.config.config_paths import setup_logging

DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 9484


def _parse_web_addr(value: str) -> tuple[str, int]:
    """Parsea ``"HOST:PORT"`` o ``"PORT"`` a ``(host, port)``."""
    if ":" in value:
        host, port_str = value.rsplit(":", 1)
        return host, int(port_str)
    return DEFAULT_WEB_HOST, int(value)


def _parse_args(argv: list[str]) -> tuple[str, int]:
    """Lee ``--web HOST:PORT`` o devuelve defaults. Idempotente."""
    parser = argparse.ArgumentParser(
        prog="main.py", add_help=True,
        description="Lanza el web server de ZC Automation Suite.",
    )
    parser.add_argument(
        "--web", metavar="HOST:PORT", default=None,
        help=(
            f"Bind del web server. Formato HOST:PORT o PORT solo. "
            f"Default: {DEFAULT_WEB_HOST}:{DEFAULT_WEB_PORT}."
        ),
    )
    # ``parse_known_args`` ignora flags desconocidos (compat con futuros args).
    args, _ = parser.parse_known_args(argv)
    if args.web is None:
        return DEFAULT_WEB_HOST, DEFAULT_WEB_PORT
    try:
        return _parse_web_addr(args.web)
    except ValueError as exc:
        parser.error(f"--web invalido ({args.web!r}): {exc}")


# Parseo eager para que ``WEB_HOST`` / ``WEB_PORT`` esten disponibles
# en el scope del modulo (compat con scripts que importan ``main``).
WEB_HOST, WEB_PORT = _parse_args(sys.argv[1:])

# Un solo archivo ``zc.log`` para toda la aplicacion.
LOG_FILE = setup_logging()  # root_name = "zc"
log = logging.getLogger("zc")


def _resolve_icon_path() -> Path | None:
    """Path del .ico: ``_MEIPASS/core/launcher/icon.ico`` si frozen,
    ``<raiz>/core/launcher/icon.ico`` en dev.

    Coherente con el refactor PR 7 (todo el shell del launcher vive
    en ``core/launcher/``) y con ``build_exe.py::EXE_ICON`` /
    ``PROJECT_DATA_FILES`` (que bundlea el mismo path al .exe).
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    else:
        base = Path(__file__).parent
    icon = base / "core" / "launcher" / "icon.ico"
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
    from core.launcher.main_supervisor import MainServiceSupervisor

    # Config eager: falla rapido al arrancar si el JSON esta roto
    # o no existe, con el log ya en marcha para diagnosticar.
    config_manager = ConfigManager()
    log.info("Config cargado: %s", config_manager.path)

    web = MainServiceSupervisor(
        host=WEB_HOST,
        port=WEB_PORT,
        tick_period_s=0.1,
        config_manager=config_manager,
    )
    log.info("Supervisor creado: %s:%d (tick=100ms).", WEB_HOST, WEB_PORT)
    log.info("Esperando que el operario elija Iniciar web desde el menu.")

    try:
        from core.launcher.tray_app import run_tray
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

