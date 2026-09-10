// ============================================================================
// main.js — Ensamblador de la SPA Vue 3 sin build step (HMI pasivo).
//
//  Sustituye al Vanilla JS de Fase 0.5 (tick SSE) y al legacy
//  `legacy_backup/interfaces/web_server/static/js/main.js` (que
//  hacia polling cada 1s para logs y 500ms para progreso).
//
//  Reglas ineludibles (AGENTS.md §4):
//    * 1 EventSource a `/api/v1/plc/events` (SSE, sin polling).
//      Lo abre `usePlc.init()` y lo mantiene durante toda la vida
//      de la SPA. Auto-reconnect nativo del navegador.
//    * CERO `setInterval` / `setTimeout` para polling. La regla del
//      greenfield: el HMI es pasivo, el backend empuja.
//    * Fetch solo via `usePlc().startFb()` / `disconnectFb()` /
//      `fetchAreas()` / `loadAreaManifest()`. NUNCA `fetch` directo
//      en un componente.
//
//  Componentes cross-cutting registrados:
//    - Welcome: pantalla de seleccion de area.
//    - ShellTopbar: cabecera con breadcrumb + indicators.
//    - ShellSidebar: sidebar con nav del area + ProgressIndicator.
//    - ConsolaLogs: footer de trazabilidad (LIFO).
//    - ProgressIndicator: panel de progreso del FB activo.
//    - EmptyState: patron "no hay datos" (NUEVO, no en legacy).
//
//  Routing:
//    - `plc.topLevelView` decide si pintamos Welcome ("welcome")
//      o el layout de area ("area": sidebar + main + logs).
//    - `plc.currentView` decide la sub-vista del area activa.
//    - `plc.selectedArea` es la key del area activa.
//
//  Manejador de seleccion de area (`onAreaSelected`):
//    Orden critico (leccion del area-loader legacy):
//      1. Reset suave del state operativo.
//      2. Cargar el manifest via `plc.loadAreaManifest(key)`.
//      3. Resolver loaders y registrar componentes en la app.
//      4. Asignar `plc.areaManifest` y poner `topLevelView = "area"`.
// ============================================================================

import { createApp, computed, nextTick } from "/js/vendor/vue.esm-browser.prod.js";
import { usePlc } from "/js/composables/usePlc.js";
import { loadArea } from "/js/area-loader.js";
import Welcome from "/js/components/Welcome.js";
import ShellTopbar from "/js/components/ShellTopbar.js";
import ShellSidebar from "/js/components/ShellSidebar.js";
import ConsolaLogs from "/js/components/ConsolaLogs.js";
import ProgressIndicator from "/js/components/ProgressIndicator.js";
import EmptyState from "/js/components/EmptyState.js";

/**
 * Componente raiz: enrutador top-level (Welcome) + layout de area.
 */
const App = {
    components: {
        Welcome,
        ShellTopbar,
        ShellSidebar,
        ConsolaLogs,
        ProgressIndicator,
        EmptyState,
    },
    setup() {
        const plc = usePlc();

        // -------------------------------------------------------------------------
        // Carga inicial: areas y arranca el EventSource (via init()).
        // -------------------------------------------------------------------------
        plc.init();           // abre el EventSource a /api/v1/plc/events
        plc.fetchAreas();     // rellena plc.areas (defensivo: si 404, queda [])

        // -------------------------------------------------------------------------
        // Handlers de routing.
        // -------------------------------------------------------------------------

        /**
         * Manejador del `select` emitido por Welcome. Orden critico:
         *   1. Reset suave del state operativo del SPA.
         *   2. Cargar el manifest del area (`plc.loadAreaManifest`).
         *   3. Resolver loaders y registrar componentes (`loadArea`).
         *   4. Transicionar a la vista de area (`topLevelView = "area"`).
         *   AHORA Vue re-renderiza con TODO listo y el Welcome se
         *   DESMONTA (asi no se vuelve a emitir `@select`).
         *
         * Si el manifest viene vacio (loaders: {}), la SPA entra en
         * modo degradado (mensaje "Area no soportada en el frontend").
         *
         * BUG QUE ESTO ARREGLA: si no se transiciona topLevelView,
         * el Welcome sigue montado, y cualquier re-render del v-for
         * de cards (por reactividad viva del Proxy del usePlc)
         * re-dispara el handler, causando un loop infinito de fetch
         * al manifest.
         */
        async function onAreaSelected(key) {
            if (!key) return;
            // 1. Reset suave del state operativo.
            plc.selectedArea = key;
            plc.currentView = "landing";
            // 2. Cargar el manifest (rellena plc.areaManifest).
            await plc.loadAreaManifest(key);
            // 3. Registrar componentes del area en la app.
            //    Si loaders esta vacio, loadArea no hace nada.
            await loadArea(_app, key);
            // 4. Transicionar a la vista de area (dispara re-render
            //    y desmonta el Welcome). DEBE IR AL FINAL: si va
            //    antes, el Welcome se desmonta con plc.areaManifest
            //    aun vacio y la SPA pinta "Area no soportada" durante
            //    un tick antes de que llegue el manifest.
            plc.topLevelView = "area";
            await nextTick();
        }

        /**
         * Manejador del `navigate` emitido por ShellSidebar. Cambia
         * la sub-vista del area activa.
         */
        function onSubviewSelected(key) {
            if (!key) return;
            const manifest = plc.areaManifest;
            const views = (manifest && manifest.components && manifest.components.views) || null;
            if (!views || typeof views !== "object") return;
            if (!Object.prototype.hasOwnProperty.call(views, key)) return;
            plc.currentView = key;
        }

        /**
         * Manejador del `back` emitido por ShellSidebar. Vuelve a Welcome.
         */
        function onBackToWelcome() {
            plc.topLevelView = "welcome";
        }

        // -------------------------------------------------------------------------
        // Computed para el template (regla Vue 3 sin build step).
        // -------------------------------------------------------------------------

        /**
         * Sidebar component del area activa. `null` mientras no hay
         * manifest (welcome o area no soportada). Lo usa el template
         * raiz via `<component :is="sidebarComponent" />`.
         */
        const sidebarComponent = computed(() => {
            const m = plc.areaManifest;
            if (!m || !m.components) return null;
            return m.components.sidebar || null;
        });

        /**
         * Componente de la sub-vista activa, leido del manifest.
         * Si la key de `plc.currentView` no esta en el manifest, devuelve
         * `null` y la vista no se renderiza.
         */
        const currentViewComponent = computed(() => {
            const m = plc.areaManifest;
            if (!m || !m.components || !m.components.views) return null;
            return m.components.views[plc.currentView] || null;
        });

        /**
         * Flag derivado: estamos en un area cuyo manifest no se
         * pudo cargar (endpoint no existe, loaders vacios o red
         * caida). Lo usa el template para mostrar un mensaje claro.
         */
        const areaManifestEmpty = computed(() => {
            return (
                plc.topLevelView === "area" &&
                !!plc.selectedArea &&
                (!plc.areaManifest ||
                    !plc.areaManifest.loaders ||
                    Object.keys(plc.areaManifest.loaders || {}).length === 0)
            );
        });

        /**
         * `{ key, label, icon }` del area activa para alimentar
         * el breadcrumb del ShellTopbar. Cae a un fallback
         * degradado si el area no esta en el catalogo.
         */
        const topbarArea = computed(() => {
            if (!plc.selectedArea) return { key: "", label: "—", icon: "" };
            const a = plc.areas.find((x) => x.key === plc.selectedArea);
            if (a) return a;
            return { key: plc.selectedArea, label: plc.selectedArea, icon: "" };
        });

        /**
         * `navItems` para el ShellSidebar del area activa, derivado
         * del manifest. Si el manifest no expone `components.views`
         * (modo degradado), devuelve un array vacio y el sidebar
         * pinta solo el titulo + ProgressIndicator.
         */
        const navItems = computed(() => {
            const m = plc.areaManifest;
            if (!m || !m.components || !m.components.views) return [];
            const out = [];
            // El landing es siempre la primera entrada ("Inicio del area").
            if (m.components.landing) {
                out.push({ key: "landing", icon: "🏠", label: "Inicio del area" });
            }
            // Las sub-vistas del area (def, disp, proc, ...).
            for (const [key] of Object.entries(m.components.views)) {
                if (key === "landing") continue;  // ya anadido arriba
                out.push({ key, icon: iconForKey(key), label: labelForKey(key) });
            }
            return out;
        });

        return {
            // Componentes locales (Vue 3 sin build step no acepta `<component :is="plc.X">`).
            topLevelView: computed(() => plc.topLevelView),
            areaLabel: computed(() => {
                const m = plc.areaManifest;
                if (m && m.label) return m.label;
                if (plc.selectedArea) return plc.selectedArea;
                return "—";
            }),
            sidebarComponent,
            currentViewComponent,
            areaManifestEmpty,
            topbarArea,
            navItems,
            selectedArea: computed(() => plc.selectedArea),
            // Handlers.
            onAreaSelected,
            onSubviewSelected,
            onBackToWelcome,
        };
    },
    template: /* html */ `
        <div class="flex flex-col flex-1 min-h-0">
            <Welcome
                v-if="topLevelView === 'welcome'"
                @select="onAreaSelected" />
            <div
                v-else
                class="flex flex-1 overflow-hidden min-w-0">

                <!-- 1. Sidebar slim: full-height, columna izquierda fija -->
                <ShellSidebar
                    v-if="sidebarComponent"
                    :area="topbarArea"
                    :nav-items="navItems"
                    @navigate="onSubviewSelected"
                    @back="onBackToWelcome" />

                <!-- 2. Columna derecha: topbar + main + consola.
                     ml-72 reserva el ancho del ShellSidebar. -->
                <div class="flex-1 flex flex-col min-w-0 ml-72">
                    <ShellTopbar :area="topbarArea" />

                    <main class="flex-1 min-w-0 flex flex-col p-5 overflow-y-auto">
                        <!-- Modo degradado: area sin manifest / sin loaders -->
                        <div
                            v-if="areaManifestEmpty"
                            class="flex-1 flex items-center justify-center"
                            data-testid="area-degraded">
                            <EmptyState
                                icon="⚠️"
                                title="Area no soportada en el frontend"
                                :description="'El backend no ha publicado el manifest de ' + selectedArea + '. Verifica que el endpoint GET /api/v1/areas/' + selectedArea + '/manifest este disponible y devuelva los loaders correctos.'"
                                size="lg" />
                        </div>

                        <!-- Vista activa del area -->
                        <component
                            v-else-if="currentViewComponent"
                            :is="currentViewComponent"
                            @select="onSubviewSelected" />
                    </main>

                    <ConsolaLogs v-if="topLevelView === 'area'" />
                </div>
            </div>
        </div>
    `,
};

// ---------------------------------------------------------------------------
// Helpers: icono + label por defecto para sub-vistas del area.
// ---------------------------------------------------------------------------

/**
 * Devuelve un emoji por defecto segun la key de la sub-vista.
 * Si la key no esta catalogada, devuelve "•".
 */
function iconForKey(key) {
    const map = {
        landing: "🏠",
        def: "📋",
        cache: "🗄️",
        disp: "🔌",
        proc: "⚙️",
    };
    return map[key] || "•";
}

/**
 * Devuelve una etiqueta humano-legible por defecto segun la key.
 * Si no esta catalogada, devuelve la key cruda.
 */
function labelForKey(key) {
    const map = {
        landing: "Inicio del area",
        def: "Definicion programacion",
        cache: "Cache del PLC",
        disp: "Dispositivos",
        proc: "Procesos",
    };
    return map[key] || key;
}

// ---------------------------------------------------------------------------
// Bootstrap.
// ---------------------------------------------------------------------------

const _app = createApp(App);
// Componentes globales por si el manifest los referencia por nombre.
_app.component("Welcome", Welcome);
_app.component("ConsolaLogs", ConsolaLogs);
_app.component("ProgressIndicator", ProgressIndicator);
_app.component("ShellTopbar", ShellTopbar);
_app.component("ShellSidebar", ShellSidebar);
_app.component("EmptyState", EmptyState);
_app.mount("#app");
