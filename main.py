"""Fat Binary Entrypoint - ZC Automation Suite (Headless Backend).

Este módulo actúa exclusivamente como enrutador CLI (Composition Root).
Su única responsabilidad es cablear las dependencias y delegar la
ejecución hacia:
  - --worker : El motor OT efímero (capa de infraestructura).
  - (default): Las capas de presentación IT (interfaces/mcp_server.py).
  - --mcp    : Alias explícito de la capa MCP (compatibilidad).

Cero UI propia: no hay TUI ni bucles interactivos. Toda la presentación
es responsabilidad de los adaptadores de `interfaces/`.
"""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn


def parse_args() -> argparse.Namespace:
    """Parsea los flags del binario. Delgado a propósito."""
    parser = argparse.ArgumentParser(
        prog="zc_automation_suite",
        description="ZC Automation Suite CLI / Server Engine (headless).",
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Arranca la aplicación en modo Servidor FastMCP (STDIO). Es el modo por defecto.",
    )
    parser.add_argument(
        "--worker",
        action="store_true",
        help="Ejecuta la entrada directa al worker efímero de TIA Portal.",
    )
    return parser.parse_args()


def run_worker_mode() -> NoReturn:
    """Redirige la ejecución directa al Worker OT efímero (capa infraestructura)."""
    from infrastructure.tia.worker_tia import main as worker_main

    worker_main()
    sys.exit(0)


def run_mcp_mode() -> None:
    """Delega en la capa de presentación MCP (interfaces/mcp_server.py)."""
    # Importación tardía: minimiza el tiempo de arranque cuando solo se
    # necesita el modo --worker y pospone la carga de fastmcp hasta que
    # el usuario realmente invoca la herramienta IT.
    from interfaces.mcp_server import run_mcp_stdio

    run_mcp_stdio()


def main() -> None:
    args = parse_args()

    if args.worker:
        run_worker_mode()
    else:
        # Por defecto (sin flags o con --mcp) -> capa de presentación MCP.
        run_mcp_mode()


if __name__ == "__main__":
    main()
