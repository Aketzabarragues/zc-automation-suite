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
 *      Contador total etiquetado "X entidades analizadas" (C.22: no
 *      segmentar por constantes vs comentarios; un solo total).
 *   2. Card "tabla": sub-card de N_MAX_ENTIDAD arriba (estilo sub-cards
 *      de Dispositivos) + tabla unica con 6 columnas
 *      (# / Tag Actual (TIA) / Comentario Actual (TIA)
 *       / Tag Deseado (Excel) / Comentario Deseado (Excel) / Estado)
 *      + boton "✅ Aplicar Cambios en TIA Portal" abajo.
 *
 * Las 6 columnas reflejan el diff unificado de C.22 (regla
 * "Excel manda"): un solo match por ``plc_tag`` literal cruza TIA con
 * Excel. Shape del row:
 *   ``{plc_tag, numero_tia, comment_tia, numero_excel, comment_excel, status}``
 * Mismo plc_tag + mismo value: comparar comments. Mismo plc_tag +
 * distinto value: 2 filas separadas (eliminar TIA + agregar Excel).
 * plc_tag solo en TIA: eliminar. plc_tag solo en Excel: agregar.
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
         * 4 contadores de status agregados desde ``data.ops`` (lista
         * unica de 5 pasadas de Aketza). SIEMPRE devuelve un dict con
         * los 4 keys, aunque no haya preview (los 4 counters en 0).
         * Esto permite que la card 1 siempre renderice el mismo patron
         * visual sin empty-state "Sin prevision".
         */
        const summary = computed(() => {
            if (!hasPreview.value) {
                return { agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 0, total: 0 };
            }
            const ops = store.previewData.ops || [];
            const eliminados = ops.filter((o) => o.kind === "delete").length;
            const agregados = ops.filter((o) => o.kind === "add").length;
            const renombrados = ops.filter(
                (o) => o.kind === "rename" || o.kind === "update_comment"
            ).length;
            const desired = (store.previewData.entities_block && store.previewData.entities_block.desired)
                ? store.previewData.entities_block.desired
                : null;
            const total = desired ? Object.keys(desired).length : 0;
            return { agregados, renombrados, eliminados, sin_cambios: total, total };
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
         * Filas de la tabla principal: ops del sync (5 pasadas de
         * Aketza). Cada op se proyecta a un row con shape uniforme:
         *   - ``{plc_tag, status, value_tia, value_excel, comment_tia, comment_excel}``.
         *
         * El status se deriva del kind: delete, add, rename, update_comment.
         * Sort por plc_tag (string) ascendente; tie-breaker por status
         * para agrupar pares delete/add del mismo plc_tag.
         */
        const activeRows = computed(() => {
            if (!hasPreview.value) return [];
            const ops = store.previewData.ops || [];
            const statusOrder = { delete: 0, rename: 1, update_comment: 2, add: 3 };
            const rows = ops.map((op) => {
                if (op.kind === "delete") {
                    return {
                        plc_tag:      op.plc_tag,
                        status:       "eliminar",
                        numero_tia:   op.value_tia,
                        comment_tia:  null,
                        numero_excel: null,
                        comment_excel: null,
                    };
                }
                if (op.kind === "add") {
                    return {
                        plc_tag:      op.plc_tag,
                        status:       "agregar",
                        numero_tia:   null,
                        comment_tia:  null,
                        numero_excel: op.value_excel,
                        comment_excel: op.comment_excel || null,
                    };
                }
                if (op.kind === "rename") {
                    return {
                        plc_tag:      `${op.plc_tag_tia} -> ${op.plc_tag_new}`,
                        status:       "renombrar",
                        numero_tia:   op.value_tia,
                        comment_tia:  null,
                        numero_excel: op.value_tia,
                        comment_excel: null,
                    };
                }
                if (op.kind === "update_comment") {
                    return {
                        plc_tag:      op.plc_tag,
                        status:       "renombrar",
                        numero_tia:   op.value_tia,
                        comment_tia:  op.comment_tia || null,
                        numero_excel: op.value_tia,
                        comment_excel: op.comment_excel || null,
                    };
                }
                return null;
            }).filter((r) => r !== null);
            return rows.sort((a, b) => {
                const at = (a.plc_tag || "").toString();
                const bt = (b.plc_tag || "").toString();
                if (at !== bt) return at.localeCompare(bt);
                return (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9);
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
                <p v-if="hasPreview" class="text-xs text-ink-muted"
                   data-testid="entidades-preview-summary">
                    {{ summary.total }} entidades analizadas —
                    <span class="text-accent">{{ summary.agregados }} a agregar</span> ·
                    <span class="text-amber-700">{{ summary.renombrados }} a renombrar</span> ·
                    <span class="text-red-700">{{ summary.eliminados }} a eliminar</span> ·
                    <span class="text-ink-muted">{{ summary.sin_cambios }} sin cambios</span>
                </p>
                <span v-else></span>
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
                                <th class="px-3 py-2 text-left text-ink-muted">Tag Actual (TIA)</th>
                                <th class="px-3 py-2 text-left text-ink-muted">Comentario Actual (TIA)</th>
                                <th class="px-3 py-2 text-left text-ink-muted">Tag Deseado (Excel)</th>
                                <th class="px-3 py-2 text-left text-ink-muted">Comentario Deseado (Excel)</th>
                                <th class="px-3 py-2 text-left text-ink-muted">Estado</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="(row, idx) in activeRows" :key="idx"
                                class="border-b border-line"
                                :class="statusMeta[row.status]?.cls">
                                <!-- # (C.22): Excel manda. Preferimos
                                     numero_excel; si no hay (eliminar)
                                     mostramos numero_tia. -->
                                <td class="px-3 py-1.5 font-mono text-xs text-ink-muted">
                                    {{ (row.numero_excel ?? row.numero_tia) === null ? '—' : (row.numero_excel ?? row.numero_tia) }}
                                </td>
                                <!-- Tag Actual (TIA): row.plc_tag si TIA
                                     lo tiene (status !== 'agregar'),
                                     si no guion. -->
                                <td class="px-3 py-1.5 font-mono text-xs"
                                    :class="row.status === 'eliminar' ? 'text-red-700 line-through' : 'text-ink'">
                                    {{ row.status === 'agregar' ? '—' : row.plc_tag }}
                                </td>
                                <!-- Comentario Actual (TIA): comment_tia
                                     si TIA lo tiene. -->
                                <td class="px-3 py-1.5 text-xs"
                                    :class="row.status === 'eliminar' ? 'text-red-700 line-through' : 'text-ink'">
                                    {{ row.comment_tia === null || row.comment_tia === undefined ? '—' : row.comment_tia }}
                                </td>
                                <!-- Tag Deseado (Excel): row.plc_tag si
                                     Excel lo tiene (status !== 'eliminar'),
                                     si no guion. -->
                                <td class="px-3 py-1.5 font-mono text-xs"
                                    :class="row.status === 'agregar' ? 'text-accent' :
                                            row.status === 'renombrar' ? 'text-amber-800' :
                                            'text-ink-muted'">
                                    {{ row.status === 'eliminar' ? '—' : row.plc_tag }}
                                </td>
                                <!-- Comentario Deseado (Excel): comment_excel
                                     si Excel lo tiene. -->
                                <td class="px-3 py-1.5 text-xs"
                                    :class="row.status === 'agregar' ? 'text-accent' :
                                            row.status === 'renombrar' ? 'text-amber-800' :
                                            'text-ink-muted'">
                                    {{ row.comment_excel === null || row.comment_excel === undefined ? '—' : row.comment_excel }}
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
                                <td colspan="6" class="px-3 py-6 text-center text-ink-muted italic">
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