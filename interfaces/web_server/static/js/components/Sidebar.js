/**
 * Componente Sidebar (panel lateral).
 *
 * Concentra:
 *   * Botones de navegación SPA (Memory / Sync).
 *   * Selector de archivo .xlsx.
 *   * Selector de PLC destino.
 *   * Botones de conexión a TIA Portal (Hot-Attach / Cold-Start).
 *
 * Tema: Industrial Claro. Usa SOLO tokens semánticos
 * (`bg-surface*`, `border-line*`, `text-ink*`, `bg-accent`,
 * `text-accent`). No se admiten colores literales (slate-X, cyan-X).
 */
import { ref } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store, pushLog } from "../store.js";
import {
    apiUploadExcel,
    apiFetchPlcs,
    apiAttachPortal,
    apiOpenNewPortal,
    apiFetchMemory,
} from "../api.js";

export default {
    name: "Sidebar",
    setup() {
        const fileInput = ref(null);

        /** Subir el .xlsx y refrescar memoria si fue OK. */
        async function handleExcel(ev) {
            const file = ev.target.files && ev.target.files[0];
            if (!file) return;
            store.busy = true;
            try {
                const r = await apiUploadExcel(file);
                if (r.ok) {
                    store.uploadSummary = r.data.summary || {};
                    pushLog("✅ Excel cargado en AppState", "success");
                    const mem = await apiFetchMemory();
                    if (mem.ok && mem.data && mem.data.ok) {
                        store.memoryState = mem.data;
                    }
                } else {
                    alert("Error cargando Excel: " + (r.data.detail || r.status));
                }
            } finally {
                store.busy = false;
                if (fileInput.value) fileInput.value.value = "";
            }
        }

        /** Refresca el desplegable de PLCs contra TIA Portal. */
        async function handleRefreshPlcs() {
            store.busy = true;
            try {
                const r = await apiFetchPlcs();
                if (r.ok && r.data && r.data.plcs) {
                    store.plcs = r.data.plcs;
                } else if (r.data && r.data.ok === false) {
                    pushLog(r.data.error || "TIA Portal no conectado", "warning");
                    store.plcs = [];
                }
            } finally {
                store.busy = false;
            }
        }

        /** Hot-Attach a una instancia YA ABIERTA de TIA Portal. */
        async function handleAttach() {
            store.busy = true;
            try {
                const r = await apiAttachPortal();
                if (r.ok) {
                    pushLog("Hot-attach a TIA Portal OK", "success");
                    await handleRefreshPlcs();
                } else {
                    alert(
                        "No se pudo conectar a TIA Portal: " +
                            (r.data?.detail || r.status || "error desconocido")
                    );
                }
            } finally {
                store.busy = false;
            }
        }

        /** Cold-Start: nueva instancia con un .apxx. */
        async function handleOpenNew() {
            const path = prompt("Ruta absoluta al archivo .apxx:");
            if (!path) return;
            store.busy = true;
            try {
                const r = await apiOpenNewPortal(path);
                if (r.ok) {
                    pushLog(`Cold start OK con proyecto '${path}'`, "success");
                    await handleRefreshPlcs();
                } else {
                    alert(
                        "No se pudo abrir el proyecto: " +
                            (r.data?.detail || r.status || "error desconocido")
                    );
                }
            } finally {
                store.busy = false;
            }
        }

        return {
            store,
            fileInput,
            handleExcel,
            handleRefreshPlcs,
            handleAttach,
            handleOpenNew,
        };
    },
    template: /* html */ `
        <aside class="w-80 flex-shrink-0 bg-surface-raised border-r border-line flex flex-col p-5 overflow-y-auto">
            <h1 class="text-xl font-bold text-accent mb-1">ZC Automation Suite</h1>
            <p class="text-xs text-ink-muted mb-6">Area Alimentación</p>

            <!-- Navegación -->
            <section class="mb-6">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Navegación</label>
                <div class="flex flex-col gap-1.5">
                    <button @click="store.currentView = 'memory'"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'memory'
                                     ? 'bg-accent border-accent text-ink-inverse font-semibold'
                                     : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        📊 Inspector de Memoria
                    </button>
                    <button @click="store.currentView = 'sync'"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'sync'
                                     ? 'bg-accent border-accent text-ink-inverse font-semibold'
                                     : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        ⚡ Sincronización TIA
                    </button>
                </div>
            </section>

            <!-- 1. Maestro Excel -->
            <section class="mb-6">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">1. Maestro Excel</label>
                <input ref="fileInput" type="file" accept=".xlsm"
                    @change="handleExcel" :disabled="store.busy"
                    class="block w-full text-xs text-ink
                           file:mr-2 file:py-1 file:px-2 file:rounded file:border-0
                           file:bg-surface-sunken file:text-ink hover:file:bg-surface-sunken" />
                <div v-if="store.uploadSummary" class="mt-2 text-xs text-ink-muted">
                    <div class="text-accent mb-1">✅ Excel cargado</div>
                    <ul class="space-y-0.5 pl-2">
                        <li v-for="(qty, tipo) in store.uploadSummary" :key="tipo">
                            <span class="font-mono text-accent">{{ tipo }}</span>:
                            <span class="font-semibold">{{ qty }}</span>
                        </li>
                    </ul>
                </div>
            </section>

            <!-- 2. PLC destino -->
            <section class="mb-6">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">2. PLC destino</label>
                <select v-model="store.selectedPlc"
                    :disabled="store.plcs.length === 0 || store.busy"
                    class="w-full bg-surface-sunken border border-line rounded px-2 py-1.5 text-sm text-ink disabled:opacity-50">
                    <option value="">-- Selecciona un PLC --</option>
                    <option v-for="p in store.plcs" :key="p" :value="p">{{ p }}</option>
                </select>
                <button @click="handleRefreshPlcs" :disabled="store.busy"
                    class="mt-2 text-xs px-2 py-1 bg-surface-sunken hover:bg-surface-sunken border border-line rounded text-ink disabled:opacity-50">
                    Refrescar lista
                </button>
            </section>

            <!-- 3. Conexión TIA Portal -->
            <section class="mb-6">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">3. Conexión TIA Portal</label>
                <div class="flex flex-col gap-2">
                    <button @click="handleAttach" :disabled="store.busy"
                        class="text-xs px-3 py-1.5 bg-accent hover:bg-accent-hover disabled:opacity-50 rounded text-ink-inverse">
                        🔌 Hot-Attach
                    </button>
                    <button @click="handleOpenNew" :disabled="store.busy"
                        class="text-xs px-3 py-1.5 bg-accent hover:bg-accent-hover disabled:opacity-50 rounded text-ink-inverse">
                        🚀 Cold Start
                    </button>
                </div>
            </section>
        </aside>
    `,
};
