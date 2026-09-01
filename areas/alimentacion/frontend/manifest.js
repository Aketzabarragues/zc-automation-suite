/**
 * Area manifest para la SPA.
 *
 * El shell ``core/interfaces/web_server/static/js/main.js`` carga este
 * módulo al entrar al área "alimentacion" (vía
 * ``core/interfaces/web_server/static/js/area-loader.js``) y monta los
 * 8 componentes Vue 3 que exporta por nombre. Ningún componente se
 * importa estáticamente desde el shell SPA: la SPA es multi-área sin
 * build step.
 *
 * Shape del manifest (debe coincidir con el endpoint
 * ``GET /api/v1/areas/<id>/manifest`` del backend, cuando se añada):
 *
 *   {
 *     id, label, icon,
 *     components: {
 *       sidebar: "AlimentacionSidebar",
 *       landing: "AreaLanding",
 *       views:    { "landing": "AreaLanding", "def": "...", "disp": "..." },
 *     },
 *     loaders: {
 *       "AlimentacionSidebar":    () => import("./components/Sidebar.js"),
 *       "AreaLanding":            () => import("./components/AreaLanding.js"),
 *       "DefinicionProgramacion": () => import("./components/DefinicionProgramacion.js"),
 *       "Dispositivos":           () => import("./components/Dispositivos.js"),
 *       "BloquesCacheView":       () => import("./components/BloquesCacheView.js"),
 *       // Sub-componentes de "Definición programación" (refactor
 *       // tabs principales, ver DefinicionProgramacion.js):
 *       "MainTabs":               () => import("./components/MainTabs.js"),
 *       "DispositivosPanel":      () => import("./components/DispositivosPanel.js"),
 *       "ProcesosPanel":          () => import("./components/ProcesosPanel.js"),
 *     },
 *   }
 *
 * Los nombres de los loaders son las keys que la SPA usa al hacer
 * ``app.component(name, def)``. Coinciden con el ``name:`` declarado
 * por cada componente Vue 3 (Sidebar → ``"AlimentacionSidebar"``,
 * AreaLanding → ``"AreaLanding"`` ...).
 *
 * Si se añade un componente nuevo al área:
 *   1. Crear el .js en ``./components/`` con un ``name:`` único.
 *   2. Añadir el ``() => import(...)`` aquí.
 *   3. Si es una sub-vista nueva, añadir su key al ``views``.
 */

const _comps = {
    "AlimentacionSidebar":     () => import("./components/Sidebar.js"),
    "AreaLanding":             () => import("./components/AreaLanding.js"),
    "DefinicionProgramacion":  () => import("./components/DefinicionProgramacion.js"),
    "Dispositivos":            () => import("./components/Dispositivos.js"),
    "BloquesCacheView":        () => import("./components/BloquesCacheView.js"),
    // Sub-componentes del rediseño de "Definición programación"
    // (tabs principales Dispositivos | Software). Se registran
    // como componentes globales para que ``DefinicionProgramacion``
    // los monte en su template (``<main-tabs>``, ``<dispositivos-panel>``,
    // ``<procesos-panel>``).
    "MainTabs":                () => import("./components/MainTabs.js"),
    "DispositivosPanel":       () => import("./components/DispositivosPanel.js"),
    "ProcesosPanel":           () => import("./components/ProcesosPanel.js"),
};

export function build() {
    return {
        id: "alimentacion",
        label: "Alimentación",
        icon: "🍞",
        components: {
            sidebar: "AlimentacionSidebar",
            landing: "AreaLanding",
            views: {
                "landing": "AreaLanding",
                "def":     "DefinicionProgramacion",
                "disp":    "Dispositivos",
                "cache":   "BloquesCacheView",
            },
        },
        loaders: _comps,
    };
}
