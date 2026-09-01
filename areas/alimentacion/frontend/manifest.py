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

El dict ``loaders`` registra TANTO las sub-vistas del sidebar
(``AlimentacionSidebar``, ``AreaLanding``, ``DefinicionProgramacion``,
``Dispositivos``, ``BloquesCacheView``) como los **sub-componentes
internos** que una sub-vista compone (``MainTabs``,
``DispositivosPanel``, ``ProcesosPanel``). Sin estos últimos, la
SPA falla en runtime con ``Failed to resolve component`` en
cuanto el operario navega a "Definición programación", porque el
``<main-tabs>`` / ``<dispositivos-panel>`` / ``<procesos-panel>``
del template no se ha registrado con ``app.component(...)``.

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
      3. Si es una sub-vista nueva (entrada en el Sidebar), añadir
         su key al dict ``_views``. Si es un sub-componente interno
         de una sub-vista (como ``MainTabs``/``DispositivosPanel``/
         ``ProcesosPanel`` dentro de ``DefinicionProgramacion``),
         **NO** se añade a ``_views``; basta con registrar el
         loader.

    Sub-componentes internos actuales (registrados en ``loaders``
    pero NO en ``views``):
      - ``MainTabs``:           strip de los 2 tabs principales
                                (Dispositivos | Procesos) de
                                ``DefinicionProgramacion``.
      - ``DispositivosPanel``:  panel de la pestaña "Dispositivos"
                                (sub-tabs ED|EA|SA|V|M|MVF + tabla).
      - ``ProcesosPanel``:      panel de la pestaña "Procesos"
                                (sub-tabs Procesos|PInt|PReal|Alarmas
                                + 4 tablas).

    Sub-vistas de primer nivel (registradas TANTO en ``loaders``
    COMO en ``views``):
      - ``AreaLanding`` ("landing"): pantalla de aterrizaje del
        área.
      - ``DefinicionProgramacion`` ("def"): maestro Excel + AppState
        del PLC (tabs Dispositivos | Procesos).
      - ``Dispositivos`` ("disp"): previsualización y aplicación de
        cambios en TIA Portal.
      - ``BloquesCacheView`` ("cache"): snapshot cacheado de
        bloques/tag tables/UDTs del PLC.
      - ``Procesos`` ("proc"): nueva sub-vista de primer nivel
        (Fase 6.A — UI sin lógica backend). Selector de proceso + 2
        cards placeholder. Distinta de ``ProcesosPanel``: esta es
        accesible desde el Sidebar y la welcome, mientras que
        ``ProcesosPanel`` solo se monta dentro del tab "Procesos"
        de ``DefinicionProgramacion``.
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
                "proc":    "Procesos",
            },
        },
        "loaders": {
            "AlimentacionSidebar":    f"{_STATIC_PREFIX}/components/Sidebar.js",
            "AreaLanding":            f"{_STATIC_PREFIX}/components/AreaLanding.js",
            "DefinicionProgramacion": f"{_STATIC_PREFIX}/components/DefinicionProgramacion.js",
            "Dispositivos":           f"{_STATIC_PREFIX}/components/Dispositivos.js",
            "BloquesCacheView":       f"{_STATIC_PREFIX}/components/BloquesCacheView.js",
            # Sub-vista de primer nivel "Procesos" (Fase 6.A del plan
            # canónico — paso 1: UI sin lógica). Distinta del
            # sub-componente ``ProcesosPanel`` (tabs dentro de
            # Definición programación). Ambas coexisten; el operario
            # accede a esta desde el Sidebar y la welcome (``key:
            # "proc"``) y a la otra solo dentro del tab "Procesos"
            # de Definición.
            "Procesos":               f"{_STATIC_PREFIX}/components/Procesos.js",
            # Sub-componentes internos del rediseño Opción A
            # (tabs principales Dispositivos | Software). Se
            # registran como loaders pero NO como sub-vistas del
            # Sidebar: solo ``DefinicionProgramacion`` los usa.
            "MainTabs":               f"{_STATIC_PREFIX}/components/MainTabs.js",
            "DispositivosPanel":      f"{_STATIC_PREFIX}/components/DispositivosPanel.js",
            "ProcesosPanel":          f"{_STATIC_PREFIX}/components/ProcesosPanel.js",
        },
    }
    return _manifest


__all__ = ["build"]
