/**
 * Componente EntidadesPanel.
 *
 * Panel que se muestra cuando ``store.activeMainTab === 'entidades'``.
 * Contiene 2 sub-tabs fijos:
 *   1. **Configuracion**: empty state (placeholder para futuro).
 *   2. **Entidades**: tabla reactiva con TODAS las columnas del DTO
 *      (``Entidad``), leidas de ``store.memoryState.entidades``.
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
import { computed, ref, watch } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

export default {
    name: "EntidadesPanel",
    setup() {
        /**
         * Sub-tabs fijos. No son data-driven (las opciones del Excel
         * no controlan esta navegacion: ``Configuracion`` es un slot
         * futuro y ``Entidades`` es la unica coleccion).
         */
        const tabs = [
            { key: "configuracion", label: "Configuracion" },
            { key: "entidades",     label: "Entidades"     },
        ];

        const activeSubTab = ref(
            store.activeTab || tabs[0].key
        );

        watch(
            () => tabs[0].key,
            (firstKey) => {
                if (!activeSubTab.value && firstKey) {
                    activeSubTab.value = firstKey;
                }
            },
            { immediate: true }
        );

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
         * Conteo total (sin filtro por sub-tab; el sub-tab
         * "Configuracion" no tiene filas).
         */
        const entidadesCount = computed(() => entities.value.length);

        /**
         * ``true`` si hay Excel cargado. Mismo patron que
         * ``DispositivosPanel``: empty state global si no hay memoria.
         */
        const hasMemory = computed(
            () => store.memoryState !== null
                && store.memoryState !== undefined
        );

        /**
         * Helper UX: ``displayValue`` muestra ``—`` para
         * ``null/undefined/""`` en vez de celdas vacias feas.
         */
        function displayValue(value) {
            if (value === null || value === undefined) return "—";
            if (typeof value === "string" && value.trim() === "") return "—";
            return String(value);
        }

        return {
            tabs,
            activeSubTab,
            entities,
            entidadesCount,
            hasMemory,
            displayValue,
        };
    },
    template: /* html */ `
        <div class="flex-1 flex flex-col overflow-hidden">

            <!-- Sub-tabs fijos: Configuracion | Entidades.
                 Misma clase que DispositivosPanel para coherencia. -->
            <div v-if="hasMemory" class="flex border-b border-line bg-surface-sunken overflow-x-auto">
                <button v-for="t in tabs" :key="t.key"
                    @click="activeSubTab = t.key"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeSubTab === t.key ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    {{ t.label }}
                    <span v-if="t.key === 'entidades'" class="ml-1 text-[10px] opacity-70">({{ entidadesCount }})</span>
                </button>
            </div>

            <!-- Sub-vista Configuracion (placeholder). -->
            <entidades-configuracion v-if="hasMemory && activeSubTab === 'configuracion'" />

            <!-- Sub-vista Entidades: tabla reactiva con las 7 columnas
                 del DTO ``Entidad``. Multi-PLC: la columna plc_name se
                 muestra siempre; el filtro por PLC vive en el preview
                 del PLC concreto (igual que ``DispositivosPanel``). -->
            <div v-if="hasMemory && activeSubTab === 'entidades'"
                class="flex-1 overflow-auto table-scroll-x mt-2 bg-surface-raised border border-line rounded">
                <table class="w-full text-xs">
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
                                ⚠️ La pestana "Entidades" no contiene entidades. Verifique que la hoja ``ENTIDADES`` exista y la ``Tabla_Entidades`` tenga filas validas.
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- Empty state global: cuando NO hay memoria cargada
                 (operario aun no ha subido Excel). Mismo patron que
                 ``DispositivosPanel``. -->
            <div v-if="!hasMemory"
                class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                <div>
                    <div class="text-5xl mb-3 opacity-40">📊</div>
                    <p class="mb-2">La cache del excel esta vacia.</p>
                    <p class="text-xs">Sube un Excel y pulsa <strong class="text-accent">"Actualizar"</strong>.</p>
                </div>
            </div>

        </div>
    `,
};