/**
 * main.js — Ensamblador de la SPA Vue 3 con ESM.
 *
 * Responsabilidades:
 *   * Importar ``createApp`` del build ESM de Vue 3.
 *   * Registrar los 4 componentes del paquete ``components/``.
 *   * Conectar el evento ``refresh`` del Inspector de Memoria a
 *     ``apiFetchMemory``.
 *   * Lanzar el polling de logs (1 s) en background.
 *   * Montar la app en ``#app``.
 *
 * NO hay build step: el navegador carga los módulos directamente
 * desde la red (CDN) o desde ``/js/`` servido por FastAPI.
 */
import { createApp } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store } from "./store.js";
import { apiFetchLogs, apiFetchMemory } from "./api.js";
import Sidebar from "./components/Sidebar.js";
import InspectorMemoria from "./components/InspectorMemoria.js";
import SincronizacionTia from "./components/SincronizacionTia.js";
import ConsolaLogs from "./components/ConsolaLogs.js";

/** Componente raíz: layout en columnas (sidebar + main) + footer. */
const App = {
    components: { Sidebar, InspectorMemoria, SincronizacionTia, ConsolaLogs },
    setup() {
        /**
         * Llamado por el Inspector de Memoria al pulsar "Refrescar".
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
        return { store, refreshMemory };
    },
    template: /* html */ `
        <div class="flex flex-1 overflow-hidden min-w-0">
            <Sidebar />
            <main class="flex-1 min-w-0 flex flex-col p-5 overflow-y-scroll">
                <InspectorMemoria
                    v-if="store.currentView === 'memory'"
                    @refresh="refreshMemory" />
                <SincronizacionTia v-else />
            </main>
        </div>
        <ConsolaLogs />
    `,
};

createApp(App).mount("#app");

/* ── Polling de logs (1 s, IT-only, sin tocar la DLL de TIA) ─────
 * Mantenemos la consola sincronizada con el backend sin necesidad
 * de WebSockets: GET /api/v1/logs es snapshot puro. */
setInterval(async () => {
    const r = await apiFetchLogs();
    if (r.ok && Array.isArray(r.data.logs)) {
        store.logs = r.data.logs;
    }
}, 1000);
