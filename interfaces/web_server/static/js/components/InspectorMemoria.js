/**
 * Componente InspectorMemoria.
 *
 * Renderiza UNA SOLA TABLA REACTIVA alimentada por
 * ``activeDevices = computed(...)``. Esto elimina el bug histórico
 * que producían 6 wrappers ``v-for ... v-show`` apilados, cada uno
 * con su propio scroll y compitiendo por el ``flex-1``.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (`bg-surface-raised`, `bg-surface-sunken`, `text-ink`,
 * `text-ink-muted`, `text-accent`, `border-line`).
 *
 * @event refresh  El componente padre debe llamar a la API que
 *                 recarga ``store.memoryState``.
 */
import { computed, ref } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store } from "../store.js";

const DEVICE_TABS = [
    { key: "DispED",   label: "ED — Entradas Digitales" },
    { key: "DispEA",   label: "EA — Entradas Analógicas" },
    { key: "DispSA",   label: "SA — Salidas Analógicas" },
    { key: "DispV",    label: "V — Variables" },
    { key: "DispM",    label: "M — Motores" },
    { key: "DispM_VF", label: "MVF — Motores VFD" },
];

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

        const activeDevices = computed(() => {
            if (!store.memoryState || !store.memoryState.dispositivos) return [];
            return store.memoryState.dispositivos[activeTab.value] || [];
        });

        const dimensiones = computed(
            () => (store.memoryState && store.memoryState.dimensiones) || null
        );

        function formatAddress(d) {
            if (!d) return "";
            const fields = ADDRESS_FIELDS[activeTab.value] || [];
            return fields
                .map((p) => (d[p] !== undefined ? d[p] : ""))
                .join(".");
        }

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
                    <h2 class="text-lg font-bold text-ink">📊 Inspector de Memoria</h2>
                    <p class="text-xs text-ink-muted mt-0.5">
                        DTOs extraídos del Excel (AppState) — no requiere TIA Portal.
                    </p>
                </div>
                <button @click="$emit('refresh')" :disabled="store.busy"
                    class="px-4 py-2 bg-accent hover:bg-accent-hover disabled:opacity-50 rounded text-sm font-medium text-ink-inverse">
                    🔄 Refrescar Memoria
                </button>
            </header>

            <!-- Tarjeta de Dimensiones (N_MAX) -->
            <div v-if="dimensiones" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 mb-4">
                <div v-for="(value, key) in dimensiones" :key="key"
                    class="bg-surface-raised border border-line rounded p-3">
                    <div class="text-[10px] uppercase text-ink-muted">{{ key }}</div>
                    <div class="text-xl font-bold text-accent">{{ value }}</div>
                </div>
            </div>

            <!-- Tabs por tipo de dispositivo (anchura reservada) -->
            <div v-if="hasMemory" class="flex border-b border-line bg-surface-sunken overflow-x-auto">
                <button v-for="t in tabs" :key="t.key"
                    @click="activeTab = t.key"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeTab === t.key ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    {{ t.label }}
                    <span class="ml-1 text-[10px] opacity-70">
                        ({{ (store.memoryState.dispositivos[t.key] || []).length }})
                    </span>
                </button>
            </div>

            <!-- ★ TABLA ÚNICA REACTIVA ★ -->
            <div class="flex-1 overflow-auto table-scroll-x mt-2">
                <table v-if="hasMemory" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted">UID</th>
                            <th class="px-3 py-2 text-left text-ink-muted">PLC Tag</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Descripción</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Dirección</th>
                            <th class="px-3 py-2 text-right text-ink-muted">Número</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="d in activeDevices" :key="(d.uid || 'no-uid') + '-' + d.numero"
                            class="border-b border-line">
                            <td class="px-3 py-1.5 font-mono text-accent">{{ d.uid }}</td>
                            <td class="px-3 py-1.5 font-mono text-ink">{{ d.plc_tag }}</td>
                            <td class="px-3 py-1.5 text-ink-muted">{{ d.descripcion }}</td>
                            <td class="px-3 py-1.5 font-mono text-ink">{{ formatAddress(d) }}</td>
                            <td class="px-3 py-1.5 text-right font-semibold text-ink">{{ d.numero }}</td>
                        </tr>
                        <tr v-if="activeDevices.length === 0">
                            <td colspan="5" class="px-3 py-6 text-center text-ink-muted italic">
                                Sin dispositivos de este tipo. Sube un Excel para popular el AppState.
                            </td>
                        </tr>
                    </tbody>
                </table>
                <div v-else class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded mt-2 p-10 text-center text-ink-muted">
                    <div>
                        <div class="text-5xl mb-3 opacity-40">📊</div>
                        <p class="mb-2">El Inspector de Memoria está vacío.</p>
                        <p class="text-xs">Sube un Excel y pulsa <strong class="text-accent">"Refrescar Memoria"</strong>.</p>
                    </div>
                </div>
            </div>

        </section>
    `,
};
