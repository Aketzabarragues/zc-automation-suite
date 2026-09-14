"""Manifest del área "alimentacion" para el endpoint REST de la SPA.

Es el espejo Python de ``manifest.js``: mismo shape, pero los
``loaders`` son **strings** (URLs HTTP), no funciones, para que el
dict sea serializable a JSON. La SPA los importa como módulos ESM
y el backend los devuelve desde
``GET /api/v1/areas/alimentacion/manifest``.

``manifest.js`` y ``manifest.py`` son hermanos, no padre/hijo.

Tras el refactor de areas (sept-2026), este manifest ya no
declara nada del shell comun. El ShellSidebar, el ShellTopbar,
el ProgressIndicator, la ConsolaLogs y el plcpanelview son del
core (``core/web_server/static/js/components/``). Solo se declaran
aqui las vistas ESPECIFICAS del area:

  - AreaLanding (home del area).
  - DefinicionProgramacion (sub-vista "def").
  - Dispositivos          (sub-vista "disp").
  - Procesos              (sub-vista "proc").

El boton "PLC" comun de la sidebar enruta a currentView="plc"
que renderiza el plcpanelview del shell. ``"cache"`` que existia
en el manifest legacy se elimino.
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
    ``core/composition/app_area_registry.py``):
        {
          "id":   "alimentacion", "label": "Área de alimentación",
          "icon": "",
          "components": {
            "landing": "<ComponentName>",
            "views":   { "<key>": "<ComponentName>", ... },
            "viewLabels": { "<key>": "<label humano>", ... },
          },
          "loaders": { "<ComponentName>": "<url>", ... },
        }

    La SPA (``area-loader.js``) hace ``import(<url>)`` por loader.
    ``viewLabels`` es nuevo: el ShellSidebar y el ShellTopbar
    leen los labels humanos desde aquí (en lugar de tener un
    VIEW_LABELS hardcoded).
    """
    from core.composition.app_area_registry import AreaFrontendManifest

    _manifest: AreaFrontendManifest = {
        "id": "alimentacion",
        "label": "Área de alimentación",
        "icon": "",
        "components": {
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
                "proc":    "Procesos",
            },
            # Labels humanos del breadcrumb y de los items de la nav.
            # El shell los lee para mostrar texto friendly en vez de
            # la key cruda. Si no se aportan, el shell hace fallback
            # a la key capitalizada.
            "viewLabels": {
                "landing": "Inicio",
                "def":     "Definición programación",
                "disp":    "Dispositivos",
                "proc":    "Procesos",
            },
        },
        "loaders": {
            "AreaLanding":             f"{_STATIC_PREFIX}/components/AreaLanding.js",
            "DefinicionProgramacion":  f"{_STATIC_PREFIX}/components/DefinicionProgramacion.js",
            "Dispositivos":            f"{_STATIC_PREFIX}/components/Dispositivos.js",
            # Sub-vista de primer nivel "Procesos" (Fase 6.A — UI sin
            # lógica). Distinta del sub-componente ``ProcesosPanel``:
            # esta es accesible desde el Sidebar y la welcome
            # (``key: "proc"``), mientras que ``ProcesosPanel`` solo
            # se monta dentro del tab "Procesos" de Definicion.
            "Procesos":                f"{_STATIC_PREFIX}/components/Procesos.js",
            # ``ProcesosSyncView``: renderizado INLINE dentro de
            # ``Procesos.js`` (no como sub-vista top-level). El shell
            # SPA necesita el loader para registrar el componente y
            # que ``<procesos-sync-view>`` funcione como etiqueta en
            # el template del padre.
            "ProcesosSyncView":        f"{_STATIC_PREFIX}/components/ProcesosSyncView.js",
            # Sub-componentes internos del rediseño Opción A
            # (tabs principales Dispositivos | Software). Se
            # registran como loaders pero NO como sub-vistas del
            # Sidebar: solo ``DefinicionProgramacion`` los usa.
            "MainTabs":                f"{_STATIC_PREFIX}/components/MainTabs.js",
            "DispositivosPanel":       f"{_STATIC_PREFIX}/components/DispositivosPanel.js",
            "ProcesosPanel":           f"{_STATIC_PREFIX}/components/ProcesosPanel.js",
        },
    }
    return _manifest


__all__ = ["build"]
