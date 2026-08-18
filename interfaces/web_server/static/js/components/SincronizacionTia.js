/**
 * Componente SincronizacionTia.
 *
 * Vista de Diff + botones "Generar Previsión" y "Aplicar Cambios".
 * Lee ``store.previewData`` y ``store.selectedPlc`` para renderizar
 * el resultado de la Pre-Flight.
 */
import { computed } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store, pushLog } from "../store.js";
import { apiGeneratePreview, apiCommit } from "../api.js";

export default {
    name: "SincronizacionTia",
    setup() {
        /** ¿Hay previsualización válida para mostrar? */
        const hasPreview = computed(
            () =>
                !!store.previewData &&
                ((store.previewData.agregados || []).length > 0 ||
                    (store.previewData.eliminados || []).length > 0 ||
                    (store.previewData.renombrados || []).length > 0)
        );

        /** Total de cambios para mostrar en el botón. */
        const totalChanges = computed(() => {
            if (!store.previewData) return 0;
            return (
                (store.previewData.agregados || []).length +
                (store.previewData.eliminados || []).length +
                (store.previewData.renombrados || []).length
            );
        });

        /** Genera la Pre-Flight (Diff) contra el PLC seleccionado. */
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

        /** Aplica la Pre-Flight actual al PLC. */
        async function ejecutarCommit() {
            if (!store.previewData) return;
            if (
                !confirm(
                    `¿Aplicar ${totalChanges.value} cambios en TIA Portal?\n\nEsta operacion modifica el PLC.`
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
            hasPreview,
            totalChanges,
            generarPreview,
            ejecutarCommit,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">
            <header class="flex justify-between items-center mb-4">
                <h2 class="text-lg font-bold text-slate-200">📋 Previsión de Cambios</h2>
                <button @click="generarPreview"
                    :disabled="!store.selectedPlc || store.busy"
                    class="px-4 py-2 bg-amber-700 hover:bg-amber-600 disabled:opacity-50 rounded text-sm font-medium">
                    Generar Previsión
                </button>
            </header>

            <div class="flex-1 bg-slate-800 border border-slate-700 rounded overflow-auto table-scroll-x">
                <table class="w-full">
                    <thead class="sticky top-0 bg-slate-700 text-xs uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left">UID</th>
                            <th class="px-3 py-2 text-left">Variable Actual</th>
                            <th class="px-3 py-2 text-left">Nueva Variable</th>
                            <th class="px-3 py-2 text-left">Acción</th>
                        </tr>
                    </thead>
                    <tbody v-if="store.previewData">
                        <tr v-for="d in store.previewData.agregados || []" :key="'a-' + d.uid" class="action-add">
                            <td class="px-3 py-2 font-mono text-xs">{{ d.uid }}</td>
                            <td class="px-3 py-2 text-slate-500 italic text-xs">(no existe)</td>
                            <td class="px-3 py-2 text-green-400 text-xs">{{ d.plc_tag }}</td>
                            <td class="px-3 py-2 text-xs font-bold text-green-400">➕ AGREGAR</td>
                        </tr>
                        <tr v-for="d in store.previewData.eliminados || []" :key="'r-' + d.uid" class="action-remove">
                            <td class="px-3 py-2 font-mono text-xs">{{ d.uid }}</td>
                            <td class="px-3 py-2 text-red-300 text-xs">{{ d.plc_tag }}</td>
                            <td class="px-3 py-2 text-slate-500 italic text-xs">(se elimina)</td>
                            <td class="px-3 py-2 text-xs font-bold text-red-400">ELIMINAR</td>
                        </tr>
                        <tr v-for="d in store.previewData.renombrados || []" :key="'m-' + d.uid" class="action-rename">
                            <td class="px-3 py-2 font-mono text-xs">{{ d.uid }}</td>
                            <td class="px-3 py-2 text-yellow-300 text-xs">{{ d.actual }}</td>
                            <td class="px-3 py-2 text-yellow-200 text-xs">{{ d.nuevo }}</td>
                            <td class="px-3 py-2 text-xs font-bold text-yellow-400">✏️ RENOMBRAR</td>
                        </tr>
                        <tr v-if="!hasPreview">
                            <td colspan="4" class="px-3 py-6 text-center text-slate-500 italic">
                                Sin prevision generada. Pulsa "🔍 Generar Previsión".
                            </td>
                        </tr>
                    </tbody>
                    <tbody v-else>
                        <tr>
                            <td colspan="4" class="px-3 py-6 text-center text-slate-500 italic">
                                Pulsa "🔍 Generar Previsión" para ver los cambios.
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <button id="btn-commit" @click="ejecutarCommit"
                :disabled="!store.previewData || store.busy"
                class="mt-4 w-full py-3 bg-green-700 hover:bg-green-600 disabled:opacity-50 rounded-lg text-base font-bold">
                ✅ Aplicar Cambios en TIA Portal
                <span v-if="hasPreview" class="ml-2 text-xs font-normal">
                    ({{ totalChanges }} cambios)
                </span>
            </button>
        </section>
    `,
};
