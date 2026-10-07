/**
 * Componente Entidades.
 *
 * Sub-vista de primer nivel del area "alimentacion" que se muestra
 * cuando ``store.currentView === 'entidades'``. Es gemela top-level
 * de Dispositivos y Procesos en el sidebar del shell SPA.
 *
 * Estructura (estilo Dispositivos.js, 2 cards):
 *   1. Card "info": summary del ultimo preview (o vacio) + boton
 *      "🔍 Generar Prevision". Si el ultimo preview fallo
 *      (precondiciones_ok=False), la cabecera muestra el motivo.
 *   2. Card "tabla": tabla plana con los 7 campos del DTO ``Entidad``
 *      filtrada por el PLC del store + boton "✅ Aplicar Cambios en
 *      TIA Portal" abajo.
 *
 * El handler ``handlePreview`` consume ``/api/v1/entidades/preview``
 * que dispara el FB ``entidades_generar_preview`` (commit C). El
 * resultado se guarda en ``lastPreview`` y se muestra en la card 1.
 *
 * El handler ``handleApply`` consume ``/api/v1/entidades/sincronizar``
 * (sigue siendo stub en commit D). Cuando se implemente el FB sync,
 * se aplicaran los cambios de ``lastPreview`` (constants + comments).
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
         * Resultado del ultimo ``/api/v1/entidades/preview`` (commit C).
         * ``null`` o dict con shape completa del FB. La card 1 lo
         * muestra como summary (counts) o como error (si
         * ``precondiciones_ok`` es False).
         */
        const lastPreview = ref(null);

        /**
         * Helper UX: ``displayValue`` muestra ``-`` para
         * ``null/undefined/""`` en vez de celdas vacias feas.
         */
        function displayValue(value) {
            if (value === null || value === undefined) return "-";
            if (typeof value === "string" && value.trim() === "") return "-";
            return String(value);
        }

        /**
         * Summary legible del ultimo preview para la cabecera.
         * Si no hay preview -> "Sin prevision".
         */
        const previewSummary = computed(() => {
            const p = lastPreview.value;
            if (!p) return "Sin prevision";
            if (!p.precondiciones_ok) return "Preview incompleto";
            const s = p.summary || {};
            return (
                `${s.constants_agregados || 0} const adds · `
                + `${s.comments_added || 0} comments adds · `
                + `${s.comments_updated || 0} comments updates`
            );
        });

        /**
         * Lista de motivos si el ultimo preview fallo
         * (precondiciones_ok=False). Lista vacia si no fallo o si
         * no hay preview.
         */
        const previewMissingBlocks = computed(() => {
            const p = lastPreview.value;
            if (!p || p.precondiciones_ok) return [];
            const mb = p.missing_blocks || [];
            return Array.isArray(mb) ? mb : [];
        });

        async function handlePreview() {
            if (isWorking.value || !plcName.value) return;
            isWorking.value = true;
            store.busy = true;
            lastPreview.value = null;
            try {
                const r = await apiEntidadesPreview(plcName.value);
                if (r && r.errorType === "TIAConnectionError") {
                    resetPlcState();
                    return;
                }
                if (r && r.ok && r.data) {
                    lastPreview.value = r.data;
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
            lastPreview,
            previewSummary,
            previewMissingBlocks,
            displayValue,
            handlePreview,
            handleApply,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- ★ Card "info" (estilo Dispositivos.js): summary del
                 ultimo preview (o vacio) + banner de error si
                 precondiciones_ok=False + boton "🔍 Generar Prevision". ★ -->
            <div class="mb-4 bg-surface-raised border border-line rounded p-4"
                 data-testid="entidades-card-info">
                <div class="flex justify-between items-start gap-3">
                    <p class="text-xs text-ink-muted"
                       data-testid="entidades-preview-summary">
                        {{ previewSummary }}
                    </p>
                    <button @click="handlePreview"
                        :disabled="!plcName || isWorking"
                        data-testid="entidades-preview-btn"
                        class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                        🔍 Generar Prevision
                    </button>
                </div>

                <!-- ★ Banner rojo si el preview fallo. ★ -->
                <div v-if="previewMissingBlocks.length > 0"
                     data-testid="entidades-preview-errors"
                     class="mt-3 bg-red-50 border border-red-300 rounded p-3 text-xs text-red-700">
                    <div class="font-semibold mb-1">Preview incompleto:</div>
                    <ul class="list-disc list-inside space-y-0.5">
                        <li v-for="(msg, idx) in previewMissingBlocks" :key="idx">
                            {{ msg }}
                        </li>
                    </ul>
                </div>
            </div>

            <!-- ★ Card "tabla" (estilo Dispositivos.js): tabla plana
                 con las entidades del PLC seleccionado + boton
                 "✅ Aplicar Cambios en TIA Portal" abajo. ★ -->
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
                    ✅ Aplicar Cambios en TIA Portal
                </button>
            </div>
        </section>
    `,
};