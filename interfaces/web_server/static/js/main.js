/**
 * main.js — Ensamblador de la SPA Vue 3 con ESM.
 *
 * Responsabilidades:
 *   * Importar ``createApp`` del build ESM de Vue 3.
 *   * Registrar los 5 componentes del paquete ``components/``
 *     (incluido el nuevo ``Welcome``).
 *   * Enrutar entre la pantalla de bienvenida (``Welcome``) y el
 *     layout de área (``Sidebar`` + ``<main>`` + ``ConsolaLogs``)
 *     según ``store.topLevelView``.
 *   * Conectar el evento ``refresh`` del Inspector de Memoria a
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
import { store, goToArea } from "./store.js";
import { apiFetchLogs, apiFetchMemory } from "./api.js";
import Welcome from "./components/Welcome.js";
import Sidebar from "./components/Sidebar.js";
import InspectorMemoria from "./components/InspectorMemoria.js";
import SincronizacionTia from "./components/SincronizacionTia.js";
import ConsolaLogs from "./components/ConsolaLogs.js";

/** Componente raíz: enrutador top-level (welcome) + layout de área. */
const App = {
    components: {
        Welcome,
        Sidebar,
        InspectorMemoria,
        SincronizacionTia,
        ConsolaLogs,
    },
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
        /**
         * Manejador del ``select`` emitido por ``Welcome``. El
         * ``Welcome`` ya validó que el área está ``available``.
         */
        function onAreaSelected(key) {
            goToArea(key);
        }
        return { store, refreshMemory, onAreaSelected };
    },
    template: /* html */ `
        <div class="flex flex-col flex-1 min-h-0">
            <Welcome v-if="store.topLevelView === 'welcome'" @select="onAreaSelected" />
            <div v-else class="flex flex-1 overflow-hidden min-w-0">
                <Sidebar />
                <main class="flex-1 min-w-0 flex flex-col p-5 overflow-y-scroll">
                    <InspectorMemoria v-if="store.currentView === 'memory'" @refresh="refreshMemory" />
                    <SincronizacionTia v-else />
                </main>
            </div>
            <ConsolaLogs v-if="store.topLevelView === 'area'" />
        </div>
    `,
};

createApp(App).mount("#app");

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
