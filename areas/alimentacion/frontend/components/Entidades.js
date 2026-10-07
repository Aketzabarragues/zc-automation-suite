/**
 * Componente Entidades.
 *
 * Sub-vista de primer nivel del area "alimentacion" que se muestra
 * cuando ``store.currentView === 'entidades'``. Es gemela top-level
 * de Dispositivos y Procesos en el sidebar del shell SPA.
 *
 * Estructura (estilo Dispositivos.js, 2 cards):
 *   1. Card "info": vacio por defecto (mismo patron que
 *      ``Dispositivos.js``: ``<span v-else></span>``) + boton
 *      "🔍 Generar Prevision".
 *   2. Card "tabla": tabla plana con los 7 campos del DTO ``Entidad``
 *      filtrada por el PLC del store + boton "✅ Aplicar en TIA Portal"
 *      abajo.
 *
 * Stub (commit B.0): los botones llaman a ``apiEntidadesPreview`` /
 * ``apiEntidadesSync`` que devuelven ``status: "preview_stub" /
 * "sincronizar_stub"``. En commit B (FB Preview real) el backend
 * devuelve el diff Excel vs TIA online. En commit C (FB Sync real)
 * aplica los cambios transaccionalmente. Este componente no se
 * toca en B/C: solo se sustituye el backend.
 *
 * Tema: Industrial Claro. Solo tokens semanticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * ``vue.esm-browser.prod.js`` NO acepta string literals multi-linea
 * dentro de arrays de ``:class``. Cada literal va en una sola linea.
 */
import { computed, ref } from "/js/vendor/vue.esm-browser.prod.js";
import { store, resetPlcState } from "/js/store.js";
import { apiEntidadesPreview, apiEntidadesSync } from "/js/api.js";

export default {
    name: "Entidades",
    setup() {
        /**
         * PLC activo del sidebar. Si esta vacio, los botones se
         * deshabilitan.
         */
        const plcName = computed(() => store.selectedPlc || "");

        /**
         * Entidades del PLC seleccionado (lista plana
         * ``store.memoryState.entidades`` filtrada por ``plc_name``).
         * Si no hay memoria, lista vacia (mostramos empty state).
         */
        const entities = computed(() => {
            const ms = store.memoryState;
            if (!ms || !Array.isArray(ms.entidades)) return [];
            if (!plcName.value) return [];
            return ms.entidades.filter((e) => e && e.plc_name === plcName.value);
        });

        /**
         * ``true`` solo cuando hay Excel cargado. Mismo patron
         * que ``Dispositivos.js``: empty state global si no hay
         * memoria.
         */
        const hasMemory = computed(
            () => store.memoryState !== null
                && store.memoryState !== undefined
        );

        /**
         * True mientras hay un request al backend en vuelo (preview
         * o apply). Los 2 botones se deshabilitan mutuamente.
         */
        const isWorking = ref(false);

        /**
         * Helper UX: ``displayValue`` muestra ``-`` para
         * ``null/undefined/""`` en vez de celdas vacias feas.
         */
        function displayValue(value) {
            if (value === null || value === undefined) return "-";
            if (typeof value === "string" && value.trim() === "") return "-";
            return String(value);
        }

        async function handlePreview() {
            if (isWorking.value || !plcName.value) return;
            isWorking.value = true;
            store.busy = true;
            try {
                const r = await apiEntidadesPreview(plcName.value);
                if (r && r.errorType === "TIAConnectionError") {
                    resetPlcState();
                    return;
                }
                if (r && r.ok) {
                    store.entidadesLastPreview = r.data;
                }
            } finally {
                isWorking.value = false;
                store.busy = false;
            }
        }

        async function handleApply() {
            if (isWorking.value || !plcName.value) return;
            isWorking.value = true;
            store.busy = true;
            try {
                const r = await apiEntidadesSync(plcName.value);
                if (r && r.errorType === "TIAConnectionError") {
                    resetPlcState();
                    return;
                }
                if (r && r.ok) {
                    store.entidadesLastApply = r.data;
                }
            } finally {
                isWorking.value = false;
                store.busy = false;
            }
        }

        return {
            store,
            plcName,
            entities,
            hasMemory,
            isWorking,
            displayValue,
            handlePreview,
            handleApply,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- ★ Card "info" (estilo Dispositivos.js): vacio si no
                 hay prevision + boton "🔍 Generar Prevision". ★ -->
            <div class="mb-4 bg-surface-raised border border-line rounded p-4 flex justify-between items-center"
                 data-testid="entidades-card-info">
                <span></span>
                <button @click="handlePreview"
                    :disabled="!plcName || isWorking"
                    data-testid="entidades-preview-btn"
                    class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    🔍 Generar Prevision
                </button>
            </div>

            <!-- ★ Card "tabla" (estilo Dispositivos.js): tabla plana
                 con las entidades del PLC seleccionado + boton
                 "✅ Aplicar en TIA Portal" abajo. ★ -->
            <div class="flex-1 bg-surface-raised border border-line rounded p-4 mb-4 flex flex-col overflow-hidden"
                 data-testid="entidades-card-tabla">

                <div class="flex-1 overflow-auto table-scroll-x bg-surface-raised border border-line rounded">
                    <table v-if="hasMemory && entities.length > 0" class="w-full text-xs">
                        <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                            <tr>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">N°</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">Descripcion</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Tag</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Tipo</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Index</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Comentario</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="e in entities" :key="e.numero + '-' + e.plc_tag"
                                class="border-b border-line">
                                <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                                    {{ displayValue(e.numero) }}
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
                        </tbody>
                    </table>

                    <div v-else class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                        <div>
                            <div class="text-5xl mb-3 opacity-40">⚡</div>
                            <p class="mb-2">Sin prevision generada.</p>
                            <p class="text-xs">Pulsa <strong class="text-accent">"🔍 Generar Previsión"</strong> para ver el diff completo.</p>
                        </div>
                    </div>
                </div>

                <button @click="handleApply"
                    :disabled="!plcName || isWorking"
                    data-testid="entidades-apply-btn"
                    class="mt-3 w-full py-3 text-accent font-semibold text-sm bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    ✅ Aplicar en TIA Portal
                </button>
            </div>
        </section>
    `,
};