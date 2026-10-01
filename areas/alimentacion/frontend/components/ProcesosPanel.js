/**
 * Componente ProcesosPanel.
 *
 * Panel que se muestra cuando ``store.activeMainTab === 'procesos'``.
 * Contiene los 4 dominios del Excel corporativo en sub-tabs, con la
 * misma estetica que ``DispositivosPanel``:
 *
 *   - Procesos             (DataExcelCache.procesos)
 *   - Parametros Enteros   (DataExcelCache.parametros_int)
 *   - Parametros Reales    (DataExcelCache.parametros_real)
 *   - Alarmas              (DataExcelCache.alarmas)
 *
 * Las columnas de cada tabla las dicta el catalog data-driven del
 * backend (``store.catalog.proc_display_order``). El orden y la
 * visibilidad por ausencia los determina el backend; la SPA solo
 * renderiza. Etiquetas y clases monospace se toman de
 * ``proc_col_labels`` y ``proc_mono_cols``.
 *
 * Tema: Industrial Claro. Solo tokens semanticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent``,
 * ``bg-amber-*``, ``text-amber-*``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * vue.esm-browser.prod.js NO acepta string literals multi-linea
 * dentro de arrays de :class. Cada literal va en una sola linea.
 */
import { computed, ref } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

export default {
    name: "ProcesosPanel",
    setup() {
        /**
         * ``{domain: [field_name_in_order, ...]}`` derivado del catalog.
         * Las claves ausentes caen al array vacio (la SPA muestra
         * el mensaje "Sin X definidos").
         */
        const displayOrder = computed(() => {
            const c = store.catalog;
            if (!c || !c.proc_display_order) return {};
            return c.proc_display_order;
        });

        /**
         * ``{col_name: "Label humano"}`` desde el catalog.
         * Fallback ``{}`` cuando el catalog no las trae.
         */
        const colLabels = computed(() => {
            const c = store.catalog;
            return (c && c.proc_col_labels) || {};
        });

        /**
         * Set de nombres de campo que se renderizan en monospace.
         * El backend ya las decide.
         */
        const monoCols = computed(() => {
            const c = store.catalog;
            return new Set((c && c.proc_mono_cols) || []);
        });

        /**
         * Lista de sub-tabs. La lista de dominios es fija (4 en
         * el Excel corporativo); aqui solo se materializa el
         * shape que consume el template ``[{key, label}]``.
         */
        const tabs = [
            { key: "procesos",        label: "Procesos" },
            { key: "parametros_int",  label: "Parametros Enteros" },
            { key: "parametros_real", label: "Parametros Reales" },
            { key: "alarmas",         label: "Alarmas" },
        ];

        const activeSoftwareTab = ref(tabs[0].key);

        /**
         * Columnas a renderizar en el sub-tab activo. Sale de
         * ``displayOrder[activeTab]``; si el catalog no la
         * provee, lista vacia y la tabla pinta el "Sin X
         * definidos".
         */
        const columns = computed(
            () => displayOrder.value[activeSoftwareTab.value] || []
        );

        /**
         * Filas (items) del sub-tab activo, leidas del cache del
         * Excel (``store.memoryState``).
         */
        const rows = computed(() => {
            if (!store.memoryState) return [];
            switch (activeSoftwareTab.value) {
                case "procesos":        return store.memoryState.procesos        || [];
                case "parametros_int":  return store.memoryState.parametros_int  || [];
                case "parametros_real": return store.memoryState.parametros_real || [];
                case "alarmas":         return store.memoryState.alarmas         || [];
                default:                return [];
            }
        });

        const emptyLabel = computed(() => {
            const t = tabs.find((x) => x.key === activeSoftwareTab.value);
            return t ? t.label : "";
        });

        /**
         * ``true`` cuando hay Excel cargado (mismo patron que
         * ``DispositivosPanel``: distinto null vs objeto vacio).
         */
        const hasMemory = computed(
            () => store.memoryState !== null
                && store.memoryState !== undefined
        );

        /**
         * Formatea un valor de celda: ``null|undefined|""`` se
         * pinta como ``"-"`` (UX limpia, sin casillas vacias).
         */
        function displayValue(value) {
            if (value === null || value === undefined) return "-";
            if (typeof value === "string" && value.trim() === "") return "-";
            return String(value);
        }

        return {
            tabs,
            activeSoftwareTab,
            columns,
            rows,
            hasMemory,
            displayValue,
            colLabels,
            monoCols,
            emptyLabel,
        };
    },
    template: /* html */ `
        <div class="flex-1 flex flex-col overflow-hidden">

            <!-- Sub-tabs de software (Procesos | PInt | PReal | Alarmas).
                 Solo visibles si hay Excel cargado (mismo patron que
                 DispositivosPanel: oculta los sub-tabs cuando !hasMemory). -->
            <div v-if="hasMemory" class="flex border-b border-line bg-surface-sunken overflow-x-auto">
                <button v-for="t in tabs" :key="t.key"
                    @click="activeSoftwareTab = t.key"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeSoftwareTab === t.key ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    {{ t.label }}
                    <span class="ml-1 text-[10px] opacity-70">({{ rows.length }})</span>
                </button>
            </div>

            <!-- Tabla reactiva. Una sola tabla para los 4 sub-tabs:
                 columnas leidas del catalog (displayOrder), filas
                 leidas de memoryState. Si no hay catalog cargado
                 (cold start), columns=[] y se muestra la tabla
                 con colspan y un aviso. -->
            <div class="flex-1 overflow-auto table-scroll-x mt-2 bg-surface-raised border border-line rounded">

                <table v-if="hasMemory && activeSoftwareTab" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th v-for="col in columns" :key="col"
                                class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">
                                {{ colLabels[col] || col }}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in rows" :key="row.uid"
                            class="border-b border-line">
                            <td v-for="col in columns" :key="col"
                                class="px-3 py-1.5 align-top text-ink whitespace-nowrap"
                                :class="monoCols.has(col) ? 'font-mono' : ''">
                                {{ displayValue(row[col]) }}
                            </td>
                        </tr>
                        <tr v-if="rows.length === 0">
                            <td :colspan="columns.length || 5"
                                class="px-3 py-6 text-center text-ink-muted italic">
                                Sin "{{ emptyLabel }}" definidos en el Excel cargado.
                            </td>
                        </tr>
                    </tbody>
                </table>

                <div v-else class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                    <div>
                        <div class="text-5xl mb-3 opacity-40">📊</div>
                        <p class="mb-2">La cache del excel está vacía.</p>
                        <p class="text-xs">Sube un Excel y pulsa <strong class="text-accent">"Actualizar"</strong>.</p>
                    </div>
                </div>

            </div>

        </div>
    `,
};