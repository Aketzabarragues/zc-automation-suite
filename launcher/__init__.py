"""Capa de launcher (system tray + control de servicios) para la app.

NO contiene lógica de aplicación. Solo infraestructura de control:
  - ``tray_app``         → system tray icon + menú dinámico
                           (Iniciar/Parar web, Iniciar/Parar MCP,
                            Estado, Salir).
  - ``web_supervisor``   → supervisor del web server FastAPI con
                           auto-restart (hilo daemon).
  - ``mcp_supervisor``   → supervisor del MCP server (HTTP/SSE) con
                           auto-restart (hilo daemon).
  - ``make_icon``        → genera ``launcher/icon.ico`` placeholder.

El entry point dev es ``main_tray.py`` (en la raíz del repo).
NO es el composition root de la app (ese sigue siendo ``main.py``).

Nota sobre el nombre del paquete:
  Originalmente se llamó ``packaging`` pero el paquete PyPI ``packaging``
  es dependencia transitiva de ``pyinstaller``. Mantener el nombre
  reservaba futuros conflictos de namespace si el repo crece.
  Renombrado a ``launcher/`` por claridad y para evitar el riesgo.
"""
