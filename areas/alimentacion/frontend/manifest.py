"""Manifest del área "alimentacion" para el endpoint REST de la SPA.

Es el espejo Python de ``manifest.js``: mismo shape, pero los
``loaders`` son **strings** (URLs HTTP), no funciones, para que el
dict sea serializable a JSON. La SPA los importa como módulos ESM
y el backend los devuelve desde
``GET /api/v1/areas/alimentacion/manifest``.

``loaders`` también incluye los sub-componentes internos de las
vistas: la SPA los necesita con ``app.component(...)`` antes de
que el template los referencie.

``manifest.js`` y ``manifest.py`` son hermanos, no padre/hijo.
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
    ``core/application/area_registry.py``):
        {
          "id":   "alimentacion", "label": "Área de alimentación",
          "icon": "",
          "components": {
            "sidebar": "<ComponentName>", "landing": "<ComponentName>",
            "views":   { "<key>": "<ComponentName>", ... },
          },
          "loaders": { "<ComponentName>": "<url>", ... },
        }

    La SPA (``area-loader.js``) hace ``import(<url>)`` por loader.
    """
    from core.application.area_registry import AreaFrontendManifest

    _manifest: AreaFrontendManifest = {
        "id": "alimentacion",
        "label": "Área de alimentación",
        "icon": "",
        "components": {
            "sidebar": "AlimentacionSidebar",
            "landing": "AreaLanding",
            # NOTA: ``ProcesosSyncView`` NO aparece en ``views`` porque
            # se renderiza INLINE dentro de ``Procesos.js`` (como
            # panel hijo) en vez de como sub-vista top-level. El
            # loader del componente sí está declarado abajo para
            # que el shell SPA lo registre con ``app.component(...)``
            # y ``Procesos.js`` lo pueda usar como
            # ``<procesos-sync-view :proc-uid="...">`` dentro de su
            # template. Mantenerlo fuera de ``views`` evita que el
            # operario acceda al sync view por una URL/spa-route
            # perdida (ya no tiene sentido sin el proceso del
            # selector).
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
            # ``ProcesosSyncView``: renderizado INLINE dentro de
            # ``Procesos.js`` (no como sub-vista top-level). El
            # shell SPA necesita el loader para registrar el
            # componente y que ``<procesos-sync-view>`` funcione
            # como etiqueta en el template del padre.
            "ProcesosSyncView":       f"{_STATIC_PREFIX}/components/ProcesosSyncView.js",
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
