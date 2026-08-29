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
// Imports absolutos. Los componentes del área se sirven bajo
// ``/static/areas/alimentacion/frontend/components/`` (path
// servido por el FastAPI shell), pero los cross-cutting
// (``store.js``, ``api.js``, ``ProgressIndicator``) viven en
// ``/js/`` y NO se mueven. Un import relativo ``../../../../js/X.js``
// se resolvería contra la URL del módulo y daría
// ``/static/js/X.js`` (404). Usar absolutos evita el problema.
import { store, pushLog, goToWelcome, goToSubview, refreshPlcBlocks, cacheSummary } from "/js/store.js";
import { apiFetchPlcs } from "/js/api.js";
import ProgressIndicator from "/js/components/ProgressIndicator.js";

export default {
    name: "AlimentacionSidebar",
    components: { ProgressIndicator },
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

        /**
         * Handler del ``@change`` del ``<select>`` de PLC. Dispara
         * el scan de bloques+tag_tables del PLC recién elegido
         * (o limpia el cache si el operario vuelve a la opción
         * vacía). La promesa se ignora a propósito: la UI se
         * re-renderiza por reactividad de ``store.plcBlocksCache``
         * y ``store.scanningPlc`` cuando el scan termina.
         */
        async function onPlcSelected() {
            await refreshPlcBlocks(store.selectedPlc);
        }

        /**
         * ``cacheSummary()`` (de ``store.js``) es una función pura
         * que devuelve un objeto; el template la consume como
         * ``cacheSummary.blocks``, ``cacheSummary.scanning`` etc.
         * Si la expusiéramos como función cruda, esas propiedades
         * serían ``undefined`` y el ``v-if`` del badge jamás se
         * activaría. La envolvemos en ``computed`` para que Vue
         * la reevalúe reactivamente cuando cambien
         * ``store.plcBlocksCache`` o ``store.scanningPlc``.
         */
        const cacheSummaryView = computed(() => cacheSummary());

        return {
            store,
            areaLabel,
            handleRefreshPlcs,
            onPlcSelected,
            cacheSummary: cacheSummaryView,
            goToWelcome,
            goToSubview,
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
                <select v-model="store.selectedPlc" @change="onPlcSelected"
                    :disabled="store.plcs.length === 0 || store.busy"
                    class="w-full bg-surface-sunken border border-line rounded px-2 py-1.5 text-sm text-ink disabled:opacity-50">
                    <option value="">-- Selecciona un PLC --</option>
                    <option v-for="p in store.plcs" :key="p" :value="p">{{ p }}</option>
                </select>
                <button @click="handleRefreshPlcs" :disabled="store.busy"
                    class="mt-2 text-xs px-2 py-1 bg-surface-sunken hover:bg-surface-sunken border border-line rounded text-ink disabled:opacity-50">
                    Refrescar lista
                </button>

                <!-- Badge "Cache: N bloques · M tablas". Inline fijo
                     debajo del botón "Refrescar lista" — no es un
                     overlay ni un modal. Solo se muestra si hay
                     cache, scan en curso o error. -->
                <div v-if="cacheSummary.blocks > 0 || cacheSummary.tables > 0 || cacheSummary.scanning || cacheSummary.error"
                    data-testid="plc-blocks-cache-badge"
                    :data-stale="cacheSummary.isStale ? 'true' : 'false'"
                    :class="['mt-2 px-2 py-1.5 rounded border text-[11px] flex items-center justify-between gap-2',
                             cacheSummary.error ? 'border-red-600 text-red-600' :
                             cacheSummary.scanning ? 'border-line text-ink-muted' :
                             cacheSummary.isStale ? 'border-amber-600 text-amber-600' :
                             'border-line text-ink-muted bg-surface-sunken']">
                    <span class="font-mono min-w-0 truncate">
                        <template v-if="cacheSummary.scanning">⏳ Cache: escaneando…</template>
                        <template v-else-if="cacheSummary.error">⚠ Cache: error</template>
                        <template v-else>Cache: {{ cacheSummary.blocks }} bloques · {{ cacheSummary.tables }} tablas
                            <span class="text-ink-muted">({{ cacheSummary.ageSeconds }}s)</span>
                        </template>
                    </span>
                    <button v-if="!cacheSummary.scanning && !cacheSummary.error && cacheSummary.blocks > 0"
                        @click="refreshPlcBlocks(store.selectedPlc, { force: true })"
                        class="text-ink-muted hover:text-accent flex-shrink-0"
                        title="Forzar re-scan"
                        data-testid="plc-blocks-cache-refresh">↻</button>
                </div>
            </section>

            <!-- Navegación entre vistas del área -->
            <section class="mb-6">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Navegación</label>
                <div class="flex flex-col gap-1.5">
                    <button @click="goToSubview('landing')"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'landing' ? 'bg-accent border-accent text-ink-inverse font-semibold' : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        🏠 Inicio del área
                    </button>
                    <button @click="goToSubview('def')"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'def' ? 'bg-accent border-accent text-ink-inverse font-semibold' : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        📊 Definición programación
                    </button>
                    <button @click="goToSubview('disp')"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'disp' ? 'bg-accent border-accent text-ink-inverse font-semibold' : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        ⚡ Dispositivos
                    </button>
                </div>
            </section>

            <!-- Indicador de progreso (fijo en la parte inferior del sidebar) -->
            <ProgressIndicator />
        </aside>
    `,
};
