/**
 * main.js — Ensamblador de la SPA Vue 3 con ESM.
 *
 * Responsabilidades:
 *   * Importar ``createApp`` del build ESM de Vue 3.
 *   * Registrar los 3 componentes cross-cutting: Welcome, ConsolaLogs,
 *     ProgressIndicator.
 *   * Enrutar entre welcome y el layout de área según ``store.topLevelView``.
 *   * Dentro del área, enrutar entre sub-vistas según ``store.currentView``
 *     (validado contra ``store.areaManifest.components.views``).
 *   * Conectar el evento ``refresh`` de Definición programación a
 *     ``apiFetchMemory``.
 *   * Cargar dinámicamente los componentes del área seleccionada vía
 *     ``area-loader.js`` (sin imports hardcoded de las áreas).
 *   * Lanzar el polling de logs (1 s) y de progreso (500 ms).
 *   * Montar la app en ``#app``.
 *
 * NO hay build step: el navegador carga los módulos directamente desde
 * la red (CDN) o desde ``/js/`` servido por FastAPI.
 */
import { createApp, computed } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store, goToArea, goToSubview, loadCatalog } from "./store.js";
import { apiFetchLogs, apiFetchMemory, apiFetchProgress } from "./api.js";
import { mountArea } from "./area-loader.js";
import Welcome from "./components/Welcome.js";
import ConsolaLogs from "./components/ConsolaLogs.js";
import ProgressIndicator from "./components/ProgressIndicator.js";

/** Componente raíz: enrutador top-level (welcome) + layout de área. */
const App = {
    components: {
        Welcome,
        ConsolaLogs,
        ProgressIndicator,
    },
    setup() {
        /**
         * Llamado por Definición programación al pulsar "Refrescar".
         * Mantenemos la lógica de la API en ``main.js`` (no en el
         * componente) para preservar el principio de "componente
         * tonto" y poder mockear la API en tests.
         */
        async function refreshMemory() {
            store.busy = true;
            try {
                const r = await apiFetchMemory();
                if (r.ok && r.data && r.data.ok) {
                    store.memoryState = r.data;
                }
            } finally {
                store.busy = false;
            }
        }
        /**
         * Manejador del ``select`` emitido por ``Welcome``. El
         * ``Welcome`` ya validó que el área está ``available``.
         *
         * ``goToArea`` es async: carga el manifest del área (en
         * ``store.js``) y luego ``mountArea`` registra los
         * componentes del área en esta instancia de app. Si el
         * manifest viene vacío (endpoint backend no implementado
         * todavía), la SPA funciona en modo degradado.
         */
        async function onAreaSelected(key) {
            await goToArea(key);
            await mountArea(_app, key);
        }
        /**
         * Manejador del ``select`` emitido por ``AreaLanding``.
         * Cambia la sub-vista dentro del área activa.
         */
        function onSubviewSelected(key) {
            goToSubview(key);
        }
        /**
         * Nombre del componente de sidebar del área activa, leído del
         * manifest. ``null`` mientras no hay manifest (welcome o
         * área no soportada por el backend). Lo usa
         * ``<component :is="sidebarComponent" />`` para resolver el
         * componente registrado por ``mountArea``.
         */
        const sidebarComponent = computed(() => {
            const m = store.areaManifest;
            if (!m || !m.components) return null;
            return m.components.sidebar || null;
        });
        /**
         * Nombre del componente de la sub-vista activa (``'landing'
         * | 'def' | 'disp'`` para alimentación), leído del manifest.
         * Si la key de ``store.currentView`` no está en el manifest
         * (área sin esa sub-vista), devuelve ``null`` y la vista no
         * se renderiza.
         */
        const currentViewComponent = computed(() => {
            const m = store.areaManifest;
            if (!m || !m.components || !m.components.views) return null;
            return m.components.views[store.currentView] || null;
        });
        /**
         * Flag derivado: estamos en un área cuyo manifest no se pudo
         * cargar (endpoint no existe, loaders vacíos o red caída). Lo
         * usa el template para mostrar un mensaje claro en lugar de
         * un sidebar/main vacío.
         */
        const areaManifestEmpty = computed(() => {
            return (
                store.topLevelView === "area" &&
                !!store.selectedArea &&
                (!store.areaManifest ||
                    !store.areaManifest.loaders ||
                    Object.keys(store.areaManifest.loaders || {}).length === 0)
            );
        });
        return {
            store,
            refreshMemory,
            onAreaSelected,
            onSubviewSelected,
            sidebarComponent,
            currentViewComponent,
            areaManifestEmpty,
        };
    },
    template: /* html */ `
        <div class="flex flex-col flex-1 min-h-0">
            <Welcome v-if="store.topLevelView === 'welcome'" @select="onAreaSelected" />
            <div v-else class="flex flex-1 overflow-hidden min-w-0">
                <component v-if="sidebarComponent" :is="sidebarComponent" />
                <main class="flex-1 min-w-0 flex flex-col p-5 overflow-y-scroll">
                    <div v-if="areaManifestEmpty"
                        class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded p-10 text-center text-ink-muted">
                        <div>
                            <div class="text-5xl mb-3 opacity-40">⚠️</div>
                            <p class="mb-2 font-semibold text-ink">Área no soportada en el frontend</p>
                            <p class="text-xs">
                                El backend no ha publicado el manifest de
                                <strong class="text-accent">{{ store.selectedArea }}</strong>.
                                Verifica que el endpoint
                                <code>GET /api/v1/areas/{{ store.selectedArea }}/manifest</code>
                                esté disponible y devuelva los
                                <code>loaders</code> correctos.
                            </p>
                        </div>
                    </div>
                    <component v-else-if="currentViewComponent"
                        :is="currentViewComponent"
                        @select="onSubviewSelected"
                        @refresh="refreshMemory" />
                </main>
            </div>
            <ConsolaLogs v-if="store.topLevelView === 'area'" />
        </div>
    `,
};

const _app = createApp(App);
_app.component("Welcome", Welcome);
_app.component("ConsolaLogs", ConsolaLogs);
_app.component("ProgressIndicator", ProgressIndicator);
_app.mount("#app");

loadCatalog();

setInterval(async () => {
    if (store.topLevelView !== "area") return;
    const r = await apiFetchLogs();
    if (r.ok && Array.isArray(r.data.logs)) {
        store.logs = r.data.logs;
    }
}, 1000);

let _progressTickCount = 0;
setInterval(async () => {
    if (store.topLevelView !== "area") return;
    _progressTickCount += 1;
    if (_progressTickCount <= 4) {
        console.log("[zc-progress] tick", _progressTickCount);
    }
    const r = await apiFetchProgress();
    if (r.ok && r.data && r.data.ok && r.data.progress) {
        store.progress = r.data.progress;
    }
}, 500);
