"""Interfaces Layer - Web Server (FastAPI).

Adaptador web alternativo al MCP: expone los mismos servicios del
subdominio alimentación vía HTTP/REST + UI HTML mínima.

Arquitectura:
  - Esta capa SOLO importa desde ``infrastructure/`` (nunca de
    ``interfaces/mcp_server`` ni ``interfaces/web_server`` entre sí).
  - Recibe UNA instancia Singleton de ``TIAProcessGateway``
    (Composition Root) por inyección de dependencias.

Comandos expuestos:
  - ``POST /api/v1/portal/attach``     → gateway.attach_portal()
  - ``POST /api/v1/portal/open-new``   → gateway.open_new_portal(project_file_path)
  - ``POST /api/v1/dispositivos/dimensions`` → SyncDispositivosDimensionsUseCase
  - ``POST /api/v1/dispositivos/instances``   → SyncDispositivosInstancesUseCase
  - ``GET  /``                         → UI HTML simple (formulario)
"""
