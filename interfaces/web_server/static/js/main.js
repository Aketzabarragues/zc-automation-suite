/**
 * main.js — Ensamblador de la SPA Vue 3 con ESM.
 *
 * Responsabilidades:
 *   * Importar ``createApp`` del build ESM de Vue 3.
 *   * Registrar los 6 componentes:
 *     - Cross-cutting: Welcome, ConsolaLogs.
 *     - Del área Alimentación: AlimentacionSidebar, AreaLanding,
 *       DefinicionProgramacion, Dispositivos.
 *   * Enrutar entre la pantalla de bienvenida (``Welcome``) y el
 *     layout de área (sidebar + main + ConsolaLogs) según
 *     ``store.topLevelView``.
 *   * Dentro del área, enrutar entre landing / def / disp según
 *     ``store.currentView``.
 *   * Conectar el evento ``refresh`` de Definición programación a
 *     ``apiFetchMemory``.
 *   * Lanzar el polling de logs (1 s) en background (solo dentro
 *     del área: en welcome no se necesita).
 *   * Montar la app en ``#app``.
 *
 * NO hay build step: el navegador carga los módulos directamente
 * desde la red (CDN) o desde ``/js/`` servido por FastAPI.
 *
 * IMPORTANTE sobre los templates: el compilador de templates en
 * runtime de Vue 3 (``vue.esm-browser.prod.js``) NO acepta string
 * literals multi-línea dentro de arrays de ``:class``. Cada literal
 * debe ir en una sola línea. Ver ``components/Welcome.js`` para el
 * ejemplo.
 */
import { createApp } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store, goToArea, goToSubview, loadCatalog } from "./store.js";
import { apiFetchLogs, apiFetchMemory } from "./api.js";
import Welcome from "./components/Welcome.js";
import ConsolaLogs from "./components/ConsolaLogs.js";
import AlimentacionSidebar from "./components/areas/alimentacion/Sidebar.js";
import AreaLanding from "./components/areas/alimentacion/AreaLanding.js";
import DefinicionProgramacion from "./components/areas/alimentacion/DefinicionProgramacion.js";
import Dispositivos from "./components/areas/alimentacion/Dispositivos.js";

/** Componente raíz: enrutador top-level (welcome) + layout de área. */
const App = {
    components: {
        Welcome,
        ConsolaLogs,
        AlimentacionSidebar,
        AreaLanding,
        DefinicionProgramacion,
        Dispositivos,
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
         */
        function onAreaSelected(key) {
            goToArea(key);
        }
        /**
         * Manejador del ``select`` emitido por ``AreaLanding``.
         * Cambia la sub-vista dentro del área activa.
         */
        function onSubviewSelected(key) {
            goToSubview(key);
        }
        return { store, refreshMemory, onAreaSelected, onSubviewSelected };
    },
    template: /* html */ `
        <div class="flex flex-col flex-1 min-h-0">
            <Welcome v-if="store.topLevelView === 'welcome'" @select="onAreaSelected" />
            <div v-else class="flex flex-1 overflow-hidden min-w-0">
                <AlimentacionSidebar />
                <main class="flex-1 min-w-0 flex flex-col p-5 overflow-y-scroll">
                    <AreaLanding v-if="store.currentView === 'landing'" @select="onSubviewSelected" />
                    <DefinicionProgramacion v-else-if="store.currentView === 'def'" @refresh="refreshMemory" />
                    <Dispositivos v-else />
                </main>
            </div>
            <ConsolaLogs v-if="store.topLevelView === 'area'" />
        </div>
    `,
};

createApp(App).mount("#app");

/* ── Carga inicial del catálogo de presentación ──────────────────
 * Llamamos a ``loadCatalog`` antes del primer render para que
 * los componentes que dependen de ``store.catalog`` (los 2
 * que muestran pestañas/tablas) tengan datos al pintarse.
 * Si el catalog falla (backend caído), los componentes caen
 * a fallbacks ``[]``/``{}`` y la SPA sigue funcionando. */
loadCatalog();

/* ── Polling de logs (1 s, IT-only, sin tocar la DLL de TIA) ─────
 * Mantenemos la consola sincronizada con el backend sin necesidad
 * de WebSockets: GET /api/v1/logs es snapshot puro. Se activa solo
 * cuando el usuario está dentro de un área (en welcome no hay
 * actividad que reflejar). */
setInterval(async () => {
    if (store.topLevelView !== "area") return;
    const r = await apiFetchLogs();
    if (r.ok && Array.isArray(r.data.logs)) {
        store.logs = r.data.logs;
    }
}, 1000);
