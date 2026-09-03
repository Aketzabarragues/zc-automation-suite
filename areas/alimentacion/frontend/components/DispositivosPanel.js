/**
 * Componente DispositivosPanel.
 *
 * Panel que se muestra cuando ``store.activeMainTab === 'dispositivos'``.
 * Contiene:
 *   1. N_MAX cards (dimensiones) — info transversal del Excel.
 *      Vivían en el shell DefinicionProgramacion; se mudaron AQUÍ
 *      por feedback del operario: describen tamaños de arrays de
 *      dispositivos (N_MAX_DISP_ED, etc.) y solo tienen sentido
 *      dentro del contexto de dispositivos.
 *   2. Sub-tabs data-driven (ED|EA|SA|V|M|MVF) generadas desde
 *      ``store.catalog.device_tabs``.
 *   3. La tabla reactiva con todas las columnas del dataclass
 *      activo (``modelColumns[activeSubTab]``), dentro de un
 *      contenedor ``bg-surface-raised border border-line rounded``
 *      para coherencia visual con ``ProcesosPanel.js``.
 *
 * Replica 1:1 el bloque que antes vivía en ``DefinicionProgramacion.js``
 * (líneas 96-103, 229-268). La refactorización es solo estructural:
 * la lógica (catalog, columnas, monospace, ``displayValue``) se
 * conserva idéntica.
 *
 * Si ``store.memoryState`` está vacío (operario aún no ha subido
 * Excel), pinta el mensaje "Inspector de Memoria está vacío" en
 * lugar de la tabla.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 */
import { computed, ref, watch } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

export default {
    name: "DispositivosPanel",
    setup() {
        /**
         * Sub-tabs data-driven desde el catalog del backend.
         * Mantiene la forma ``{key, label}`` que ya consumía el
         * template original.
         */
        const tabs = computed(() => {
            const c = store.catalog;
            if (!c || !Array.isArray(c.device_tabs)) return [];
            return c.device_tabs.map((t) => ({
                key: t.canonical,
                label: t.label,
            }));
        });

        /**
         * ``canonical → [field_name, ...]`` derivado del catalog.
         * El backend (``get_columns_for``) ya filtra los campos
         * ``cfg_*`` (SCL), así que coincide con lo que la UI
         * legacy mostraba.
         */
        const modelColumns = computed(() => {
            const c = store.catalog;
            if (!c || !c.model_columns) return {};
            return c.model_columns;
        });

        /**
         * Etiquetas de columna y columnas monospace desde el
         * catalog. Si el catalog no las trae, fallback a ``{}``
         * y ``new Set()`` respectivamente (modo degradado).
         */
        const colLabels = computed(() => {
            const c = store.catalog;
            return (c && c.col_labels) || {};
        });

        const monoCols = computed(() => {
            const c = store.catalog;
            return new Set((c && c.mono_cols) || []);
        });

        const activeSubTab = ref(store.activeTab || (tabs.value[0] && tabs.value[0].key) || "");

        // Si el catalog se carga tarde (después de que el
        // componente ya montó), ``activeSubTab`` puede estar ``""``.
        // Reaccionar y fijar al primer tab disponible.
        watch(
            () => tabs.value[0] && tabs.value[0].key,
            (firstKey) => {
                if (!activeSubTab.value && firstKey) {
                    activeSubTab.value = firstKey;
                }
            },
            { immediate: true }
        );

        const columns = computed(
            () => modelColumns.value[activeSubTab.value] || []
        );

        const activeDevices = computed(() => {
            if (!store.memoryState || !store.memoryState.dispositivos) return [];
            return store.memoryState.dispositivos[activeSubTab.value] || [];
        });

        const hasMemory = computed(
            () => {
                // ``hasMemory`` distingue 2 estados visuales:
                //   1. ``store.memoryState === null``: operario no ha
                //      hecho nunca un fetch (estado "virgen"). Se
                //      muestra el "Inspector vacío" centrado.
                //   2. ``store.memoryState`` es un objeto (incluso con
                //      dicts vacios, p.ej. tras "Refrescar" sin
                //      Excel): se muestran las tablas. Cada tabla
                //      pinta su propio mensaje "La pestaña X no
                //      contiene dispositivos" si su lista esta
                //      vacia (eso lo hace el ``<tr v-if="...">``).
                // El operario quiere que tras "Refrescar" se vean
                // las tablas (no el "Inspector vacío"), asi que
                // hasMemory es true en cuanto hay memoryState
                // (incluso si no trae datos).
                return store.memoryState !== null
                    && store.memoryState !== undefined;
            }
        );

        /**
         * N_MAX cards (dimensiones) — info transversal del Excel.
         * Antes vivían en el shell ``DefinicionProgramacion``; se
         * mudaron AQUÍ (dentro del tab Dispositivos) por feedback del
         * operario: el bloque de "dimensiones" describe tamaños de
         * arrays de dispositivos (N_MAX_DISP_ED, etc.) y solo tiene
         * sentido dentro del contexto de dispositivos.
         */
        const dimensiones = computed(
            () => (store.memoryState && store.memoryState.dimensiones) || null
        );

        /**
         * Conteo de dispositivos por sub-tab (DispED, DispEA, ...).
         * Encapsula el acceso a ``store.memoryState.dispositivos`` para
         * que el template no toque ``store`` directamente (lo cual es
         * inalcanzable desde el template en Vue 3 con template compiler
         * en runtime: las variables importadas a nivel de módulo NO se
         * exponen automáticamente al template; solo lo retornado del
         * setup()).
         */
        const deviceCountsByTab = computed(() => {
            const out = {};
            const disp = store.memoryState && store.memoryState.dispositivos;
            if (!disp || typeof disp !== "object") return out;
            for (const [key, lst] of Object.entries(disp)) {
                out[key] = Array.isArray(lst) ? lst.length : 0;
            }
            return out;
        });

        /**
         * Helper: formatea un valor de celda para mostrar ``—``
         * en vez de ``null/undefined/vacío`` (UX limpia).
         */
        function displayValue(value) {
            if (value === null || value === undefined) return "—";
            if (typeof value === "string" && value.trim() === "") return "—";
            return String(value);
        }

        return {
            tabs,
            activeSubTab,
            columns,
            activeDevices,
            hasMemory,
            dimensiones,
            displayValue,
            colLabels,
            monoCols,
            deviceCountsByTab,
        };
    },
    template: /* html */ `
        <div class="flex-1 flex flex-col overflow-hidden">

            <!-- Tarjeta de Dimensiones (N_MAX) — info transversal del Excel.
                 Vivía en el shell DefinicionProgramacion; se movió AQUÍ
                 (dentro del tab Dispositivos) por feedback del operario. -->
            <div v-if="dimensiones" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 mb-3">
                <div v-for="(value, key) in dimensiones" :key="key"
                    class="bg-surface-raised border border-line rounded p-3">
                    <div class="text-[10px] uppercase text-ink-muted">{{ key }}</div>
                    <div class="text-xl font-bold text-accent">{{ value }}</div>
                </div>
            </div>

            <!-- Sub-tabs por tipo de dispositivo (ED|EA|SA|V|M|MVF) -->
            <div v-if="hasMemory" class="flex border-b border-line bg-surface-sunken overflow-x-auto">
                <button v-for="t in tabs" :key="t.key"
                    @click="activeSubTab = t.key"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeSubTab === t.key ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    {{ t.label }}
                    <span class="ml-1 text-[10px] opacity-70">({{ deviceCountsByTab[t.key] || 0 }})</span>
                </button>
            </div>

            <!-- Tabla reactiva: dump de TODAS las columnas del dataclass activo.
                 Contenedor estandarizado con ProcesosPanel: bg-surface-raised
                 + border + rounded para coherencia visual entre ambos tabs. -->
            <div class="flex-1 overflow-auto table-scroll-x mt-2 bg-surface-raised border border-line rounded">
                <table v-if="hasMemory" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th v-for="col in columns" :key="col"
                                class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">
                                {{ colLabels[col] || col }}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="d in activeDevices"
                            :key="(d.uid || 'no-uid') + '-' + d.numero"
                            class="border-b border-line">
                            <td v-for="col in columns" :key="col"
                                class="px-3 py-1.5 align-top text-ink whitespace-nowrap"
                                :class="monoCols.has(col) ? 'font-mono' : ''">
                                {{ displayValue(d[col]) }}
                            </td>
                        </tr>
                        <tr v-if="activeDevices.length === 0">
                            <td :colspan="columns.length || 5"
                                class="px-3 py-6 text-center text-ink-muted italic">
                                ⚠️ La pestaña "{{ activeSubTab }}" no contiene dispositivos. Si el Excel fue cargado, verifique que la tabla exista y no esté vacía.
                            </td>
                        </tr>
                    </tbody>
                </table>
                <div v-else class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                    <div>
                        <div class="text-5xl mb-3 opacity-40">📊</div>
                        <p class="mb-2">El Inspector de Memoria está vacío.</p>
                        <p class="text-xs">Sube un Excel y pulsa <strong class="text-accent">"Actualizar"</strong>.</p>
                    </div>
                </div>
            </div>

        </div>
    `,
};
