/**
 * Componente Entidades.
 *
 * Vista top-level gemela de Dispositivos y Procesos en el sidebar del shell
 * SPA. Se muestra cuando ``store.currentView === 'entidades'``.
 *
 * Estructura (2 cards, mismo patron que Dispositivos.js):
 *   1. Card "info": summary del ultimo preview (counts de constants +
 *      comments) + boton "🔍 Generar Prevision".
 *   2. Card "tabla": N_MAX_ENTIDAD (sub-card arriba) + strip de 2 tabs
 *      ("Constantes" | "Comentarios") + tabla con 4 columnas
 *      (# / Actual (TIA) / Deseado (Excel) / Estado) + boton
 *      "✅ Aplicar Cambios en TIA Portal" abajo.
 *
 * El handler ``handlePreview`` consume ``/api/v1/entidades/preview``
 * que dispara el FB ``entidades_generar_preview``. El ``result`` se
 * guarda en ``lastPreview`` (ref local + ``store.entidadesLastPreview``)
 * y se renderiza en la card 2.
 *
 * El handler ``handleApply`` consume ``/api/v1/entidades/sincronizar``
 * (sigue siendo stub en commit D).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * ``vue.esm-browser.prod.js`` NO acepta string literals multi-linea
 * dentro de arrays de ``:class``. Cada literal va en una sola linea.
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
         * Resultado del ultimo ``/api/v1/entidades/preview``.
         * ``null`` o dict con la shape completa del FB. La card 1 lo
         * muestra como summary (counts) y la card 2 lo renderiza como
         * tabla de diff.
         */
        const lastPreview = ref(null);

        /**
         * True si hay un preview con precondiciones OK. Equivalente a
         * ``hasPreview`` de Dispositivos.js pero particularizado para
         * el shape del FB de entidades (``precondiciones_ok`` en lugar
         * de chequear ``store.previewData.todos``).
         */
        const hasPreview = computed(
            () => !!lastPreview.value && lastPreview.value.precondiciones_ok === true
        );

        /**
         * N_MAX_ENTIDAD como sub-card (estilo sub-cards de Dispositivos).
         * Si no hay preview o el XML no existia, lista vacia (la
         * sub-card simplemente no se renderiza).
         */
        const nmaxCards = computed(() => {
            if (!hasPreview.value) return [];
            return (lastPreview.value.nmax && lastPreview.value.nmax.todos) || [];
        });

        const nmaxSummary = computed(() => {
            if (!hasPreview.value) {
                return { actualizar: 0, sin_cambios: 0, total: 0 };
            }
            return (lastPreview.value.nmax && lastPreview.value.nmax.summary)
                || { actualizar: 0, sin_cambios: 0, total: 0 };
        });

        /**
         * Strip de 2 tabs: "Constantes" (tabla de PlcUserConstants
         * ``ent_<plc_tag>`` en ``6_Entidades``) y "Comentarios"
         * (tabla de comentarios del array ``ENT[]`` de ``DB6_ENT``).
         */
        const tabs = computed(() => [
            { key: "constantes",  label: "Constantes" },
            { key: "comentarios", label: "Comentarios" },
        ]);

        const activeTab = ref("constantes");

        /**
         * Filas de la tab activa:
         *   - "constantes"  -> ``constants.todos`` del FB
         *     (``{plc_tag, actual, nuevo, status}``).
         *   - "comentarios" -> ``arrays.ENT`` del FB
         *     (``{slot, actual, nuevo, status}``).
         *
         * Las constantes se ordenan por ``plc_tag`` ascendente
         * (string compare estable). Los comentarios por ``slot``
         * numerico ascendente.
         */
        const activeRows = computed(() => {
            if (!hasPreview.value) return [];
            const p = lastPreview.value;
            if (activeTab.value === "constantes") {
                const todos = (p.constants && p.constants.todos) || [];
                return todos.slice().sort((a, b) => {
                    const an = String(a.plc_tag || "");
                    const bn = String(b.plc_tag || "");
                    return an.localeCompare(bn);
                });
            }
            if (activeTab.value === "comentarios") {
                const arr = (p.arrays && p.arrays.ENT) || [];
                return arr.slice().sort((a, b) => {
                    const an = typeof a.slot === "number" ? a.slot : 0;
                    const bn = typeof b.slot === "number" ? b.slot : 0;
                    return an - bn;
                });
            }
            return [];
        });

        /**
         * Contadores por tab para los badges del strip.
         * Suma solo estados "relevantes" (agregar/renombrar/eliminar)
         * para que el badge indique volumen de cambios pendientes.
         */
        const tabCounts = computed(() => {
            if (!hasPreview.value) return { constantes: 0, comentarios: 0 };
            const p = lastPreview.value;
            const constants = (p.constants && p.constants.todos) || [];
            const arraysEnt = (p.arrays && p.arrays.ENT) || [];
            const countChanges = (rows) => rows.filter(
                (r) => r.status === "agregar"
                    || r.status === "renombrar"
                    || r.status === "eliminar"
            ).length;
            return {
                constantes:  countChanges(constants),
                comentarios: countChanges(arraysEnt),
            };
        });

        /**
         * Summary legible del ultimo preview para la cabecera.
         * Si no hay preview o el preview fallo, devuelve
         * "Sin prevision" (mismo patron que ``Dispositivos.js``).
         */
        const previewSummary = computed(() => {
            const p = lastPreview.value;
            if (!p || !p.precondiciones_ok) return "Sin prevision";
            const s = p.summary || {};
            return (
                `${s.constants_agregados || 0} const adds · `
                + `${s.comments_added || 0} comments adds · `
                + `${s.comments_updated || 0} comments updates`
            );
        });

        /**
         * Total de cambios pendientes (todos los vectores), para el
         * badge del boton "Aplicar Cambios". Es la suma de constants
         * adds/renames/removes + comments adds/updates.
         */
        const totalChanges = computed(() => {
            if (!hasPreview.value) return 0;
            const s = lastPreview.value.summary || {};
            return (
                (s.constants_agregados || 0)
                + (s.constants_eliminados || 0)
                + (s.constants_renombrados || 0)
                + (s.comments_added || 0)
                + (s.comments_updated || 0)
                + (nmaxSummary.value.actualizar || 0)
            );
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
            isWorking,
            lastPreview,
            hasPreview,
            nmaxCards,
            nmaxLabel: nmaxLabelEntidades,
            nmaxSummary,
            tabs,
            activeTab,
            activeRows,
            tabCounts,
            previewSummary,
            totalChanges,
            statusMeta: STATUS_META,
            handlePreview,
            handleApply,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- ★ Card "info" (estilo Dispositivos.js): summary del
                 ultimo preview (o vacio) + boton "🔍 Generar
                 Prevision". ★ -->
            <div class="mb-4 bg-surface-raised border border-line rounded p-4 flex justify-between items-center"
                 data-testid="entidades-card-info">
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

            <!-- ★ Card "tabla" (estilo Dispositivos.js): NMAX_ENTIDAD
                 + strip de tabs + tabla de diff + boton aplicar. ★ -->
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

                <!-- Strip de tabs "Constantes" | "Comentarios". Mismo
                     lenguaje que Dispositivos.js (bg-surface-sunken,
                     border-b border-line, tab-btn class). -->
                <div v-if="hasPreview" class="flex border-b border-line bg-surface-sunken overflow-x-auto mb-3">
                    <button v-for="t in tabs" :key="t.key"
                        @click="activeTab = t.key"
                        data-testid="entidades-tab-btn"
                        :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                                 activeTab === t.key ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                        {{ t.label }}
                        <span class="ml-1 text-[10px] opacity-70">({{ tabCounts[t.key] }})</span>
                    </button>
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
                                <td class="px-3 py-1.5 font-mono text-xs text-ink-muted">
                                    <template v-if="activeTab === 'comentarios'">
                                        {{ row.slot }}
                                    </template>
                                    <template v-else>
                                        {{ row.plc_tag }}
                                    </template>
                                </td>
                                <td class="px-3 py-1.5 font-mono text-xs"
                                    :class="row.status === 'eliminar' ? 'text-red-700 line-through' : 'text-ink'">
                                    {{ row.actual === null || row.actual === undefined ? '—' : row.actual }}
                                </td>
                                <td class="px-3 py-1.5 font-mono text-xs"
                                    :class="row.status === 'agregar' ? 'text-accent' :
                                            row.status === 'renombrar' ? 'text-amber-800' :
                                            'text-ink-muted'">
                                    {{ row.nuevo === null || row.nuevo === undefined ? '—' : row.nuevo }}
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
                                    ⚠️ Sin entradas para "{{ tabs.find((t) => t.key === activeTab)?.label }}".
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