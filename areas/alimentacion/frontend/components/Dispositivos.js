/**
 * Componente Dispositivos.
 *
 * Vista de Pre-Flight con dos secciones:
 *   1. **Cards de N_MAX** (arriba, estilo Definición programación):
 *      muestran las PlcUserConstant de la tabla
 *      ``000_Config_Dispositivos`` con su valor actual en TIA
 *      y el valor deseado del Excel. Solo dos estados posibles:
 *      ``actualizar`` (X → Y) o ``sin_cambios``.
 *   2. **Tabs por tipo de dispositivo** (ED/EA/SA/V/M/MVF por
 *      defecto; los 6 que vienen del ``config.json``) con la
 *      lista COMPLETA de PlcTag (no solo los que cambian) ordenada
 *      por ``numero`` ascendente.
 *
 * Estados por fila (devices):
 *   - "agregar"     ➕  (en AppState pero no en TIA)
 *   - "renombrar"   ✏️  (mismo numero, plc_tag distinto)
 *   - "eliminar"    🗑️  (en TIA pero no en AppState)
 *   - "sin_cambios" ✓  (mismo numero y mismo plc_tag)
 *
 * Cabecera: contadores agregados / renombrados / eliminados /
 * sin_cambios y un botón de "Aplicar Cambios en TIA Portal".
 *
 * Tema: Industrial Claro. Solo tokens semánticos del theme.
 *
 * **Migrado a data-driven**: los tabs y los labels de N_MAX
 * vienen de ``store.catalog`` (cargado al arrancar desde
 * ``GET /api/v1/catalog``). Añadir un nuevo ``hw_type`` o
 * ``N_MAX`` al ``config.json`` se refleja en esta vista sin
 * tocar JS. Si el catálogo aún no se ha cargado, se cae a
 * fallbacks ``[]`` (modo degradado, ver ``setup()``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 */
import { computed, ref } from "/js/vendor/vue.esm-browser.prod.js";
// Imports absolutos: ver nota en ``Sidebar.js``.
import { store, pushLog } from "/js/store.js";
import { apiGeneratePreview, apiCommit } from "/js/api.js";
import { STATUS_META } from "./disp_status.js";

export default {
    name: "Dispositivos",
    setup() {
        /**
         * Tabs data-driven desde el catalog del backend.
         * Si el catalog aún no se ha cargado (p.ej. SPA arrancando
         * con un backend no disponible), ``tabs`` es ``[]`` y la
         * vista se queda vacía (modo degradado).
         */
        const tabs = computed(() => {
            const c = store.catalog;
            if (!c || !Array.isArray(c.device_tabs)) return [];
            return c.device_tabs.map((t) => ({
                key: t.hw_type,
                canonical: t.canonical,
                label: t.label,
            }));
        });

        /**
         * Map ``canonical → label`` (p.ej. ``"DispED" → "ED"``)
         * derivado del catalog. Lo usa el filtro de filas para
         * saber qué ``type`` matchear en ``previewData.todos``.
         */
        const typeKeyByCanonical = computed(() => {
            const m = {};
            for (const t of tabs.value) m[t.canonical] = t.key;
            return m;
        });

        /**
         * Map ``N_MAX name → label`` (p.ej. ``"N_MAX_DISP_ED" →
         * "num_disp_ed"``) derivado del catalog. Lo usa la card
         * de N_MAX para mostrar el nombre humano. Si el catalog
         * no tiene el entry, fallback al ``name`` crudo.
         */
        const nmaxLabel = computed(() => {
            const m = {};
            const c = store.catalog;
            if (c && Array.isArray(c.nmax)) {
                for (const e of c.nmax) m[e.name] = e.label;
            }
            return m;
        });

        const activeTab = ref(
            tabs.value.length > 0 ? tabs.value[0].key : ""
        );

        const hasPreview = computed(
            () => !!store.previewData && Array.isArray(store.previewData.todos)
        );

        const summary = computed(() => {
            if (!hasPreview.value) {
                return { agregados: 0, renombrados: 0, eliminados: 0, sin_cambios: 0, total: 0 };
            }
            const s = store.previewData.summary || {};
            return {
                agregados:   s.agregados   ?? (store.previewData.agregados   || []).length,
                renombrados: s.renombrados ?? (store.previewData.renombrados || []).length,
                eliminados:  s.eliminados  ?? (store.previewData.eliminados  || []).length,
                sin_cambios: s.sin_cambios ?? 0,
                total:       s.total       ?? (store.previewData.todos || []).length,
            };
        });

        // N_MAX como cards (estética compartida con DefinicionProgramacion).
        const nmaxCards = computed(() => {
            if (!hasPreview.value) return [];
            return store.previewData.nmax?.todos || [];
        });

        const nmaxSummary = computed(() => {
            if (!hasPreview.value) {
                return { actualizar: 0, sin_cambios: 0, total: 0 };
            }
            return store.previewData.nmax?.summary || {
                actualizar: 0, sin_cambios: 0, total: 0,
            };
        });

        // Filas de la pestaña activa de devices.
        // El backend emite ``row.type`` con el ``hw_type`` corto
        // (``"ed"``, ``"ea"``, ...), por eso filtramos por el
        // ``key`` de la tab (NO por el ``canonical``).
        const activeRows = computed(() => {
            if (!hasPreview.value) return [];
            return (store.previewData.todos || [])
                .filter((r) => r.type === activeTab.value)
                .sort((a, b) => {
                    const an = typeof a.numero === "number" ? a.numero : 0;
                    const bn = typeof b.numero === "number" ? b.numero : 0;
                    return an - bn;
                });
        });

        // Contador por pestaña de devices.
        const tabCounts = computed(() => {
            const counts = Object.fromEntries(tabs.value.map((t) => [t.key, 0]));
            if (!hasPreview.value) return counts;
            for (const r of store.previewData.todos || []) {
                if (counts[r.type] !== undefined) counts[r.type] += 1;
            }
            return counts;
        });

        async function generarPreview() {
            if (!store.selectedPlc) return;
            store.busy = true;
            try {
                const r = await apiGeneratePreview(store.selectedPlc);
                if (r.ok) {
                    store.previewData = r.data;
                    pushLog("Previsión generada OK", "success");
                } else {
                    alert(
                        "Error generando prevision: " +
                            (r.data.detail || r.status)
                    );
                }
            } finally {
                store.busy = false;
            }
        }

        async function ejecutarCommit() {
            if (!store.previewData) return;
            const total = summary.value.agregados +
                          summary.value.renombrados +
                          summary.value.eliminados +
                          nmaxSummary.value.actualizar;
            if (
                !confirm(
                    `¿Aplicar ${total} cambios en TIA Portal?\n\n` +
                    `Devices:\n` +
                    `  Agregar: ${summary.value.agregados}\n` +
                    `  Renombrar: ${summary.value.renombrados}\n` +
                    `  Eliminar: ${summary.value.eliminados}\n\n` +
                    `N_MAX (dimensiones):\n` +
                    `  Actualizar: ${nmaxSummary.value.actualizar}\n\n` +
                    `Los "sin cambios" no se tocan.\n` +
                    `Esta operacion modifica el PLC.`
                )
            ) {
                return;
            }
            store.busy = true;
            try {
                const r = await apiCommit(
                    store.selectedPlc,
                    store.previewData
                );
                if (r.ok) {
                    // Tras un commit exitoso, el backend ya re-corre el
                    // preview y lo devuelve en `post_sync_preview`. Lo usamos
                    // para refrescar la vista directamente: si el sync fue
                    // completo, este preview mostrara 0 cambios (todo en sync).
                    // Si por algun motivo no viene (raro), hacemos fallback a
                    // llamar al endpoint de preview manualmente.
                    if (r.data && r.data.post_sync_preview) {
                        store.previewData = r.data.post_sync_preview;
                        pushLog(
                            "Transacción aplicada OK. Vista refrescada con estado post-sync.",
                            "success"
                        );
                    } else {
                        // Fallback: re-llamar al preview endpoint.
                        const rp = await apiGeneratePreview(
                            store.selectedPlc
                        );
                        if (rp.ok) {
                            store.previewData = rp.data;
                        }
                        pushLog(
                            "Transacción aplicada OK. Preview refrescado (fallback).",
                            "success"
                        );
                    }
                } else {
                    alert(
                        "Error aplicando: " + (r.data.detail || r.status)
                    );
                }
            } finally {
                store.busy = false;
            }
        }

        return {
            store,
            tabs,
            statusMeta: STATUS_META,
            nmaxLabel,
            hasPreview,
            summary,
            nmaxCards,
            nmaxSummary,
            activeTab,
            activeRows,
            tabCounts,
            generarPreview,
            ejecutarCommit,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">
            <!-- Cabecera mínima: solo el resumen de cambios + botón
                 "Generar Previsión". El título "⚡ Dispositivos" se
                 eliminó tras el rediseño "Modern Corporate" — el
                 topbar ya muestra la sub-vista activa. -->
            <div class="mb-4 bg-surface-raised border border-line rounded p-4 flex justify-between items-center"
                 data-testid="dispositivos-card-info">
                <p v-if="hasPreview" class="text-xs text-ink-muted">
                    {{ summary.total }} dispositivos analizados —
                    <span class="text-accent">{{ summary.agregados }} a agregar</span> ·
                    <span class="text-amber-700">{{ summary.renombrados }} a renombrar</span> ·
                    <span class="text-red-700">{{ summary.eliminados }} a eliminar</span> ·
                    <span class="text-ink-muted">{{ summary.sin_cambios }} sin cambios</span>
                </p>
                <span v-else></span>
                <button @click="generarPreview"
                    :disabled="!store.selectedPlc || store.busy"
                    data-testid="dispositivos-generar-prevision"
                    class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    🔍 Generar Previsión
                </button>
            </div>

            <!-- ★ Segundo card: engloba N_MAX + strip de tabs + tabla.
                 El operario pidió que TODA la información viviera dentro
                 de un único card; antes las N_MAX y los tabs vivían
                 sueltos. Se renderiza siempre: si no hay prevision, el
                 empty-state "Sin prevision generada" actúa de
                 placeholder (UX ya validada en la iteración anterior). ★ -->
            <div class="flex-1 bg-surface-raised border border-line rounded p-4 mb-4 flex flex-col overflow-hidden"
                 data-testid="dispositivos-card-tabla">

                <!-- N_MAX (estética de sub-cards: bg-surface-raised sobre
                     la card padre, separados por la rejilla de gap-2) -->
                <div v-if="hasPreview && nmaxCards.length > 0"
                    class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 mb-3">
                    <div v-for="card in nmaxCards" :key="card.name"
                        class="bg-surface-raised border border-line rounded p-3">
                        <div class="text-[10px] uppercase text-ink-muted">
                            {{ nmaxLabel[card.name] || card.name }}
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

                <!-- Tabs por tipo de dispositivo (ED|EA|SA|V|M|MVF) -->
                <div v-if="hasPreview" class="flex border-b border-line bg-surface-sunken overflow-x-auto mb-3">
                    <button v-for="t in tabs" :key="t.key"
                        @click="activeTab = t.key"
                        :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                                 activeTab === t.key ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                        {{ t.label }}
                        <span class="ml-1 text-[10px] opacity-70">({{ tabCounts[t.key] }})</span>
                    </button>
                </div>

                <!-- Área de scroll: contiene la tabla única de devices
                     o el empty-state "Sin prevision generada". Mismo
                     lenguaje de card que DispositivosPanel/ProcesosPanel:
                     la clase "bg-surface-raised border border-line rounded"
                     define el área scrollable de la tabla (sub-card
                     dentro de la card 2). -->
                <div class="flex-1 overflow-auto table-scroll-x mt-2 bg-surface-raised border border-line rounded">
                <table v-if="hasPreview" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted w-14">#</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Actual (TIA)</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Deseado (Excel)</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Estado</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in activeRows" :key="row.type + '-' + row.uid"
                            :class="statusMeta[row.status]?.cls">
                            <td class="px-3 py-1.5 font-mono text-xs text-ink-muted">
                                {{ row.numero }}
                            </td>
                            <td class="px-3 py-1.5 font-mono text-xs"
                                :class="row.status === 'eliminar' ? 'text-red-700 line-through' : 'text-ink'">
                                {{ row.actual || '—' }}
                            </td>
                            <td class="px-3 py-1.5 font-mono text-xs"
                                :class="row.status === 'agregar' ? 'text-accent' :
                                        row.status === 'renombrar' ? 'text-amber-800' :
                                        'text-ink-muted'">
                                {{ row.nuevo || '—' }}
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
                                ⚠️ Sin dispositivos para "{{ activeTab }}".
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
                </div><!-- /Área de scroll (cierre del wrapper interior de la card 2) -->
            </div><!-- /card 2 (N_MAX + tabs + tabla) -->

            <button id="btn-commit" @click="ejecutarCommit"
                :disabled="!hasPreview || (summary.agregados + summary.renombrados + summary.eliminados + nmaxSummary.actualizar === 0) || store.busy"
                data-testid="dispositivos-aplicar"
                class="mt-4 w-full py-3 text-accent font-bold text-sm bg-surface-raised border-2 border-accent hover:border-accent-bright hover:shadow-lg rounded-lg transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                ✅ Aplicar Cambios en TIA Portal
                <span v-if="hasPreview" class="text-xs font-normal text-ink-muted">
                    ({{ summary.agregados + summary.renombrados + summary.eliminados +
                       nmaxSummary.actualizar }} cambios)
                </span>
            </button>
        </section>
    `,
};
