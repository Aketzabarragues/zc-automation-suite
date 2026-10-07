/**
 * Componente Entidades.
 *
 * Vista top-level gemela de Dispositivos y Procesos en el sidebar del shell
 * SPA. Se muestra cuando ``store.currentView === 'entidades'``.
 *
 * Estructura (2 cards, mismo patron que Dispositivos.js):
 *   1. Card "info": summary del ultimo preview con 4 contadores
 *      coloreados (agregar / renombrar / eliminar / sin_cambios)
 *      + boton "🔍 Generar Prevision". SIEMPRE se renderiza: si no
 *      hay preview, los 4 contadores se quedan en 0 (gemelo Disp).
 *   2. Card "tabla": sub-card de N_MAX_ENTIDAD arriba (estilo sub-cards
 *      de Dispositivos) + tabla unica con 4 columnas
 *      (# / Actual (TIA) / Deseado (Excel) / Estado) + boton
 *      "✅ Aplicar Cambios en TIA Portal" abajo.
 *
 * Columnas de la tabla (orden post C.16, oct-2026):
 *   #             -> row.nuevo (value del Excel). null si eliminar.
 *   Actual (TIA)  -> row.plc_tag_tia (TAG del PLC). null si agregar.
 *   Deseado (Exc) -> row.plc_tag_excel (TAG del Excel). null si eliminar.
 *   Estado        -> status (agregar/renombrar/eliminar/sin_cambios).
 *
 * Estado del preview: lee/escribe directo ``store.previewData`` (mismo
 * slot que Dispositivos). Asi, al navegar away y volver, el preview
 * se mantiene (consistente con Dispositivos).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * ``vue.esm-browser.prod.js`` NO acepta CUALQUIER baktill (doble o
 * simple) dentro de ``template: `...` `` (ver C.13 + C.15). Cero
 * baktilts dentro del template. Para "comillas tipograficas" usar
 * comillas rectas o entidades HTML.
 */
import { computed, ref } from "/js/vendor/vue.esm-browser.prod.js";
import { store, resetPlcState } from "/js/store.js";
import { apiEntidadesPreview, apiEntidadesSync } from "/js/api.js";
import { STATUS_META } from "../lib/disp_status.js";

/**
 * Etiqueta humana del NMAX del feature entidades. Se deriva del
 * nombre canonico (``N_MAX_ENTIDAD``) ya que el catalog puede
 * exponer el label en ``store.catalog.nmax``.
 */
function nmaxLabelEntidades(name) {
    const c = store.catalog;
    if (c && Array.isArray(c.nmax)) {
        const hit = c.nmax.find((e) => e.name === name);
        if (hit && hit.label) return hit.label;
    }
    return name;
}

export default {
    name: "Entidades",
    setup() {
        const plcName = computed(() => store.selectedPlc || "");

        /**
         * True mientras hay un request al backend en vuelo (preview
         * o apply). Los 2 botones se deshabilitan mutuamente.
         */
        const isWorking = ref(false);

        /**
         * True si hay preview con precondiciones OK. Mismo patron
         * que Dispositivos.js pero particularizado para el shape
         * del FB de entidades (``precondiciones_ok``).
         */
        const hasPreview = computed(
            () => !!store.previewData && store.previewData.precondiciones_ok === true
        );

        /**
         * 4 contadores de status agregados desde ``constants.todos``
         * (patron Dispositivos.js). SIEMPRE devuelven un dict con
         * los 4 keys, aunque no haya preview (los 4 counters en 0).
         * Esto permite que la card 1 siempre renderice el mismo
         * patron visual sin empty-state "Sin prevision".
         */
        const summary = computed(() => {
            if (!hasPreview.value) {
                return { agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 0, total: 0 };
            }
            const all = (store.previewData.constants && store.previewData.constants.todos) || [];
            const agregados = all.filter((r) => r.status === "agregar").length;
            const renombrados = all.filter((r) => r.status === "renombrar").length;
            const eliminados = all.filter((r) => r.status === "eliminar").length;
            const sin_cambios = all.filter((r) => r.status === "sin_cambios").length;
            const total = all.length;
            return { agregados, renombrados, eliminados, sin_cambios, total };
        });

        /**
         * N_MAX_ENTIDAD como sub-card (estilo sub-cards de
         * Dispositivos). Si no hay preview o el XML no existia,
         * lista vacia.
         */
        const nmaxCards = computed(() => {
            if (!hasPreview.value) return [];
            return (store.previewData.nmax && store.previewData.nmax.todos) || [];
        });

        const nmaxSummary = computed(() => {
            if (!hasPreview.value) {
                return { actualizar: 0, sin_cambios: 0, total: 0 };
            }
            return (store.previewData.nmax && store.previewData.nmax.summary)
                || { actualizar: 0, sin_cambios: 0, total: 0 };
        });

        /**
         * Filas del diff de PlcUserConstants ``ent_<plc_tag>``.
         * Directo desde ``store.previewData.constants.todos``.
         *
         * El FB garantiza el shape ``{plc_tag, plc_tag_tia, plc_tag_excel,
         * actual, nuevo, status}`` por entry. Sort por ``plc_tag``
         * ascendente (string stable).
         */
        const activeRows = computed(() => {
            if (!hasPreview.value) return [];
            const all = (store.previewData.constants && store.previewData.constants.todos) || [];
            return all.slice().sort((a, b) => {
                const an = String(a.plc_tag || "");
                const bn = String(b.plc_tag || "");
                return an.localeCompare(bn);
            });
        });

        /**
         * Total de cambios pendientes (constantes + NMAX), para el
         * badge del boton "Aplicar Cambios".
         */
        const totalChanges = computed(() => {
            if (!hasPreview.value) return 0;
            return (
                summary.value.agregados
                + summary.value.eliminados
                + summary.value.renombrados
                + (nmaxSummary.value.actualizar || 0)
            );
        });

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
                if (r && r.ok && r.data) {
                    store.previewData = r.data;
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
                if (r && r.ok && r.data && r.data.post_sync_preview) {
                    store.previewData = r.data.post_sync_preview;
                }
            } finally {
                isWorking.value = false;
                store.busy = false;
            }
        }

        return {
            store,
            plcName,
            isWorking,
            hasPreview,
            summary,
            nmaxCards,
            nmaxLabel: nmaxLabelEntidades,
            nmaxSummary,
            activeRows,
            totalChanges,
            statusMeta: STATUS_META,
            handlePreview,
            handleApply,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- ★ Card "info" (estilo Dispositivos.js): SIEMPRE se
                 renderiza con los 4 contadores (en 0 si no hay
                 preview). Colores por segmento (agregar=accent,
                 renombrar=amber, eliminar=red, sin_cambios=ink-muted),
                 mismo lenguaje que Disp. No hay literal "Sin prevision"
                 (en Disp tampoco esta). ★ -->
            <div class="mb-4 bg-surface-raised border border-line rounded p-4 flex justify-between items-center"
                 data-testid="entidades-card-info">
                <p class="text-xs text-ink-muted"
                   data-testid="entidades-preview-summary">
                    {{ summary.total }} entidades analizadas —
                    <span class="text-accent">{{ summary.agregados }} a agregar</span> ·
                    <span class="text-amber-700">{{ summary.renombrados }} a renombrar</span> ·
                    <span class="text-red-700">{{ summary.eliminados }} a eliminar</span> ·
                    <span class="text-ink-muted">{{ summary.sin_cambios }} sin cambios</span>
                </p>
                <button @click="handlePreview"
                    :disabled="!plcName || isWorking"
                    data-testid="entidades-preview-btn"
                    class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    🔍 Generar Prevision
                </button>
            </div>

            <!-- ★ Card "tabla" (estilo Dispositivos.js): NMAX_ENTIDAD
                 + tabla unica de diff + boton aplicar. Sin tabs:
                 solo hay 1 tipo de entidad (ENT), no hace falta
                 el strip de tabs como en Disp. ★ -->
            <div class="flex-1 bg-surface-raised border border-line rounded p-4 mb-4 flex flex-col overflow-hidden"
                 data-testid="entidades-card-tabla">

                <!-- NMAX_ENTIDAD como sub-card (mismo lenguaje visual
                     que las NMAX de Dispositivos). Solo 1 entrada,
                     por eso usamos grid de 1-2 cols (no 6). -->
                <div v-if="hasPreview && nmaxCards.length > 0"
                    class="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
                    <div v-for="card in nmaxCards" :key="card.name"
                        data-testid="entidades-nmax-card"
                        class="bg-surface-raised border border-line rounded p-3">
                        <div class="text-[10px] uppercase text-ink-muted">
                            {{ nmaxLabel(card.name) }}
                        </div>
                        <div class="text-xl font-bold">
                            <template v-if="card.status === 'actualizar'">
                                <span class="inline-flex items-baseline gap-1.5">
                                    <span v-if="card.actual !== null && card.actual !== undefined"
                                        class="text-accent">{{ card.actual }}</span>
                                    <span class="text-ink-muted">→</span>
                                    <span class="text-amber-700">{{ card.nuevo }}</span>
                                </span>
                            </template>
                            <template v-else>
                                <span class="text-accent">{{ card.nuevo }}</span>
                            </template>
                        </div>
                    </div>
                </div>

                <!-- Area de scroll: contiene la tabla unica de diff o
                     el empty-state "Sin prevision generada". Mismo
                     lenguaje de card que Dispositivos.js. -->
                <div class="flex-1 overflow-auto table-scroll-x mt-2 bg-surface-raised border border-line rounded">
                    <table v-if="hasPreview" class="w-full text-xs" data-testid="entidades-diff-table">
                        <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                            <tr>
                                <th class="px-3 py-2 text-left text-ink-muted w-14">#</th>
                                <th class="px-3 py-2 text-left text-ink-muted">Actual (TIA)</th>
                                <th class="px-3 py-2 text-left text-ink-muted">Deseado (Excel)</th>
                                <th class="px-3 py-2 text-left text-ink-muted">Estado</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="(row, idx) in activeRows" :key="idx"
                                class="border-b border-line"
                                :class="statusMeta[row.status]?.cls">
                                <!-- #: value del Excel (nuevo).
                                     null para status=eliminar. -->
                                <td class="px-3 py-1.5 font-mono text-xs text-ink-muted">
                                    {{ row.nuevo === null || row.nuevo === undefined ? '—' : row.nuevo }}
                                </td>
                                <!-- Actual (TIA): plc_tag del PLC.
                                     null para status=agregar. -->
                                <td class="px-3 py-1.5 font-mono text-xs"
                                    :class="row.status === 'eliminar' ? 'text-red-700 line-through' : 'text-ink'">
                                    {{ row.plc_tag_tia === null || row.plc_tag_tia === undefined ? '—' : row.plc_tag_tia }}
                                </td>
                                <!-- Deseado (Excel): plc_tag del Excel.
                                     null para status=eliminar. -->
                                <td class="px-3 py-1.5 font-mono text-xs"
                                    :class="row.status === 'agregar' ? 'text-accent' :
                                            row.status === 'renombrar' ? 'text-amber-800' :
                                            'text-ink-muted'">
                                    {{ row.plc_tag_excel === null || row.plc_tag_excel === undefined ? '—' : row.plc_tag_excel }}
                                </td>
                                <td class="px-3 py-1.5 text-xs whitespace-nowrap"
                                    :class="row.status === 'agregar' ? 'text-accent font-semibold' :
                                            row.status === 'renombrar' ? 'text-amber-700 font-semibold' :
                                            row.status === 'eliminar' ? 'text-red-700 font-semibold' :
                                            'text-ink-muted'">
                                    {{ statusMeta[row.status]?.label || row.status }}
                                </td>
                            </tr>
                            <tr v-if="activeRows.length === 0">
                                <td colspan="4" class="px-3 py-6 text-center text-ink-muted italic">
                                    Sin cambios pendientes.
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

                <!-- Boton "Aplicar Cambios en TIA Portal" — accion
                     destructiva/commit. Mismo lenguaje pill que
                     Dispositivos.js (text-accent, bg-surface-sunken,
                     w-full, py-3, text-sm, contenido centrado). -->
                <button @click="handleApply"
                    :disabled="!plcName || isWorking || !hasPreview"
                    data-testid="entidades-apply-btn"
                    class="mt-3 w-full py-3 text-accent font-semibold text-sm bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    ✅ Aplicar Cambios en TIA Portal
                    <span v-if="hasPreview" class="text-xs font-normal text-ink-muted">
                        ({{ totalChanges }} cambios)
                    </span>
                </button>
            </div>
        </section>
    `,
};