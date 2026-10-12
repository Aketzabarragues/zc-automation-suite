/**
 * Componente EntidadesPanel.
 *
 * Panel que se muestra cuando ``store.activeMainTab === 'entidades'``.
 * Contiene la tabla reactiva con las columnas del DTO ``Entidad``,
 * leidas de
 * ``store.appCache.areas["alimentacion"].excel_full.entidades``.
 *
 * Las columnas visibles las dicta el catalog data-driven del backend
 * (``store.catalog.ent_display_order.entidades``). El orden y la
 * visibilidad por ausencia los determina el backend; la SPA solo
 * renderiza. Etiquetas y clases monospace se toman de
 * ``store.catalog.ent_col_labels`` y ``store.catalog.ent_mono_cols``.
 *
 * Multi-PLC: la lista del cache viene plana con todas las entidades
 * de todos los PLCs. La columna ``plc_name`` se incluye en el
 * display_order y la SPA la pinta siempre que el backend la liste.
 *
 * Si ``excel_full.value`` esta vacio, pinta el empty state global
 * (mismo patron que ``DispositivosPanel`` / ``ProcesosPanel``).
 *
 * Tema: Industrial Claro. Solo tokens semanticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent*``).
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

export default {
    name: "EntidadesPanel",
    setup() {
        // ``excel_full`` reactivo desde el AppCache del area activa.
        const excelFull = computed(
            () => store.appCache?.areas?.alimentacion?.excel_full || null
        );

        /**
         * Filas de la tabla: ``excel_full.entidades``
         * (lista plana multi-PLC del DTO ``Entidad``). Si la lista
         * esta vacia o el cache es null, devolvemos ``[]``.
         */
        const entities = computed(() => {
            const ms = excelFull.value;
            if (!ms) return [];
            const lst = ms.entidades;
            return Array.isArray(lst) ? lst : [];
        });

        /**
         * ``true`` si hay Excel cargado. Mismo patron que
         * ``DispositivosPanel``: empty state global si no hay memoria.
         */
        const hasMemory = computed(() => excelFull.value != null);

        /**
         * Columnas visibles del DTO ``Entidad`` (en el orden que el
         * operario ha decidido en el ``config.json``).
         * ``ent_display_order.entidades`` es un array plano (single
         * domain). Fallback ``[]`` si el catalog no esta cargado.
         */
        const displayOrder = computed(() => {
            const c = store.catalog;
            if (!c || !c.ent_display_order) return [];
            return Array.isArray(c.ent_display_order.entidades)
                ? c.ent_display_order.entidades
                : [];
        });

        /**
         * ``{col_name: "Label humano"}`` desde el catalog.
         * Fallback ``{}`` cuando el catalog no las trae.
         */
        const colLabels = computed(() => {
            const c = store.catalog;
            return (c && c.ent_col_labels) || {};
        });

        /**
         * Set de nombres de campo que se renderizan en monospace
         * (``font-mono``). El backend ya las decide.
         */
        const monoCols = computed(() => {
            const c = store.catalog;
            if (!c || !Array.isArray(c.ent_mono_cols)) return new Set();
            return new Set(c.ent_mono_cols);
        });

        /**
         * Resuelve la etiqueta humana de una columna desde el catalog.
         * Si no hay label para esa col, devuelve el nombre crudo
         * (fallback defensivo para no pintar celdas vacias).
         */
        function columnLabel(col) {
            const labels = colLabels.value;
            if (Object.prototype.hasOwnProperty.call(labels, col)) {
                const label = labels[col];
                if (typeof label === "string" && label.length > 0) {
                    return label;
                }
            }
            return col;
        }

        /**
         * Devuelve ``"font-mono"`` si la columna es monospace segun el
         * catalog, sino ``""``. La SPA aplica la clase con el binding
         * ``:class`` (sin strings multilinea dentro del array).
         */
        function columnClass(col) {
            return monoCols.value.has(col) ? "font-mono" : "";
        }

        /**
         * Helper UX: ``displayValue`` muestra ``-`` para
         * ``null/undefined/""`` en vez de celdas vacias feas.
         */
        function displayValue(value) {
            if (value === null || value === undefined) return "-";
            if (typeof value === "string" && value.trim() === "") return "-";
            return String(value);
        }

        return {
            entities,
            hasMemory,
            displayOrder,
            columnLabel,
            columnClass,
            displayValue,
        };
    },
    template: /* html */ `
        <div class="flex-1 overflow-auto table-scroll-x bg-surface-raised border border-line rounded">
            <table v-if="hasMemory" class="w-full text-xs">
                <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                    <tr>
                        <th v-for="col in displayOrder" :key="col"
                            class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">
                            {{ columnLabel(col) }}
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="e in entities" :key="e.plc_name + '-' + e.numero + '-' + e.plc_tag"
                        class="border-b border-line">
                        <td v-for="col in displayOrder" :key="col"
                            :class="'px-3 py-1.5 align-top text-ink whitespace-nowrap ' + columnClass(col)">
                            {{ displayValue(e[col]) }}
                        </td>
                    </tr>
                    <tr v-if="entities.length === 0">
                        <td :colspan="displayOrder.length"
                            class="px-3 py-6 text-center text-ink-muted italic">
                            No contiene entidades. Verifique que la hoja ENTIDADES exista y la Tabla_Entidades tenga filas validas.
                        </td>
                    </tr>
                </tbody>
            </table>
            <div v-else class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                <div>
                    <div class="text-5xl mb-3 opacity-40">📊</div>
                    <p class="mb-2">La cache del excel esta vacia.</p>
                    <p class="text-xs">Sube un Excel y pulsa <strong class="text-accent">"Actualizar"</strong>.</p>
                </div>
            </div>
        </div>
    `,
};