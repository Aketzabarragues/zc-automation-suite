"""Manifest del area ``tia_conexion``.

Este modulo **NO** es un ``manifest.js`` que la SPA importa: es un
modulo Python que el router ``GET /api/v1/areas/tia_conexion/manifest``
ejecuta en el servidor llamando a ``build()``.

Decision de diseno (importante, ver ``core/web/routers/areas.py``):
  El manifest es un ``dict`` Python serializado a JSON. Esto evita
  meter ``js2py`` / ``PyExecJS`` / etc. en el .exe de PyInstaller
  (prohibido por .clinerules §1: solo ``core.worker`` carga el SDK
  de Siemens). La SPA recibe el dict y luego resuelve los
  ``loaders`` (URLs absolutas a ``.js``) en el navegador con
  ``import(url)``, igual que hacia el ``area-loader.js`` del legacy.

Shape del dict:
    {
        "id":        str,           # mismo que AreaSpec.key
        "label":     str,           # mismo que AreaSpec.label
        "icon":      str,           # mismo que AreaSpec.icon
        "components": {
            "sidebar": str | None,  # nombre del componente o None
            "landing": str,         # nombre del componente principal
            "views":   { name: str },  # mapa nombre -> componente
        },
        "loaders": {
            # nombre del componente -> URL absoluta al .js
            # que FastAPI sirve como static file.
            "ConexionTIAView": "/areas/tia_conexion/frontend/components/ConexionTIAView.js",
        },
    }

Importante: el Agente A (frontend) crea ``ConexionTIAView.js`` y
lo sirve FastAPI montando ``areas/`` como static dir. Si el .js
aun no existe cuando arrancamos la app, el endpoint de manifest
sigue funcionando (solo falla el ``import()`` del lado SPA).
"""
from __future__ import annotations

from typing import Any

# Prefijo de URL para los loaders. **Debe coincidir** con el
# ``app.mount(...)`` que el Agente A anyade en ``core/web/app.py``
# para servir ``areas/`` como static files. En Fase 3 no esta
# montado aun (el endpoint devuelve el manifest OK, pero el
# ``import()`` del SPA fallara hasta que Agente A integre el
# mount). Documentamos el contrato aqui para que ambos agentes
# esten sincronizados.
_LOADER_PREFIX = "/areas/tia_conexion/frontend/components"


def build() -> dict[str, Any]:
    """Construye el manifest del area ``tia_conexion``.

    Returns:
        ``dict`` con el shape documentado en el module docstring.

    Note:
        Los ``loaders`` son **URLs absolutas** (comienzan con
        ``/areas/...``) para que el ``area-loader.js`` del Agente A
        pueda hacer ``import(url)`` directamente sin construirlas.
    """
    return {
        "id": "tia_conexion",
        "label": "Conexion TIA",
        "icon": "🔌",
        "components": {
            "sidebar": None,                # sin sidebar propio en esta area
            "landing": "ConexionTIAView",   # vista principal
            "views": {
                "main": "ConexionTIAView",
            },
        },
        "loaders": {
            "ConexionTIAView": (
                f"{_LOADER_PREFIX}/ConexionTIAView.js"
            ),
        },
    }
