/**
 * Componente SincronizacionTia.
 *
 * Vista de Pre-Flight con dos secciones:
 *   1. **Cards de N_MAX** (arriba, estilo Inspector de Memoria):
 *      muestran las 6 PlcUserConstant de la tabla
 *      ``000_Config_Dispositivos`` con su valor actual en TIA
 *      y el valor deseado del Excel. Solo dos estados posibles:
 *      ``actualizar`` (X → Y) o ``sin_cambios``.
 *   2. **Tabs por tipo de dispositivo** (ED/EA/SA/V/M/MVF) con la
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
 */
import { computed, ref } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store, pushLog } from "../store.js";
import { apiGeneratePreview, apiCommit } from "../api.js";

const DEVICE_TABS = [
    { key: "ed",    label: "ED — Entradas Digitales" },
    { key: "ea",    label: "EA — Entradas Analógicas" },
    { key: "sa",    label: "SA — Salidas Analógicas" },
    { key: "v",     label: "V — Válvulas" },
    { key: "m",     label: "M — Motores" },
    { key: "m_vf",  label: "MVF — Motores VFD" },
];

const STATUS_META = {
    agregar:      { label: "➕ AGREGAR",     cls: "action-add" },
    renombrar:    { label: "✏️ RENOMBRAR",  cls: "action-rename" },
    eliminar:     { label: "🗑️ ELIMINAR",   cls: "action-remove" },
    sin_cambios:  { label: "✓ OK",          cls: "action-ok" },
};

// Mapeo de nombre canónico de la N_MAX en TIA → key del
// ``DimensionesDispositivos``. Mantiene la misma estética que el
// Inspector de Memoria (``num_disp_ed``, ``num_disp_ea``, …).
const NMAX_LABEL = {
    "N_MAX_DISP_ED":   "num_disp_ed",
    "N_MAX_DISP_EA":   "num_disp_ea",
    "N_MAX_DISP_SA":   "num_disp_sa",
    "N_MAX_DISP_V":    "num_disp_v",
    "N_MAX_DISP_M":    "num_disp_m",
    "N_MAX_DISP_M_VF": "num_m_vf",
};

export default {
    name: "SincronizacionTia",
    setup() {
        const activeTab = ref(DEVICE_TABS[0].key);

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

        // N_MAX como cards (estilo Inspector de Memoria).
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
            const counts = Object.fromEntries(DEVICE_TABS.map((t) => [t.key, 0]));
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
                    pushLog("Transacción aplicada OK", "success");
                    store.previewData = null;
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
            tabs: DEVICE_TABS,
            statusMeta: STATUS_META,
            nmaxLabel: NMAX_LABEL,
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
            <header class="flex justify-between items-center mb-4">
                <div>
                    <h2 class="text-lg font-bold text-ink">📋 Previsión de Cambios</h2>
                    <p v-if="hasPreview" class="text-xs text-ink-muted mt-0.5">
                        {{ summary.total }} dispositivos analizados —
                        <span class="text-accent">{{ summary.agregados }} a agregar</span> ·
                        <span class="text-amber-700">{{ summary.renombrados }} a renombrar</span> ·
                        <span class="text-red-700">{{ summary.eliminados }} a eliminar</span> ·
                        <span class="text-ink-muted">{{ summary.sin_cambios }} sin cambios</span>
                    </p>
                </div>
                <button @click="generarPreview"
                    :disabled="!store.selectedPlc || store.busy"
                    class="px-4 py-2 bg-accent hover:bg-accent-hover disabled:opacity-50 rounded text-sm font-medium text-ink-inverse">
                    🔍 Generar Previsión
                </button>
            </header>

            <!-- ★ CARDS DE N_MAX (misma estética que Inspector de Memoria) ★ -->
            <div v-if="hasPreview && nmaxCards.length > 0"
                class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 mb-4">
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

            <!-- Tabs por tipo de dispositivo -->
            <div v-if="hasPreview" class="flex border-b border-line bg-surface-sunken overflow-x-auto">
                <button v-for="t in tabs" :key="t.key"
                    @click="activeTab = t.key"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeTab === t.key ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    {{ t.label }}
                    <span class="ml-1 text-[10px] opacity-70">({{ tabCounts[t.key] }})</span>
                </button>
            </div>

            <!-- Tabla única con TODOS los dispositivos del tipo activo -->
            <div class="flex-1 bg-surface-raised border border-line rounded overflow-auto table-scroll-x mt-2">
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
                            <td class="px-3 py-1.5 text-xs font-bold"
                                :class="row.status === 'agregar' ? 'text-accent' :
                                        row.status === 'renombrar' ? 'text-amber-700' :
                                        row.status === 'eliminar' ? 'text-red-700' :
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
                <div v-else class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded p-10 text-center text-ink-muted">
                    <div>
                        <div class="text-5xl mb-3 opacity-40">📋</div>
                        <p class="mb-2">Sin prevision generada.</p>
                        <p class="text-xs">Pulsa <strong class="text-accent">"🔍 Generar Previsión"</strong> para ver el diff completo.</p>
                    </div>
                </div>
            </div>

            <button id="btn-commit" @click="ejecutarCommit"
                :disabled="!hasPreview || (summary.agregados + summary.renombrados + summary.eliminados + nmaxSummary.actualizar === 0) || store.busy"
                class="mt-4 w-full py-3 bg-accent hover:bg-accent-hover disabled:opacity-50 rounded-lg text-base font-bold text-ink-inverse">
                ✅ Aplicar Cambios en TIA Portal
                <span v-if="hasPreview" class="ml-2 text-xs font-normal">
                    ({{ summary.agregados + summary.renombrados + summary.eliminados +
                       nmaxSummary.actualizar }} cambios)
                </span>
            </button>
        </section>
    `,
};
