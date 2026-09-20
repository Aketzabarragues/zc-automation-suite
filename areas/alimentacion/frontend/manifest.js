/**
 * Area manifest para la SPA.
 *
 * El shell ``core/web_server/static/js/main.js`` carga este módulo al
 * entrar al área "alimentacion" (vía
 * ``core/web_server/static/js/area-loader.js``) y monta los
 * componentes Vue 3 que exporta por nombre. Ningún componente se
 * importa estáticamente desde el shell SPA: la SPA es multi-área
 * sin build step.
 *
 * Tras el refactor de areas (sept-2026), este manifest ya no
 * declara nada del shell comun. El ShellSidebar, el ShellTopbar,
 * el ProgressIndicator, la ConsolaLogs y el plcpanelview son del
 * core (``core/web_server/static/js/components/``) y NO aparecen
 * aquí. Solo se declaran aquí las vistas ESPECIFICAS del area:
 *
 *   - AreaLanding (home del area).
 *   - DefinicionProgramacion (sub-vista "def").
 *   - Dispositivos          (sub-vista "disp").
 *   - Procesos              (sub-vista "proc").
 *
 * El boton "PLC" comun de la sidebar enruta a currentView="plc"
 * que renderiza el plcpanelview del shell. ``"cache"`` que existia
 * en el manifest legacy se elimino: ya no es una sub-vista del
 * area sino una vista comun del shell.
 *
 * Shape del manifest:
 *
 *   {
 *     id, label, icon,
 *     components: {
 *       landing: "AreaLanding",
 *       views:    { "landing": "AreaLanding", "def": "...", "disp": "...", "proc": "..." },
 *       viewLabels: { "landing": "Inicio", "def": "...", "disp": "...", "proc": "..." },
 *     },
 *     loaders: { "<ComponentName>": () => import("./components/<File>.js") },
 *   }
 *
 * ``viewLabels`` es nuevo (sept-2026). El shell lee las labels
 * humanas del breadcrumb y de los items de la nav desde aquí (en
 * lugar de tener un VIEW_LABELS hardcoded en el shell). Si el area
 * no aporta viewLabels, el shell hace fallback a la key
 * capitalizada.
 */

const _comps = {
    "AreaLanding":             () => import("./components/AreaLanding.js"),
    "DefinicionProgramacion":  () => import("./components/DefinicionProgramacion.js"),
    "Dispositivos":            () => import("./components/Dispositivos.js"),
    // Sub-vista de primer nivel "Procesos" (UI sin lógica).
    // Distinta del sub-componente ``ProcesosPanel``: esta es accesible
    // desde el Sidebar y la welcome (``key: "proc"``), mientras que
    // ``ProcesosPanel`` solo se monta dentro del tab "Procesos" de
    // ``DefinicionProgramacion``. Ambas coexisten en el área.
    "Procesos":                () => import("./components/Procesos.js"),
    // Sub-vista "Sync comentarios de DB" (preview + diff + apply).
    // Accesible desde la card de Procesos.js (key: "proc_sync").
    "ProcesosSyncView":        () => import("./components/ProcesosSyncView.js"),
    // Sub-vista inline "Crear proceso completo desde plantilla TIA".
    // Mismo patron que ``ProcesosSyncView``: se renderiza INLINE
    // dentro de ``Procesos.js`` (panel hijo) y NO aparece en
    // ``views`` (no es sub-vista top-level del area).
    "ProcesosCrearView":       () => import("./components/ProcesosCrearView.js"),
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
        label: "Área de alimentación",
        icon: "",
        components: {
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
                "proc":    "Procesos",
            },
            // Labels humanos del breadcrumb y de los items de la nav.
            // El shell los lee para mostrar texto friendly en vez de
            // la key cruda. Si no se aportan, el shell hace
            // fallback a la key capitalizada.
            viewLabels: {
                "landing": "Inicio",
                "def":     "Definición programación",
                "disp":    "Dispositivos",
                "proc":    "Procesos",
            },
        },
        loaders: _comps,
    };
}
