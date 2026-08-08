"""Interfaces Layer - Capa de Presentación Agéntica.

Este paquete aloja los adaptadores que exponen el Gateway de TIA Portal a
distintos tipos de clientes (LLM vía FastMCP, navegador vía FastAPI, TUI,
etc.). Es la frontera del sistema con el mundo exterior.

Reglas arquitectónicas:
  - El contenido de este paquete SOLO puede importar desde
    `infrastructure/`. Nunca debe importar desde `interfaces/*` entre sí
    (evita dependencias circulares entre adaptadores).
  - Cualquier nueva interfaz (web, gRPC, CLI interactiva) se añade como
    un módulo independiente aquí (ej. `web_server.py`).
"""
