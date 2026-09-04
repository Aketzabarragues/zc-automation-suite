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
import io
import sys
from typing import NoReturn

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
    app = create_app(gateway)

    host, _, port = host_port.partition(":")
    uvicorn.run(
        app,
        host=host or "127.0.0.1",
        port=int(port) if port else 8000,
    )


def main() -> None:
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
