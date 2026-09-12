"""main_ob1.py — entrypoint OB1 del CLI (Fase 4 / paso 4.5.1).

Complementario a ``main.py`` (FastAPI async). Mientras ``main.py`` sigue
siendo el modo legacy, ``main_ob1.py`` arranca la nueva arquitectura
OB1 (sync + Flask):

  1. Carga el wrapper siemens_tia_scripting.pyd via SyncTIAClient
     (placeholder: en 4.5.2+ se conecta al TIA real).
  2. Registra comandos core (register_core_commands) y del area
     (register_ob1).
  3. Arranca Flask en un hilo daemon (werkzeug.serving.make_server).
  4. Entra al loop OB1 en el hilo principal: dispatch TIA + run_cycle
     engine + sleep 100ms.
  5. Ctrl+C detiene limpio ambos (daemon Flask muere al salir main).

Uso:
    python main_ob1.py --web 127.0.0.1:8000

Estado (sept-2026): skeleton minimo. La carga real del wrapper .pyd,
el wiring con las areas, y la conversion de gateway.py a tia_client.py
queda para pasos posteriores de DA-014.

Trade-off aceptado: single-threaded (Flask dev server + OB1 loop en
main thread). Requests HTTP serializan contra el ciclo OB1 (mismo
loop, 10 Hz). Para la carga esperada (1 operario, <10 req/s) es OK.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from typing import NoReturn

from werkzeug.serving import make_server

from core.application.log_paths import setup_logging
from core.infrastructure.tia_client import (
    SyncTIAClient,
    register_core_commands,
)
from core.plc.engine import Engine
from core.sse.event_bus_sync import EventBusSync
from interfaces.web_server.app_flask import create_app


logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main_ob1",
        description="zc-automation-suite — modo OB1 (Fase 4 / DA-014).",
    )
    parser.add_argument(
        "--web",
        dest="host_port",
        default="127.0.0.1:5000",
        help="host:port para Flask. Default: 127.0.0.1:5000",
    )
    parser.add_argument(
        "--tick-period-ms",
        type=int,
        default=100,
        help="Periodo del OB1 main loop en ms. Default: 100 (10 Hz).",
    )
    parser.add_argument(
        "--no-engine",
        action="store_true",
        help="Desactiva el engine (solo tick TIA client).",
    )
    return parser.parse_args(argv)


_shutdown_event = threading.Event()


def _request_shutdown(signum: int, frame) -> None:
    """Signal handler: marca shutdown_event. El OB1 loop lo ve y sale."""
    logger.info("main_ob1: signal %d received, requesting shutdown.", signum)
    _shutdown_event.set()


def run_web_ob1_mode(host_port: str, tick_period_s: float, no_engine: bool) -> None:
    """Arranca Flask daemon + OB1 main loop en hilo principal."""
    setup_logging("web-ob1")
    logger.info(
        "run_web_ob1_mode entry: host_port=%s tick=%dms no_engine=%s",
        host_port,
        int(tick_period_s * 1000),
        no_engine,
    )

    # Componentes core.
    tia_client = SyncTIAClient()
    register_core_commands(tia_client)
    engine = Engine(tick_period_s=tick_period_s) if not no_engine else None
    event_bus = EventBusSync()

    # Flask en hilo daemon.
    flask_app = create_app(
        tia_client=tia_client,
        engine=engine,
        event_bus=event_bus,
    )
    host, _, port_str = host_port.partition(":")
    port = int(port_str) if port_str else 5000

    server = make_server(
        host=host or "127.0.0.1",
        port=port,
        app=flask_app,
        threaded=False,  # single-threaded: serializa contra OB1
    )
    flask_thread = threading.Thread(
        target=server.serve_forever,
        name="flask-daemon",
        daemon=True,
    )
    flask_thread.start()
    logger.info(
        "main_ob1: Flask daemon started on http://%s:%d (PID=%d)",
        host or "127.0.0.1",
        port,
        threading.get_ident(),
    )

    # Signal handlers para shutdown limpio.
    signal.signal(signal.SIGINT, _request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_shutdown)

    # OB1 main loop en hilo principal.
    print(f"[main_ob1] OB1 loop @ {int(tick_period_s * 1000)}ms on http://{host or '127.0.0.1'}:{port}")
    print("[main_ob1] Ctrl+C to stop.")
    try:
        while not _shutdown_event.is_set():
            # 1. Drenar cola TIA (commands submitted por Flask thread).
            tia_client.dispatch_pending()
            # 2. Tick engine.
            if engine is not None:
                try:
                    engine.run_cycle()
                except Exception:
                    logger.exception("OB1 loop: engine.run_cycle() failed")
            # 3. Sleep (cede CPU al Flask daemon y otros hilos).
            time.sleep(tick_period_s)
    except KeyboardInterrupt:
        logger.info("main_ob1: KeyboardInterrupt received.")
    finally:
        _shutdown_event.set()
        logger.info("main_ob1: shutting down Flask daemon...")
        server.shutdown()
        logger.info("main_ob1: bye.")


def main(argv: list[str] | None = None) -> NoReturn:
    args = parse_args(argv)
    run_web_ob1_mode(
        host_port=args.host_port,
        tick_period_s=args.tick_period_ms / 1000.0,
        no_engine=args.no_engine,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
