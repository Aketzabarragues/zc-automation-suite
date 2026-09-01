/**
 * Componente DefinicionProgramacion.
 *
 * Vista que combina:
 *   1. Carga excel (antes en el Sidebar, ahora al inicio
 *      de esta vista).
 *   2. Inspector de Memoria: tabla reactiva con todas las columnas
 *      del dataclass activo (DispED / DispEA / DispSA / DispV /
 *      DispM / DispM_VF — el conjunto se carga del ``config.json``
 *      vía ``/api/v1/catalog``) + cards de N_MAX.
 *
 * Pensado como dump de Cache: el operario ve, fila por fila, el
 * contenido íntegro de la AppState sin tener que descargar el JSON.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (`bg-surface-raised`, `bg-surface-sunken`, `text-ink`,
 * `text-ink-muted`, `text-accent`, `border-line`).
 *
 * **Migrado a data-driven**: las pestañas, las columnas y los
 * labels vienen de ``store.catalog``. Añadir un nuevo tipo de
 * dispositivo al ``config.json`` se refleja aquí sin tocar JS.
 *
 * @event refresh  El componente padre debe llamar a la API que
 *                 recarga ``store.memoryState``.
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 */
import { computed, ref, watch } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
// Imports absolutos: ver nota en ``Sidebar.js``.
import { store, pushLog } from "/js/store.js";
import { apiUploadExcel, apiFetchMemory } from "/js/api.js";

export default {
    name: "DefinicionProgramacion",
    emits: ["refresh"],
    setup() {
        const fileInput = ref(null);

        /**
         * Tabs data-driven desde el catalog del backend.
         * Mantiene la forma legacy ``{key, label}`` para no
         * tocar el template más de lo necesario.
         */
        const tabs = computed(() => {
            const c = store.catalog;
            if (!c || !Array.isArray(c.device_tabs)) return [];
            return c.device_tabs.map((t) => ({
                key: t.canonical,
                label: t.label,
            }));
        });

        /**
         * Map ``canonical → [field_name, ...]`` derivado del
         * catalog. El backend (``get_columns_for``) ya filtra
         * los campos ``cfg_*`` (SCL), así que coincide con lo
         * que la UI legacy mostraba.
         */
        const modelColumns = computed(() => {
            const c = store.catalog;
            if (!c || !c.model_columns) return {};
            return c.model_columns;
        });

        /**
         * Etiquetas de columna y columnas monospace desde el
         * catalog. Si el catalog no las trae, fallback a ``{}``
         * y ``new Set()`` respectivamente (modo degradado).
         */
        const colLabels = computed(() => {
            const c = store.catalog;
            return (c && c.col_labels) || {};
        });

        const monoCols = computed(() => {
            const c = store.catalog;
            return new Set((c && c.mono_cols) || []);
        });

        const activeTab = ref(store.activeTab || (tabs.value[0]?.key ?? ""));

        // Si el catalog se carga tarde (después de que el componente
        // ya montó), ``activeTab`` puede estar ``""``. Reaccionar:
        watch(
            () => tabs.value[0]?.key,
            (firstKey) => {
                if (!activeTab.value && firstKey) {
                    activeTab.value = firstKey;
                }
            },
            { immediate: true }
        );

        const columns = computed(
            () => modelColumns.value[activeTab.value] || []
        );

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

        // ── Fase 6: 4 dominios de software (Procesos / PInt / PReal / Alarmas)
        // Leen desde ``store.memoryState`` (volcado por el endpoint
        // ``GET /api/v1/state/dispositivos``). Defensivos: si el
        // operario aún no ha subido Excel o el backend aún no expone
        // los 4 campos nuevos (modo degradado), todos devuelven ``[]``.
        const softwareImplemented = computed(
            () => !!(store.memoryState
                     && store.memoryState.software_parsers_implemented)
        );
        const procesos = computed(
            () => (store.memoryState && store.memoryState.procesos) || []
        );
        const parametrosInt = computed(
            () => (store.memoryState && store.memoryState.parametros_int) || []
        );
        const parametrosReal = computed(
            () => (store.memoryState && store.memoryState.parametros_real) || []
        );
        const alarmas = computed(
            () => (store.memoryState && store.memoryState.alarmas) || []
        );

        /**
         * Sube el .xlsm al backend. Si OK, refresca la memoria
         * automáticamente (para que las cards de N_MAX y la tabla
         * se rellenen sin que el usuario tenga que pulsar "Refrescar").
         *
         * Antes vivía en el Sidebar.js; se mudó aquí porque el flujo
         * natural del usuario es: subir Excel → ver inmediatamente
         * su contenido en la tabla de esta misma vista.
         */
        async function handleExcel(ev) {
            const file = ev.target.files && ev.target.files[0];
            if (!file) return;
            store.busy = true;
            try {
                const r = await apiUploadExcel(file);
                if (r.ok) {
                    store.uploadSummary = r.data.summary || {};
                    pushLog("✅ Excel cargado en AppState", "success");
                    const mem = await apiFetchMemory();
                    if (mem.ok && mem.data && mem.data.ok) {
                        store.memoryState = mem.data;
                    }
                } else {
                    alert("Error cargando Excel: " + (r.data.detail || r.status));
                }
            } finally {
                store.busy = false;
                if (fileInput.value) fileInput.value.value = "";
            }
        }

        function displayValue(value) {
            if (value === null || value === undefined) return "—";
            if (typeof value === "string" && value.trim() === "") return "—";
            return String(value);
        }

        return {
            store,
            fileInput,
            tabs,
            activeTab,
            columns,
            activeDevices,
            dimensiones,
            hasMemory,
            // Fase 6: 4 dominios de software + flag
            softwareImplemented,
            procesos,
            parametrosInt,
            parametrosReal,
            alarmas,
            displayValue,
            handleExcel,
            colLabels,
            monoCols,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- ★ Carga excel (movida del Sidebar al inicio de esta vista) ★ -->
            <section class="mb-4 bg-surface-raised border border-line rounded p-4">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Carga excel</label>
                <input ref="fileInput" type="file" accept=".xlsm"
                    @change="handleExcel" :disabled="store.busy"
                    class="block w-full text-xs text-ink file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:bg-surface-sunken file:text-ink hover:file:bg-surface-sunken" />
                <div v-if="store.uploadSummary" class="mt-2 text-xs text-ink-muted">
                    <div class="text-accent">✅ Excel cargado</div>
                </div>
            </section>

            <header class="flex justify-between items-center mb-4">
                <div>
                    <h2 class="text-lg font-bold text-ink">📊 Definición programación</h2>
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
                    <span class="ml-1 text-[10px] opacity-70">({{ (store.memoryState.dispositivos[t.key] || []).length }})</span>
                </button>
            </div>

            <!-- ★ TABLA ÚNICA REACTIVA: dump de TODAS las columnas del dataclass activo ★ -->
            <div class="flex-1 overflow-auto table-scroll-x mt-2">
                <table v-if="hasMemory" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th v-for="col in columns" :key="col"
                                class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">
                                {{ colLabels[col] || col }}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="d in activeDevices"
                            :key="(d.uid || 'no-uid') + '-' + d.numero"
                            class="border-b border-line">
                            <td v-for="col in columns" :key="col"
                                class="px-3 py-1.5 align-top text-ink whitespace-nowrap"
                                :class="monoCols.has(col) ? 'font-mono' : ''">
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

            <!-- ★ Fase 6: 4 secciones de software (Procesos / PInt / PReal / Alarmas) ★
                 Se renderizan debajo de la tabla de dispositivos, ANTES del
                 "Inspector vacío" (que solo aparece si !hasMemory, así que
                 en la práctica estas secciones SIEMPRE se ven junto a la
                 tabla, nunca con el mensaje de "Inspector vacío").

                 Cada <details> es colapsable: por defecto solo se ve el
                 summary con el conteo de elementos. Al expandir, se ve la
                 tabla compacta con las columnas más relevantes del DTO
                 (uid, codigo, nombre, etc.).

                 Tema: tokens semánticos del "Industrial Claro" (AGENTS.md).
                 PROHIBIDO literales multi-línea dentro de arrays :class
                 (cada clase va en una sola línea). -->
            <section v-if="hasMemory" class="mt-4 space-y-2">
                <!-- Banner ámbar: visible si el flag software_parsers_implemented
                     es false (modo degradado: backend aún no expone los 4
                     campos nuevos o Excel sin hojas de software). -->
                <div v-if="!softwareImplemented"
                     class="bg-amber-100 border-l-4 border-amber-500 text-amber-900 p-3 rounded text-xs">
                    ⚠️ Datos de software pendientes. Sube un Excel con hojas
                    CONFIGURACION / P_REAL / P_INT / ALARMAS para verlos aquí.
                </div>

                <!-- Procesos -->
                <details v-if="procesos.length > 0" class="bg-surface-raised border border-line rounded">
                    <summary class="px-4 py-2 cursor-pointer text-sm font-medium text-ink">
                        Procesos ({{ procesos.length }})
                    </summary>
                    <div class="overflow-auto table-scroll-x p-2">
                        <table class="w-full text-xs">
                            <thead class="bg-surface-sunken text-[10px] uppercase">
                                <tr>
                                    <th class="px-2 py-1 text-left text-ink-muted">UID</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Código</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Nombre</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">PReal</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">PInt</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Alarmas</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">DB PREAL</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">DB ALM</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">ALM HMI</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="p in procesos" :key="p.uid" class="border-b border-line">
                                    <td class="px-2 py-1 font-mono">{{ p.uid }}</td>
                                    <td class="px-2 py-1 font-mono">{{ p.codigo }}</td>
                                    <td class="px-2 py-1">{{ p.nombre }}</td>
                                    <td class="px-2 py-1">{{ p.preal }}</td>
                                    <td class="px-2 py-1">{{ p.pint }}</td>
                                    <td class="px-2 py-1">{{ p.alarmas }}</td>
                                    <td class="px-2 py-1 font-mono">DB{{ 3000 + p.uid }}</td>
                                    <td class="px-2 py-1 font-mono">DB{{ 5000 + p.uid }}</td>
                                    <td class="px-2 py-1">{{ Math.max(0, Math.floor(p.alarmas / 16) - 1) }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </details>

                <!-- Parametros Int -->
                <details v-if="parametrosInt.length > 0" class="bg-surface-raised border border-line rounded">
                    <summary class="px-4 py-2 cursor-pointer text-sm font-medium text-ink">
                        Parámetros Enteros ({{ parametrosInt.length }})
                    </summary>
                    <div class="overflow-auto table-scroll-x p-2">
                        <table class="w-full text-xs">
                            <thead class="bg-surface-sunken text-[10px] uppercase">
                                <tr>
                                    <th class="px-2 py-1 text-left text-ink-muted">UID</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Nº</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Código</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Num.DB</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Num.Lista</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Txt.Lista</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Descripción</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="p in parametrosInt" :key="p.uid" class="border-b border-line">
                                    <td class="px-2 py-1 font-mono">{{ p.uid }}</td>
                                    <td class="px-2 py-1 font-mono">{{ p.numero }}</td>
                                    <td class="px-2 py-1 font-mono">{{ p.codigo }}</td>
                                    <td class="px-2 py-1 font-mono">{{ p.num_db }}</td>
                                    <td class="px-2 py-1 font-mono">{{ p.num_lista }}</td>
                                    <td class="px-2 py-1">{{ p.txt_lista }}</td>
                                    <td class="px-2 py-1">{{ p.descripcion }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </details>

                <!-- Parametros Real -->
                <details v-if="parametrosReal.length > 0" class="bg-surface-raised border border-line rounded">
                    <summary class="px-4 py-2 cursor-pointer text-sm font-medium text-ink">
                        Parámetros Reales ({{ parametrosReal.length }})
                    </summary>
                    <div class="overflow-auto table-scroll-x p-2">
                        <table class="w-full text-xs">
                            <thead class="bg-surface-sunken text-[10px] uppercase">
                                <tr>
                                    <th class="px-2 py-1 text-left text-ink-muted">UID</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Nº</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Código</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Num.DB</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Num.Lista</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Txt.Lista</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Descripción</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="p in parametrosReal" :key="p.uid" class="border-b border-line">
                                    <td class="px-2 py-1 font-mono">{{ p.uid }}</td>
                                    <td class="px-2 py-1 font-mono">{{ p.numero }}</td>
                                    <td class="px-2 py-1 font-mono">{{ p.codigo }}</td>
                                    <td class="px-2 py-1 font-mono">{{ p.num_db }}</td>
                                    <td class="px-2 py-1 font-mono">{{ p.num_lista }}</td>
                                    <td class="px-2 py-1">{{ p.txt_lista }}</td>
                                    <td class="px-2 py-1">{{ p.descripcion }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </details>

                <!-- Alarmas -->
                <details v-if="alarmas.length > 0" class="bg-surface-raised border border-line rounded">
                    <summary class="px-4 py-2 cursor-pointer text-sm font-medium text-ink">
                        Alarmas ({{ alarmas.length }})
                    </summary>
                    <div class="overflow-auto table-scroll-x p-2">
                        <table class="w-full text-xs">
                            <thead class="bg-surface-sunken text-[10px] uppercase">
                                <tr>
                                    <th class="px-2 py-1 text-left text-ink-muted">UID</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Nº</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Proceso</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Num.DB</th>
                                    <th class="px-2 py-1 text-left text-ink-muted">Descripción</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="a in alarmas" :key="a.uid" class="border-b border-line">
                                    <td class="px-2 py-1 font-mono">{{ a.uid }}</td>
                                    <td class="px-2 py-1 font-mono">{{ a.numero }}</td>
                                    <td class="px-2 py-1">{{ a.proceso }}</td>
                                    <td class="px-2 py-1 font-mono">{{ a.num_db }}</td>
                                    <td class="px-2 py-1">{{ a.descripcion }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </details>
            </section>

        </section>
    `,
};
