/**
 * Componente InspectorMemoria.
 *
 * Renderiza UNA SOLA TABLA REACTIVA con TODAS las columnas del
 * dataclass activo (DispED / DispEA / DispSA / DispV / DispM /
 * DispM_VF). Pensado como dump de Cache: el operario ve, fila por
 * fila, el contenido íntegro de la AppState sin tener que
 * descargar el JSON.
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
    { key: "DispV",    label: "V — Valvulas" },
    { key: "DispM",    label: "M — Motores" },
    { key: "DispM_VF", label: "MVF — Motores VFD" },
];

const MODEL_COLUMNS = {
    DispED: [
        "uid", "numero", "plc_tag", "plc_comentario", "descripcion",
        "tag", "fat",
        "e_byte", "e_bit",
        "gr_alarma", "cuadro", "observaciones",
        "plc_tipo", "plc_index",
        "hmi_index", "hmi_texto",
        "comentario_db",
    ],
    DispEA: [
        "uid", "numero", "plc_tag", "plc_comentario", "descripcion",
        "tag", "fat",
        "e_byte",
        "unidades", "rii", "rsi",
        "gr_alarma", "cuadro", "observaciones",
        "plc_tipo", "plc_index",
        "hmi_index", "hmi_texto",
        "comentario_db",
    ],
    DispSA: [
        "uid", "numero", "plc_tag", "plc_comentario", "descripcion",
        "tag", "fat",
        "e_byte",
        "unidades", "rii", "rsi",
        "gr_alarma", "cuadro", "observaciones",
        "plc_tipo", "plc_index",
        "hmi_index", "hmi_texto",
        "comentario_db",
    ],
    DispV: [
        "uid", "numero", "plc_tag", "plc_comentario", "descripcion",
        "tag", "fat",
        "s_byte", "s_bit",
        "rr_byte", "rr_bit",
        "rt_byte", "rt_bit",
        "gr_alarma", "cuadro", "observaciones",
        "plc_tipo", "plc_index",
        "hmi_index", "hmi_texto",
        "comentario_db",
    ],
    DispM: [
        "uid", "numero", "plc_tag", "plc_comentario", "descripcion",
        "tag", "fat",
        "s_byte", "s_bit",
        "rt_byte", "rt_bit",
        "rm_byte", "rm_bit",
        "gr_alarma", "cuadro", "observaciones",
        "plc_tipo", "plc_index",
        "hmi_index", "hmi_texto",
        "comentario_db",
    ],
    DispM_VF: [
        "uid", "numero", "plc_tag", "plc_comentario", "descripcion",
        "tag", "fat",
        "s_byte", "s_bit",
        "rt_byte", "rt_bit",
        "rm_byte", "rm_bit",
        "sa_byte",
        "gr_alarma", "cuadro", "observaciones",
        "plc_tipo", "plc_index",
        "hmi_index", "hmi_texto",
        "comentario_db",
    ],
};

const COL_LABELS = {
    uid: "UID",
    numero: "Número",
    plc_tag: "PLC Tag",
    plc_comentario: "Comentario PLC",
    descripcion: "Descripción",
    tag: "TAG",
    fat: "FAT",
    e_byte: "E.Byte",
    e_bit: "E.Bit",
    s_byte: "S.Byte",
    s_bit: "S.Bit",
    rr_byte: "RR.Byte",
    rr_bit: "RR.Bit",
    rt_byte: "RT.Byte",
    rt_bit: "RT.Bit",
    rm_byte: "RM.Byte",
    rm_bit: "RM.Bit",
    sa_byte: "SA.Byte",
    unidades: "Unidades",
    rii: "RII",
    rsi: "RSI",
    gr_alarma: "Gr.Alarma",
    cuadro: "Cuadro",
    observaciones: "Observaciones",
    plc_tipo: "PLC.Tipo",
    plc_index: "PLC.Index",
    hmi_index: "Hmi.Index",
    hmi_texto: "Hmi.Texto",
    comentario_db: "ComentarioDB",
};

const MONO_COLS = new Set(["uid", "plc_tag", "plc_comentario"]);

export default {
    name: "InspectorMemoria",
    emits: ["refresh"],
    setup() {
        const activeTab = ref(store.activeTab);

        const columns = computed(() => MODEL_COLUMNS[activeTab.value] || []);

        const activeDevices = computed(() => {
            if (!store.memoryState || !store.memoryState.dispositivos) return [];
            return store.memoryState.dispositivos[activeTab.value] || [];
        });

        const dimensiones = computed(
            () => (store.memoryState && store.memoryState.dimensiones) || null
        );

        const hasMemory = computed(
            () => !!(store.memoryState && store.memoryState.dispositivos)
        );

        function displayValue(value) {
            if (value === null || value === undefined) return "—";
            if (typeof value === "string" && value.trim() === "") return "—";
            return String(value);
        }

        return {
            store,
            tabs: DEVICE_TABS,
            activeTab,
            columns,
            activeDevices,
            dimensiones,
            hasMemory,
            displayValue,
            COL_LABELS,
            MONO_COLS, // <-- CORRECCIÓN: Exportado a la vista
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <header class="flex justify-between items-center mb-4">
                <div>
                    <h2 class="text-lg font-bold text-ink">📊 Inspector de Memoria</h2>
                    <p class="text-xs text-ink-muted mt-0.5">
                        Dump completo de la cache (AppState) — todas las columnas del dataclass activo.
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

            <!-- Tabs por tipo de dispositivo -->
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

            <!-- ★ TABLA ÚNICA REACTIVA: dump de TODAS las columnas del dataclass activo ★ -->
            <div class="flex-1 overflow-auto table-scroll-x mt-2">
                <table v-if="hasMemory" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th v-for="col in columns" :key="col"
                                class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">
                                {{ COL_LABELS[col] || col }}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="d in activeDevices"
                            :key="(d.uid || 'no-uid') + '-' + d.numero"
                            class="border-b border-line">
                            <td v-for="col in columns" :key="col"
                                class="px-3 py-1.5 align-top text-ink whitespace-nowrap"
                                :class="MONO_COLS.has(col) ? 'font-mono' : ''">
                                {{ displayValue(d[col]) }}
                            </td>
                        </tr>
                        <tr v-if="activeDevices.length === 0">
                            <td :colspan="columns.length || 5"
                                class="px-3 py-6 text-center text-ink-muted italic">
                                ⚠️ La pestaña "{{ activeTab }}" no contiene dispositivos. Si el Excel fue cargado, verifique que la tabla exista y no esté vacía.
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