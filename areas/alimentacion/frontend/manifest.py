"""Manifest del área "alimentacion" para el endpoint REST de la SPA.

Espejo Python del módulo ``manifest.js`` (mismo shape, mismas keys,
misma estructura ``components`` y ``views``). La diferencia es que
los ``loaders`` aquí son **strings** (URLs HTTP) en lugar de
funciones ``() => import(...)`` — son serializables a JSON y los
devuelve el endpoint ``GET /api/v1/areas/alimentacion/manifest``
del backend.

La SPA los ``import()`` directamente como módulos ESM. El prefijo
``/static/areas/alimentacion/`` se sirve desde el FastAPI (un
``StaticFiles`` que apunta a ``STATIC_DIR / "areas"``; ver
``core/interfaces/web_server/app.py``).

Si en el futuro se añade un área nueva:
  1. Crear ``areas/<nueva>/frontend/components/`` con los .js de
     Vue 3 del área (cada uno con un ``name:`` único).
  2. Crear ``areas/<nueva>/frontend/manifest.js`` (módulo JS que
     exporta ``build()`` y los loaders ``() => import(...)``; lo
     usa el SPA si decide bypasear el endpoint).
  3. Crear ``areas/<nueva>/frontend/manifest.py`` (este archivo,
     espejo Python que devuelve URLs strings).
  4. Añadir ``contributes_frontend_manifest=build_manifest`` a la
     ``AREA_SPEC`` del ``__init__.py`` del área.
  5. El backend (``core/interfaces/web_server/routers/area_manifests.py``
     o equivalente) itera el ``AreaRegistry`` y serializa el dict
     que devuelve ``build()`` a JSON.

Importante: NO referenciar ``manifest.js`` desde aquí. Son
hermanos, no padre/hijo. El backend solo necesita strings.
"""
from __future__ import annotations

# Prefijo HTTP desde el que el FastAPI sirve los .js de las áreas.
# Se mantiene como constante (no se lee de config) porque es parte
# del contrato estático de la SPA: el shell ``area-loader.js``
# confía en que las URLs del manifest son absolutas y empiezan por
# este prefijo. Cambiar este valor implica cambiar también el
# router de static files del backend y el ``app.mount`` que lo
# registra.
_STATIC_PREFIX = "/static/areas/alimentacion/frontend"


def build() -> "AreaFrontendManifest":
    """Devuelve el manifest del área "alimentacion" serializable.

    Shape (ver ``AreaFrontendManifest`` en
    ``core/application/area_registry.py`` para el TypedDict):
        {
            "id":     "alimentacion",
            "label":  "Alimentación",
            "icon":   "🍞",
            "components": {
                "sidebar": "<ComponentName>",
                "landing": "<ComponentName>",
                "views":    { "<key>": "<ComponentName>", ... },
            },
            "loaders": {
                "<ComponentName>": "<url absoluta>",
                ...
            },
        }

    La SPA (``core/interfaces/web_server/static/js/area-loader.js``)
    consume este dict y hace ``import(<url>)`` para cada loader.
    El ``<ComponentName>`` coincide con el ``name:`` declarado en
    cada componente Vue 3 (``Sidebar.js`` → ``"AlimentacionSidebar"``).

    Si se añade un componente al área, hay que:
      1. Crear el .js con un ``name:`` único.
      2. Añadirlo al dict ``_loaders`` aquí Y al objeto ``_comps``
         de ``manifest.js`` (espejo JS).
      3. Si es una sub-vista nueva, añadir su key al dict ``_views``.
    """
    from core.application.area_registry import AreaFrontendManifest

    _manifest: AreaFrontendManifest = {
        "id": "alimentacion",
        "label": "Alimentación",
        "icon": "🍞",
        "components": {
            "sidebar": "AlimentacionSidebar",
            "landing": "AreaLanding",
            "views": {
                "landing": "AreaLanding",
                "def":     "DefinicionProgramacion",
                "disp":    "Dispositivos",
                "cache":   "BloquesCacheView",
            },
        },
        "loaders": {
            "AlimentacionSidebar":    f"{_STATIC_PREFIX}/components/Sidebar.js",
            "AreaLanding":            f"{_STATIC_PREFIX}/components/AreaLanding.js",
            "DefinicionProgramacion": f"{_STATIC_PREFIX}/components/DefinicionProgramacion.js",
            "Dispositivos":           f"{_STATIC_PREFIX}/components/Dispositivos.js",
            "BloquesCacheView":       f"{_STATIC_PREFIX}/components/BloquesCacheView.js",
        },
    }
    return _manifest


__all__ = ["build"]
