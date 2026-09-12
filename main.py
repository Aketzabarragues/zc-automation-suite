"""Composition Root del launcher (modo dev) con system tray.

Este módulo es el **único entry point** del proyecto (Fase 4 / DA-014,
sept-2026). El operario lo usa así:

    Doble clic sobre run_tray.bat   # ← SIN consola (recomendado)
    pythonw.exe main.py             # ← SIN consola (manual)
    python main.py                  # ← CON consola (debug)

Modos disponibles (Fase 4 / DA-014, sept-2026):
  - default              -> Bandeja con icono (pystray). Click en
                           "Iniciar web" arranca Flask + OB1 main loop
                           en hilos daemon. Click "Parar web" los para.
  - ``--web [host:port]`` -> CLI headless: Flask + OB1 sin bandeja.
                           Ctrl+C para parar.
  - ``--mcp``             -> Servidor FastMCP STDIO (legacy gateway).
  - ``--worker``          -> Modo subproceso OT 1-shot (lo invoca el
                           gateway legacy). NO instancia bandeja.
  - ``--worker-persistent`` -> Modo subproceso OT persistente (loop).
                           NO instancia bandeja.

Responsabilidades exclusivas de esta capa:
  1. Configurar logging a fichero (unificado en ``zc.log``).
  2. Parsear CLI args y dispatch al modo correspondiente.
  3. En modo bandeja: crear ``Ob1ServiceSupervisor`` (NO iniciarlo),
     bloquear main thread con pystray, y delegar start/stop a los
     callbacks del menu (Iniciar/Parar web).
  4. En modo --web: arrancar ``Ob1ServiceSupervisor`` en foreground,
     bloquear main thread hasta Ctrl+C.

Lo que esta capa NO hace:
  - NO instancia ``SyncTIAClient``, ``Engine``, ``EventBusSync`` ni
    Flask directamente. Lo hace ``Ob1ServiceSupervisor`` (separación
    composition root / runtime lifecycle).
  - NO lanza subprocesos TIA. OB1 elimina el patrón process-per-call:
    el wrapper se llama directamente via ``SyncTIAClient``, en el
    mismo proceso que Flask y el OB1 main loop.
  - NO modifica nada de ``application/``, ``core/``, ``infrastructure/``
    ni ``interfaces/``.

Nombre histórico: este archivo se llamaba ``main_tray.py`` hasta
sept-2026. Se renombro a ``main.py`` para reflejar que es el UNICO
entry point (el resto de mains legacy — FastAPI, OB1 CLI — se borraron
en 4.N5 y 4.N6).
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

    # ── Dispatch --web [host:port] (CLI OB1 headless, sin bandeja) ─
    # Modo CLI para servidores headless / integracion continua: arranca
    # Flask + OB1 main loop directamente, sin icono de bandeja. Ctrl+C
    # para parar. Migrado de ``main_ob1.py`` (4.N5, sept-2026) tras
    # eliminar main_ob1.py como entry point independiente.
    if "--web" in sys.argv[1:]:
        return _run_cli_web_mode()

    # ── Dispatch --mcp (CLI MCP STDIO) ─
    # Migrado de ``main.py`` (4.N6, sept-2026). El servidor MCP usa
    # el gateway legacy (``TIAProcessGateway``) hasta migrar FBs y
    # use cases a ``tia_client``. Por eso este modo sigue cargando
    # ``run_mcp_stdio`` del modulo legacy.
    if "--mcp" in sys.argv[1:]:
        return _run_cli_mcp_mode()

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
    # pero la llamada se quedo en este punto y rompia main.main()
    # con NameError. Fix sept-2026: quitar la llamada).
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


# ── Modos CLI (sin bandeja) ──────────────────────────────────────
# Migrados desde ``main_ob1.py`` (--web) y ``main.py`` (--mcp) en
# sept-2026 (Fase 4 / 4.N5-4.N6). main.py es ahora el UNICO
# entry point del proyecto.


def _run_cli_web_mode() -> int:
    """Modo ``--web [host:port]``: OB1 server sin bandeja.

    Bloquea el main thread hasta Ctrl+C. Usado para servidores headless
    y para integracion continua (sin GUI). Migrado de main_ob1.py.

    Returns:
        Exit code (0 limpio, !=0 si falla).
    """
    # Parsear host:port del CLI (manual para no depender de argparse).
    host_port = "127.0.0.1:5000"
    tick_period_ms = _read_env_int("ZC_OB1_TICK_MS", 100)
    argv = sys.argv[1:]
    if "--web" in argv:
        idx = argv.index("--web")
        # Si --web lleva argumento explicito, lo usamos.
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("--"):
            host_port = argv[idx + 1]
    if "--tick-period-ms" in argv:
        idx = argv.index("--tick-period-ms")
        if idx + 1 < len(argv):
            tick_period_ms = _read_env_int("--tick-period-ms", tick_period_ms)
            try:
                tick_period_ms = int(argv[idx + 1])
            except ValueError:
                pass
    if "--no-engine" in argv:
        no_engine = True
    else:
        no_engine = False

    host, _, port_str = host_port.partition(":")
    host = host or "127.0.0.1"
    port = int(port_str) if port_str else 5000

    log.info(
        "Modo --web: OB1 server arrancando en %s:%d (tick=%dms, engine=%s).",
        host, port, tick_period_ms, "OFF" if no_engine else "ON",
    )

    from launcher.ob1_supervisor import Ob1ServiceSupervisor

    web = Ob1ServiceSupervisor(
        host=host,
        port=port,
        tick_period_s=tick_period_ms / 1000.0,
        no_engine=no_engine,
    )
    web.start()
    if not web.wait_until_alive(timeout_s=10.0):
        log.error("OB1 supervisor no arranco en 10s; abortando.")
        web.stop(timeout=2.0)
        return 1

    log.info("OB1 server vivo en http://%s:%d. Ctrl+C para parar.", host, port)

    # Bloquear main thread hasta Ctrl+C.
    shutdown = threading.Event()

    def _on_signal(signum, _frame):
        log.info("Signal %d recibido; parando OB1 supervisor.", signum)
        shutdown.set()

    if sys.platform == "win32":
        import signal
        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)

    try:
        while not shutdown.is_set() and web.is_alive():
            shutdown.wait(timeout=1.0)
    except KeyboardInterrupt:
        log.info("Ctrl+C detectado; parando.")

    web.stop(timeout=5.0)
    log.info("Adios.")
    return 0


def _run_cli_mcp_mode() -> int:
    """Modo ``--mcp``: MCP STDIO server sin bandeja.

    Migrado de main.py. Por ahora delega en el modulo legacy
    (``core/interfaces/mcp_server.run_mcp_stdio``) porque las tools
    MCP usan el gateway async legacy. Cuando los use cases migrados
    a ``tia_client`` (Fase 4.6+), este modo tambien migra a OB1.

    Returns:
        Exit code (0 limpio, !=0 si falla).
    """
    log.info("Modo --mcp: arrancando FastMCP STDIO (legacy gateway).")
    from core.interfaces.mcp_server import run_mcp_stdio
    run_mcp_stdio()
    return 0


if __name__ == "__main__":
    sys.exit(main())
