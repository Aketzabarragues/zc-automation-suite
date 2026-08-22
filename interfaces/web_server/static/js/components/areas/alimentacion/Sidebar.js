/**
 * Componente Sidebar (panel lateral) — específico del área Alimentación.
 *
 * Estructura (de arriba a abajo):
 *   1. Cabecera: "← Volver al inicio" + título "ZC Automation Suite" + área activa.
 *   2. Selección PLC (renombrado de "PLC destino"; solo el label cambia).
 *   3. Navegación entre vistas: "Definición programación" / "Dispositivos".
 *
 * Ya NO contiene:
 *   - "1. Maestro Excel" (movido al inicio de la vista "Definición programación").
 *   - "3. Conexión TIA Portal" (Hot-Attach / Cold-Start). El usuario lanza
 *     TIA Portal manualmente fuera de la app; el botón "Refrescar lista"
 *     de "Selección PLC" basta para poblar el dropdown.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (`bg-surface*`, `border-line*`, `text-ink*`, `bg-accent`, `text-accent`).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 */
import { computed } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store, pushLog, goToWelcome } from "../../../store.js";
import { apiFetchPlcs } from "../../../api.js";

export default {
    name: "AlimentacionSidebar",
    setup() {
        /**
         * Etiqueta del área actualmente seleccionada, derivada del
         * catálogo. Si no hay área o no se encuentra en el catálogo,
         * se muestra un placeholder neutro.
         */
        const areaLabel = computed(() => {
            if (!store.selectedArea) return "—";
            const a = store.availableAreas.find(
                (x) => x.key === store.selectedArea
            );
            return a ? a.label : store.selectedArea;
        });

        /**
         * Refresca el desplegable de PLCs contra TIA Portal.
         * Si no hay TIA Portal abierto, el endpoint responde
         * `{ok: false, error: "TIA Portal no conectado..."}` y se
         * loggea un warning. La UI queda con la lista vacía.
         */
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

        return {
            store,
            areaLabel,
            handleRefreshPlcs,
            goToWelcome,
        };
    },
    template: /* html */ `
        <aside class="w-80 flex-shrink-0 bg-surface-raised border-r border-line flex flex-col p-5 overflow-y-auto">
            <!-- Cabecera: volver + título + área activa -->
            <div class="mb-6">
                <button @click="goToWelcome"
                    class="text-xs text-ink-muted hover:text-accent flex items-center gap-1 mb-2"
                    data-testid="sidebar-back">
                    ← Volver al inicio
                </button>
                <h1 class="text-xl font-bold text-accent leading-tight">ZC Automation Suite</h1>
                <p class="text-xs text-ink-muted mt-0.5">
                    Área activa: <span class="font-semibold text-ink">{{ areaLabel }}</span>
                </p>
            </div>

            <!-- Selección PLC -->
            <section class="mb-6">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Selección PLC</label>
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

            <!-- Navegación entre vistas del área -->
            <section class="mb-6">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Navegación</label>
                <div class="flex flex-col gap-1.5">
                    <button @click="store.currentView = 'def'"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'def' ? 'bg-accent border-accent text-ink-inverse font-semibold' : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        📊 Definición programación
                    </button>
                    <button @click="store.currentView = 'disp'"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'disp' ? 'bg-accent border-accent text-ink-inverse font-semibold' : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        ⚡ Dispositivos
                    </button>
                </div>
            </section>
        </aside>
    `,
};
