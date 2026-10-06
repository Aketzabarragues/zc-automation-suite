/**
 * Componente EntidadesPanel.
 *
 * Panel que se muestra cuando ``store.activeMainTab === 'entidades'``.
 * Contiene la tabla reactiva con TODAS las columnas del DTO
 * ``Entidad``, leidas de ``store.memoryState.entidades``.
 *
 * Multi-PLC: la lista del cache viene plana con todas las entidades
 * de todos los PLCs. La columna ``plc_name`` se muestra siempre
 * (no filtramos por PLC aqui; el filtro vive en el preview del PLC
 * concreto, igual que ``DispositivosPanel``).
 *
 * Si ``store.memoryState`` esta vacio, pinta el mismo empty state
 * que ``DispositivosPanel`` / ``ProcesosPanel``.
 *
 * Tema: Industrial Claro. Solo tokens semanticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent*``).
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

export default {
    name: "EntidadesPanel",
    setup() {
        /**
         * Filas de la tabla: ``store.memoryState.entidades``
         * (lista plana multi-PLC del DTO ``Entidad``). Si la lista
         * esta vacia o ``memoryState`` es null, devolvemos ``[]``.
         */
        const entities = computed(() => {
            if (!store.memoryState) return [];
            const lst = store.memoryState.entidades;
            return Array.isArray(lst) ? lst : [];
        });

        /**
         * ``true`` si hay Excel cargado. Mismo patron que
         * ``DispositivosPanel``: empty state global si no hay memoria.
         */
        const hasMemory = computed(
            () => store.memoryState !== null
                && store.memoryState !== undefined
        );

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
            displayValue,
        };
    },
    template: /* html */ `
        <div class="flex-1 overflow-auto table-scroll-x bg-surface-raised border border-line rounded">
            <table v-if="hasMemory" class="w-full text-xs">
                <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                    <tr>
                        <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">N°</th>
                        <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC</th>
                        <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">Descripcion</th>
                        <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Tag</th>
                        <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Tipo</th>
                        <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Index</th>
                        <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Comentario</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="e in entities" :key="e.plc_name + '-' + e.numero + '-' + e.plc_tag"
                        class="border-b border-line">
                        <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                            {{ displayValue(e.numero) }}
                        </td>
                        <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                            {{ displayValue(e.plc_name) }}
                        </td>
                        <td class="px-3 py-1.5 align-top text-ink whitespace-nowrap">
                            {{ displayValue(e.descripcion) }}
                        </td>
                        <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                            {{ displayValue(e.plc_tag) }}
                        </td>
                        <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                            {{ displayValue(e.plc_tipo) }}
                        </td>
                        <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                            {{ displayValue(e.plc_index) }}
                        </td>
                        <td class="px-3 py-1.5 align-top text-ink-muted">
                            {{ displayValue(e.plc_comentario) }}
                        </td>
                    </tr>
                    <tr v-if="entities.length === 0">
                        <td colspan="7"
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