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
 *       // Sub-vista de primer nivel "Procesos" (Fase 6.A del plan
 *       // canónico — paso 1: UI sin lógica). Distinta del
 *       // sub-componente ``ProcesosPanel`` (tabs dentro de
 *       // Definición programación). Ambas coexisten.
 *       "Procesos":               () => import("./components/Procesos.js"),
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
 * AreaLanding → ``"AreaLanding"`` ..., Procesos → ``"Procesos"``).
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
    // Sub-vista de primer nivel "Procesos" (Fase 6.A — UI sin lógica).
    // Distinta del sub-componente ``ProcesosPanel``: esta es accesible
    // desde el Sidebar y la welcome (``key: "proc"``), mientras que
    // ``ProcesosPanel`` solo se monta dentro del tab "Procesos" de
    // ``DefinicionProgramacion``. Ambas coexisten en el área.
    "Procesos":                () => import("./components/Procesos.js"),
    // Sub-vista "Sync comentarios de DB" (preview + diff + apply).
    // Accesible desde la card de Procesos.js (key: "proc_sync").
    "ProcesosSyncView":        () => import("./components/ProcesosSyncView.js"),
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
            // NOTA: ``ProcesosSyncView`` NO aparece en ``views`` porque
            // se renderiza INLINE dentro de ``Procesos.js`` (como
            // panel hijo) en vez de como sub-vista top-level. El
            // loader del componente sí está declarado arriba para
            // que el shell SPA lo registre con ``app.component(...)``
            // y ``Procesos.js`` lo pueda usar como
            // ``<procesos-sync-view :proc-uid="...">`` dentro de su
            // template. Mantenerlo fuera de ``views`` evita que el
            // operario acceda al sync view por una URL/spa-route
            // perdida (ya no tiene sentido sin el proceso del
            // selector).
            views: {
                "landing": "AreaLanding",
                "def":     "DefinicionProgramacion",
                "disp":    "Dispositivos",
                "cache":   "BloquesCacheView",
                "proc":    "Procesos",
            },
        },
        loaders: _comps,
    };
}
