/**
 * Componente InspectorMemoria.
 *
 * Renderiza UNA SOLA TABLA REACTIVA alimentada por
 * ``activeDevices = computed(...)``. Esto elimina el bug histórico
 * que producían 6 wrappers ``v-for ... v-show`` apilados, cada uno
 * con su propio scroll y compitiendo por el ``flex-1``.
 *
 * @event refresh  El componente padre debe llamar a la API que
 *                 recarga ``store.memoryState`` (no la hacemos aquí
 *                 para mantener el componente desacoplado de la API).
 */
import { computed, ref } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store } from "../store.js";

/** Definición declarativa de las 6 pestañas del Inspector. */
const DEVICE_TABS = [
    { key: "DispED",   label: "ED — Entradas Digitales" },
    { key: "DispEA",   label: "EA — Entradas Analógicas" },
    { key: "DispSA",   label: "SA — Salidas Analógicas" },
    { key: "DispV",    label: "V — Variables" },
    { key: "DispM",    label: "M — Motores" },
    { key: "DispM_VF", label: "MVF — Motores VFD" },
];

/** Composición de la columna "Dirección" por tipo de dispositivo. */
const ADDRESS_FIELDS = {
    DispED:   ["e_byte", "e_bit"],
    DispEA:   ["e_byte"],
    DispSA:   ["e_byte"],
    DispV:    ["s_byte", "s_bit"],
    DispM:    ["s_byte", "s_bit"],
    DispM_VF: ["s_byte", "s_bit"],
};

export default {
    name: "InspectorMemoria",
    emits: ["refresh"],
    setup() {
        const activeTab = ref(store.activeTab);

        /** Dispositivos visibles de la pestaña activa (reactive). */
        const activeDevices = computed(() => {
            if (!store.memoryState || !store.memoryState.dispositivos) return [];
            return store.memoryState.dispositivos[activeTab.value] || [];
        });

        /** Dimensiones N_MAX de la AppState (para tarjetas resumen). */
        const dimensiones = computed(
            () => (store.memoryState && store.memoryState.dimensiones) || null
        );

        /** Concatena los campos de dirección configurados por tipo. */
        function formatAddress(d) {
            if (!d) return "";
            const fields = ADDRESS_FIELDS[activeTab.value] || [];
            return fields
                .map((p) => (d[p] !== undefined ? d[p] : ""))
                .join(".");
        }

        /** Helper: ¿hay memoria cargada en el AppState? */
        const hasMemory = computed(
            () => !!(store.memoryState && store.memoryState.dispositivos)
        );

        return {
            store,
            tabs: DEVICE_TABS,
            activeTab,
            activeDevices,
            dimensiones,
            hasMemory,
            formatAddress,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <header class="flex justify-between items-center mb-4">
                <div>
                    <h2 class="text-lg font-bold text-slate-200">📊 Inspector de Memoria</h2>
                    <p class="text-xs text-slate-400 mt-0.5">
                        DTOs extraídos del Excel (AppState) — no requiere TIA Portal.
                    </p>
                </div>
                <button @click="$emit('refresh')" :disabled="store.busy"
                    class="px-4 py-2 bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 rounded text-sm font-medium">
                    🔄 Refrescar Memoria
                </button>
            </header>

            <!-- Tarjeta de Dimensiones (N_MAX) -->
            <div v-if="dimensiones" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 mb-4">
                <div v-for="(value, key) in dimensiones" :key="key"
                    class="dim-card bg-slate-800 border border-slate-700 rounded p-3">
                    <div class="text-[10px] uppercase text-slate-400">{{ key }}</div>
                    <div class="text-xl font-bold text-cyan-300">{{ value }}</div>
                </div>
            </div>

            <!-- Tabs por tipo de dispositivo (anchura reservada) -->
            <div v-if="hasMemory" class="flex border-b border-slate-700 bg-slate-900 overflow-x-auto">
                <button v-for="t in tabs" :key="t.key"
                    @click="activeTab = t.key"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-slate-700 whitespace-nowrap',
                             activeTab === t.key ? 'active' : 'bg-slate-800 text-slate-300 hover:bg-slate-700']">
                    {{ t.label }}
                    <span class="ml-1 text-[10px] opacity-70">
                        ({{ (store.memoryState.dispositivos[t.key] || []).length }})
                    </span>
                </button>
            </div>

            <!-- ★ TABLA ÚNICA REACTIVA ★ -->
            <div class="flex-1 overflow-auto table-scroll-x mt-2">
                <table v-if="hasMemory" class="w-full text-xs">
                    <thead class="sticky top-0 bg-slate-700 text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left">UID</th>
                            <th class="px-3 py-2 text-left">PLC Tag</th>
                            <th class="px-3 py-2 text-left">Descripción</th>
                            <th class="px-3 py-2 text-left">Dirección</th>
                            <th class="px-3 py-2 text-right">Número</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="d in activeDevices" :key="(d.uid || 'no-uid') + '-' + d.numero"
                            class="border-b border-slate-700/50">
                            <td class="px-3 py-1.5 font-mono text-cyan-200">{{ d.uid }}</td>
                            <td class="px-3 py-1.5 font-mono text-slate-100">{{ d.plc_tag }}</td>
                            <td class="px-3 py-1.5 text-slate-300">{{ d.descripcion }}</td>
                            <td class="px-3 py-1.5 font-mono text-amber-200">{{ formatAddress(d) }}</td>
                            <td class="px-3 py-1.5 text-right font-semibold text-slate-200">{{ d.numero }}</td>
                        </tr>
                        <tr v-if="activeDevices.length === 0">
                            <td colspan="5" class="px-3 py-6 text-center text-slate-500 italic">
                                Sin dispositivos de este tipo. Sube un Excel para popular el AppState.
                            </td>
                        </tr>
                    </tbody>
                </table>
                <div v-else class="flex-1 flex items-center justify-center bg-slate-800 border border-slate-700 border-dashed rounded mt-2 p-10 text-center text-slate-500">
                    <div>
                        <div class="text-5xl mb-3 opacity-40">📊</div>
                        <p class="mb-2">El Inspector de Memoria está vacío.</p>
                        <p class="text-xs">Sube un Excel y pulsa <strong class="text-cyan-300">"Refrescar Memoria"</strong>.</p>
                    </div>
                </div>
            </div>

        </section>
    `,
};
