"""Fat Binary Entrypoint - ZC Automation Suite (Headless Backend).

Este módulo actúa exclusivamente como enrutador CLI (Composition Root).
Su única responsabilidad es cablear las dependencias y delegar la
ejecución hacia:
  - --worker : El motor OT efímero (capa de infraestructura).
  - --mcp    : El servidor FastMCP (capa de presentación agéntica).
  - --web    : El servidor FastAPI/Uvicorn (capa de presentación web).
  - (default): --mcp por compatibilidad.

Composition Root (REGLA DE ORO):
  - ``TIAProcessGateway`` se instancia UNA SOLA VEZ por proceso.
  - Esa única instancia se inyecta en cascada hacia
    ``create_mcp_server(gateway)`` y ``create_app(gateway)``.
  - Prohibido crear múltiples gateways en el mismo proceso (cada uno
    lanzaría su propio worker OT efímero, multiplicando la presión
    sobre el RCW de TIA Portal).

Cero UI propia: no hay TUI ni bucles interactivos.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import sys
from typing import NoReturn

# ── DA-012: toggle de logging DEBUG exhaustivo ───────────────────────
# Cuando ZC_DEBUG=1, se emite log DEBUG de TODO el flujo (main,
# lifespan, gateway, worker, reader_task, heartbeat, SSE, bus,
# engine). Pensado para capturar data en el siguiente arranque del
# operario y diagnosticar el bug DA-012 (SSE que cuelga 0 bytes en
# producción con TIA real, mock funciona).
#
# Uso:
#   $ ZC_DEBUG=1 python main.py --web
#   $ ZC_DEBUG=1 python main.py --mcp
#
# El default (sin env var) NO emite DEBUG: solo WARNING+ via los
# loggers que ya estuvieran configurados (uvicorn, root). Asi el
# operario puede activar el modo cuando lo necesita sin ruido en
# operación normal.
if os.environ.get("ZC_DEBUG") == "1":
    logging.basicConfig(
        level=logging.DEBUG,
        format=(
            "%(asctime)s.%(msecs)03d [ZC_DEBUG] "
            "%(name)s %(levelname)s %(message)s"
        ),
        datefmt="%H:%M:%S",
        force=True,  # pisa basicConfig previo (uvicorn lo hace)
    )
    # Logger especifico del flow DA-012 (gateway, worker, SSE, etc.).
    # Lo activamos aunque basicConfig ya esté en DEBUG para que un
    # futuro caller pueda filtrar por nombre.
    logging.getLogger("zc.debug.da012").setLevel(logging.DEBUG)

# Forzar UTF-8 en stdout/stderr/stdin para evitar errores
# de codificacion cuando TIA Portal (via Pythonnet)
# devuelve strings con caracteres españoles (Latin-1)
# que el wrapper intenta convertir a UTF-8. Esto se hereda
# al proceso del worker (subproceso de main.py).
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        # Fallback para Python <3.7 o si falla.
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    """Parsea los flags del binario. Delgado a propósito."""
    parser = argparse.ArgumentParser(
        prog="zc_automation_suite",
        description="ZC Automation Suite CLI / Server Engine (headless).",
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Arranca la aplicación en modo Servidor FastMCP (STDIO).",
    )
    parser.add_argument(
        "--worker",
        action="store_true",
        help="Ejecuta la entrada directa al worker efímero de TIA Portal.",
    )
    parser.add_argument(
        "--web",
        nargs="?",
        const="127.0.0.1:8000",
        default=None,
        metavar="HOST:PORT",
        help=(
            "Arranca el servidor web FastAPI (default 127.0.0.1:8000). "
            "Ejemplo: --web 0.0.0.0:5000"
        ),
    )
    parser.add_argument(
        "--worker-persistent",
        action="store_true",
        help=(
            "(interno) Arranca el worker OT en modo persistente (loop). "
            "Lo invoca TIAProcessGateway(persistent=True) en modo web. "
            "El loop real se implementa en PR 3; por ahora es un "
            "NotImplementedError explicito."
        ),
    )
    return parser.parse_args()


def run_worker_mode() -> NoReturn:
    """Redirige la ejecución directa al Worker OT efímero (capa infraestructura)."""
    from core.infrastructure.tia.worker_tia import main as worker_main

    worker_main()
    sys.exit(0)


def run_mcp_mode() -> None:
    """Delega en la capa de presentación MCP (core/interfaces/mcp_server.py).

    Tras PR 6 el shell MCP vive en ``core/interfaces/mcp_server.py`` y
    agrega tools del gateway + tools aportadas por las áreas vía
    ``AreaRegistry.discover().for_each("contributes_mcp_tools", ...)``.
    """
    # Setup logging unificado ANTES de cualquier import pesado (FastMCP,
    # gateway, areas). Asi cualquier warning/import se loguea a zc.log.
    from core.application.log_paths import setup_logging
    setup_logging("mcp")

    # Importación tardía: minimiza el tiempo de arranque cuando solo se
    # necesita el modo --worker y pospone la carga de fastmcp hasta que
    # el usuario realmente invoca la herramienta IT.
    from core.interfaces.mcp_server import run_mcp_stdio

    run_mcp_stdio()


def run_web_mode(host_port: str) -> None:
    """Delega en la capa de presentación web FastAPI (interfaces/web_server/).

    Composition Root de la capa web (``interfaces/web_server/app.py``):
    ``create_app(gateway)`` recibe la única instancia de
    ``TIAProcessGateway`` y la ensambla con los routers. Aquí
    instanciamos el gateway UNA SOLA VEZ por proceso.

    Args:
        host_port: Cadena ``"host:port"`` parseable por ``uvicorn.run``.
    """
    # Importación tardía por la misma razón que en ``run_mcp_mode``.
    import uvicorn

    from interfaces.web_server.app import create_app
    from core.infrastructure.gateway import TIAProcessGateway
    from core.application.log_paths import setup_logging

    # Setup logging unificado ANTES de instanciar nada. Asi cualquier
    # warning de import (FastAPI, uvicorn, areas) se loguea a zc.log.
    setup_logging("web")
    logging.getLogger("zc.debug.da012").debug(
        "run_web_mode entry host_port=%r", host_port
    )

    # Modo web: el gateway se construye con ``persistent=True`` para
    # que en PR 3+ el worker OT corra como subproceso vivo durante
    # toda la sesión (1 attach al inicio, N comandos por el mismo
    # attach). En este PR (PR 2) el flag solo añade infraestructura
    # en el gateway; ``_dispatch_worker`` detecta el flag y lanza
    # ``NotImplementedError`` con la referencia al plan. El cambio
    # es seguro: ``persistent=False`` (default) preserva el
    # comportamiento 1-shot actual, y ``persistent=True`` no rompe
    # nada en este PR (el dispatch falla de forma explícita si se
    # intenta usar, sin pisar el modo 1-shot del MCP).
    gateway = TIAProcessGateway(persistent=True)
    logging.getLogger("zc.debug.da012").debug(
        "run_web_mode: gateway instanciado (persistent=True, pid=%s)", os.getpid()
    )

    host, _, port = host_port.partition(":")
    logging.getLogger("zc.debug.da012").debug(
        "run_web_mode: host=%s port=%s (parsed)", host or "127.0.0.1", port or "8000"
    )
    # Red de seguridad X2: aunque el lifespan de FastAPI YA llama a
    # ``gateway.disconnect()`` al shutdown (ver ``app.py::_tia_lifespan``),
    # ``uvicorn.run`` es sync y bloqueante: si crashea antes de
    # ejecutar el lifespan cleanup, el subproceso del worker
    # persistente quedaría zombi (~200 MB con ``siemens_tia_scripting.pyd``
    # cargado) hasta que se cierre TIA o se mate manualmente. Por eso
    # delegamos en la versión async y envolvemos en try/finally.
    asyncio.run(_run_web_mode_async(gateway, host or "127.0.0.1", int(port) if port else 8000))


async def _run_web_mode_async(
    gateway: TIAProcessGateway, host: str, port: int
) -> None:
    """Implementación async de ``run_web_mode`` con cleanup garantizado.

    Separada de ``run_web_mode`` para poder envolver el ``uvicorn.Server.serve``
    en un ``try/finally`` que llame a ``gateway.disconnect()`` al
    terminar (red de seguridad X2). El lifespan de FastAPI ya cubre
    el caso normal; este finally cubre el crash pre-lifespan.
    """
    import uvicorn

    from interfaces.web_server.app import create_app

    _dbg = logging.getLogger("zc.debug.da012")
    _dbg.debug("_run_web_mode_async entry: creando app FastAPI")

    app = create_app(gateway)
    _dbg.debug("_run_web_mode_async: app FastAPI creada, routers montados")

    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    _dbg.debug(
        "_run_web_mode_async: uvicorn.Server listo, await server.serve() (bloquea hasta shutdown)"
    )
    try:
        await server.serve()
    finally:
        _dbg.debug("_run_web_mode_async: server.serve() retorno, entrando a finally")
        try:
            await gateway.disconnect()
            _dbg.debug("_run_web_mode_async: gateway.disconnect() OK")
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "gateway.disconnect() en main fallo: %s", exc
            )


def main() -> None:
    logging.getLogger("zc.debug.da012").debug(
        "main() entry: argv=%r sys.executable=%r", sys.argv, sys.executable
    )
    args = parse_args()

    if args.worker_persistent:
        # Modo persistente del worker (PR 2/3): el subproceso entra
        # en ``main_persistent_loop()`` (placeholder en este PR; loop
        # real en PR 3). El flag CLI existe para que el gateway en
        # modo web pueda invocar ``main.py --worker-persistent`` sin
        # que ``argparse`` rechace el argumento.
        from core.infrastructure.tia.worker_tia import main_persistent_loop

        main_persistent_loop()
        sys.exit(0)
    if args.worker:
        run_worker_mode()
        return
    if args.web is not None:
        run_web_mode(args.web)
        return
    # Por defecto (sin flags o con --mcp) -> capa de presentación MCP.
    run_mcp_mode()


if __name__ == "__main__":
    main()
