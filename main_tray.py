"""Composition Root del launcher (modo dev) con system tray.

Este módulo es el **único entry point** del proyecto (Fase 4 / DA-014,
sept-2026). Reemplaza a ``main.py`` (legacy FastAPI/uvicorn) y a
``main_ob1.py`` (modo CLI). El operario lo usa así:

    Doble clic sobre run_tray.bat   # ← SIN consola (recomendado)
    pythonw.exe main_tray.py        # ← SIN consola (manual)
    python main_tray.py             # ← CON consola (debug)

Responsabilidades exclusivas de esta capa:
  1. Configurar logging a fichero.
  2. Leer variables de entorno para host/puerto del web server.
  3. Crear el ``Ob1ServiceSupervisor`` (NO iniciarlo — el operario
     decide haciendo click en "Iniciar web" en el menú de bandeja).
  4. Bloquear el main thread con el icono de bandeja (pystray lo
     requiere así en Windows).
  5. Al pulsar "Iniciar web", arranca Flask + OB1 main loop en hilos
     daemon. Al pulsar "Parar web" o "Salir", los detiene limpiamente.

Lo que esta capa NO hace:
  - NO instancia el gateway directamente (lo hace el supervisor OB1 al
    construir la app Flask).
  - NO lanza workers persistentes: el patrón OB1 los elimina de raíz
    (TIA wrapper se llama directamente via ``SyncTIAClient``, sin
    subproceso).
  - NO modifica nada de ``application/``, ``core/``, ``infrastructure/``
    ni ``interfaces/``.

Dispatch ``--worker`` y ``--worker-persistent``: cuando el binario se
invoca con esos flags, este entry point se transforma en el subproceso
OT (modo dev o frozen indistintamente). Ver bloque más abajo.
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
# Desde DA-013 unificamos: setup_logging() en core.application.log_paths
# escribe a UN SOLO archivo ``zc.log`` (mismo que ``--web`` y ``--mcp``).
# Modo "tray" se ve como ``[zc.tray]`` en cada línea del log.
# Override por ``ZC_LOG_DIR``, fallback a
# ``%LocalAppData%\zc-automation-suite\logs\``. ZC_DEBUG=1 activa DEBUG.
# Importante: setup_logging() se llama AQUÍ (no arriba) porque debe
# quedar lista ANTES de cargar modulos pesados.

from core.application.log_paths import setup_logging  # noqa: E402

LOG_FILE = setup_logging("tray")
log = logging.getLogger("zc.tray")


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
    # ── Dispatch --worker-persistent (subprocess OT persistente) ANTES de --worker ─
    # El flag ``--worker-persistent`` lo usa TIAProcessGateway cuando
    # se construye con ``persistent=True`` (modo web, PR 3+). El
    # subproceso del worker debe entrar en ``main_persistent_loop()``
    # (loop de N comandos por stdin/stdout con 1 attach al inicio).
    # En este PR (PR 2) el loop es un ``NotImplementedError`` con
    # la referencia al plan; en PR 3 será el loop real.
    #
    # Importante: comprobar ``--worker-persistent`` ANTES que
    # ``--worker`` porque en argparse la cadena ``--worker-persistent``
    # NO es igual a ``--worker`` (sigue siendo una cadena distinta),
    # pero queremos ser explícitos sobre la precedencia: si el
    # binario frozen se invoca con ``--worker-persistent`` (modo web),
    # ese es el dispatch correcto, no el 1-shot.
    if "--worker-persistent" in sys.argv[1:]:
        from core.infrastructure.tia.worker_tia import main_persistent_loop

        main_persistent_loop()
        return 0

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

    # NOTA: setup_logging('tray') ya configura streams correctamente
    # para modo windowed (no crea StreamHandler(sys.stdout) si stdout
    # es None). Ver core/application/log_paths.py. Por eso no hace
    # falta un redirect adicional aqui (commit 2279887 lo elimino,
    # pero la llamada se quedo en este punto y rompia main_tray.main()
    # con NameError. Fix sept-2026: quitar la llamada).
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
    log.info(
        "OB1 supervisor creado: %s:%d (tick=%dms).",
        web_host,
        web_port,
        tick_period_ms,
    )
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

    log.info("Cerrando OB1 supervisor...")
    web.stop(timeout=5.0)
    log.info("Adios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
