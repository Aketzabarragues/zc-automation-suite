/**
 * Componente DispositivosPanel.
 *
 * Panel que se muestra cuando ``store.activeMainTab === 'dispositivos'``.
 * Contiene:
 *   1. Sub-tabs data-driven (ED|EA|SA|V|M|MVF) generadas desde
 *      ``store.catalog.device_tabs``.
 *   2. La tabla reactiva con todas las columnas del dataclass
 *      activo (``modelColumns[activeSubTab]``), dentro de un
 *      contenedor ``bg-surface-raised border border-line rounded``
 *      para coherencia visual con ``ProcesosPanel.js``.
 *
 * Multi-PLC: las N_MAX cards (antes aquí) se han movido a
 * ``ConfiguracionPanel`` (tab "Configuracion"). Multi-PLC rompe la
 * utilidad de cards mezcladas por PLC: la info por PLC vive en el
 * tab "Configuracion" (Tabla_Dispositivos cruda del Excel) y en el
 * preview del PLC concreto (``Dispositivos.js``).
 *
 * **Convención de keys:**
 *   - ``tab.key``     = ``t.canonical`` (``"DispED"``): indexa
 *     ``store.catalog.model_columns`` (el backend lo construye
 *     con canonical como clave, no con ``hw_type``).
 *   - ``tab.hwType``  = ``t.hw_type`` (``"ed"``): indexa
 *     ``store.appCache.areas.alimentacion.excel_full.dispositivos``
 *     (el backend ``excel_loader.py`` produce el dict con keys
 *     ``hw_type`` lowercase).
 * Mezclar ambas keys da ``undefined`` y la pestaña muestra el
 * empty-state "no contiene dispositivos" aunque el cache esté lleno.
 *
 * Si ``store.appCache.areas["alimentacion"].excel_full`` está
 * vacío (operario aún no ha subido Excel), pinta el mensaje
 * "Inspector de Memoria está vacío" en lugar de la tabla.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 */
import { computed, ref, watch } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

export default {
    name: "DispositivosPanel",
    setup() {
        /**
         * Sub-tabs data-driven desde el catalog del backend.
         * Mantiene la forma ``{key, hwType, label}``: ``key`` es el
         * canonical (para ``modelColumns``), ``hwType`` es el
         * ``hw_type`` lowercase (para ``excel_full.dispositivos``).
         */
        const tabs = computed(() => {
            const c = store.catalog;
            if (!c || !Array.isArray(c.device_tabs)) return [];
            return c.device_tabs.map((t) => ({
                key: t.canonical,
                hwType: t.hw_type,
                label: t.label,
            }));
        });

        /**
         * ``canonical → [field_name, ...]`` derivado del catalog.
         * El backend (``get_columns_for``) ya filtra los campos
         * ``cfg_*`` (SCL), así que coincide con lo que la UI
         * legacy mostraba.
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

        const activeSubTab = ref(store.activeTab || (tabs.value[0] && tabs.value[0].key) || "");

        // Si el catalog se carga tarde (después de que el
        // componente ya montó), ``activeSubTab`` puede estar ``""``.
        // Reaccionar y fijar al primer tab disponible.
        watch(
            () => tabs.value[0] && tabs.value[0].key,
            (firstKey) => {
                if (!activeSubTab.value && firstKey) {
                    activeSubTab.value = firstKey;
                }
            },
            { immediate: true }
        );

        const columns = computed(
            () => modelColumns.value[activeSubTab.value] || []
        );

        // ``excel_full`` reactivo desde el AppCache del area activa.
        const excelFull = computed(
            () => store.appCache?.areas?.alimentacion?.excel_full || null
        );

        // ``hwTypeByKey`` traduce ``activeSubTab`` (canonical, p.ej.
        // ``"DispED"``) al ``hw_type`` (``"ed"``) con el que el
        // backend keyed ``excel_full.dispositivos``. Sin este mapeo
        // el lookup devuelve ``undefined`` y la SPA pinta el
        // empty-state "no contiene dispositivos" aunque el cache
        // tenga disp cargados.
        const hwTypeByKey = computed(() => {
            const m = {};
            for (const t of tabs.value) m[t.key] = t.hwType;
            return m;
        });

        const activeDevices = computed(() => {
            const ms = excelFull.value;
            if (!ms || !ms.dispositivos) return [];
            const hw = hwTypeByKey.value[activeSubTab.value];
            if (!hw) return [];
            return ms.dispositivos[hw] || [];
        });

        const hasMemory = computed(
            () => {
                // ``hasMemory`` distingue 2 estados visuales:
                //   1. ``excelFull.value === null``: operario no ha
                //      hecho nunca un fetch (estado "virgen"). Se
                //      muestra el "Inspector vacío" centrado.
                //   2. ``excelFull.value`` es un objeto (incluso con
                //      dicts vacios, p.ej. tras "Refrescar" sin
                //      Excel): se muestran las tablas. Cada tabla
                //      pinta su propio mensaje "La pestaña X no
                //      contiene dispositivos" si su lista esta
                //      vacia (eso lo hace el ``<tr v-if="...">``).
                // El operario quiere que tras "Refrescar" se vean
                // las tablas (no el "Inspector vacío"), asi que
                // hasMemory es true en cuanto hay excel_full
                // (incluso si no trae datos).
                return excelFull.value != null;
            }
        );

        // N_MAX cards ELIMINADAS (multi-PLC). La shape multi-PLC
        // (dict anidado por PLC) no se puede iterar como cards sin
        // ambiguedad. Las N_MAX por PLC viven ahora en el tab
        // ``ConfiguracionPanel`` (``Tabla_Dispositivos`` cruda del Excel)
        // y en el preview del PLC concreto (``Dispositivos.js``).

        /**
         * Conteo de dispositivos por sub-tab (DispED, DispEA, ...).
         * Encapsula el acceso a ``excelFull.dispositivos`` para
         * que el template no toque ``store`` directamente (lo cual es
         * inalcanzable desde el template en Vue 3 con template compiler
         * en runtime: las variables importadas a nivel de módulo NO se
         * exponen automáticamente al template; solo lo retornado del
         * setup()). Las keys del dict resultante son ``tab.key``
         * (canonical, ``DispED``) porque el template itera sobre
         * ``tabs`` y hace ``deviceCountsByTab[t.key]``; los valores
         * se leen del backend con ``hwType`` (``t.hwType``).
         */
        const deviceCountsByTab = computed(() => {
            const out = {};
            const ms = excelFull.value;
            const disp = ms && ms.dispositivos;
            if (!disp || typeof disp !== "object") return out;
            for (const t of tabs.value) {
                const v = disp[t.hwType];
                out[t.key] = Array.isArray(v) ? v.length : 0;
            }
            return out;
        });

        /**
         * Helper: formatea un valor de celda para mostrar ``—``
         * en vez de ``null/undefined/vacío`` (UX limpia).
         */
        function displayValue(value) {
            if (value === null || value === undefined) return "—";
            if (typeof value === "string" && value.trim() === "") return "—";
            return String(value);
        }

        return {
            tabs,
            activeSubTab,
            columns,
            activeDevices,
            hasMemory,
            displayValue,
            colLabels,
            monoCols,
            deviceCountsByTab,
        };
    },
    template: /* html */ `
        <div class="flex-1 flex flex-col overflow-hidden">

            <!-- N_MAX cards ELIMINADAS (multi-PLC). La
                 Tabla_Dispositivos del Excel ahora vive en el
                 tab ConfiguracionPanel (shape multi-PLC, una
                 fila por PLC). -->

            <!-- Sub-tabs por tipo de dispositivo (ED|EA|SA|V|M|MVF) -->
            <div v-if="hasMemory" class="flex border-b border-line bg-surface-sunken overflow-x-auto">
                <button v-for="t in tabs" :key="t.key"
                    @click="activeSubTab = t.key"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeSubTab === t.key ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    {{ t.label }}
                    <span class="ml-1 text-[10px] opacity-70">({{ deviceCountsByTab[t.key] || 0 }})</span>
                </button>
            </div>

            <!-- Tabla reactiva: dump de TODAS las columnas del dataclass activo.
                 Contenedor estandarizado con ProcesosPanel: bg-surface-raised
                 + border + rounded para coherencia visual entre ambos tabs. -->
            <div class="flex-1 overflow-auto table-scroll-x mt-2 bg-surface-raised border border-line rounded">
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
                                ⚠️ La pestaña "{{ activeSubTab }}" no contiene dispositivos. Si el Excel fue cargado, verifique que la tabla exista y no esté vacía.
                            </td>
                        </tr>
                    </tbody>
                </table>
                <div v-else class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                    <div>
                        <div class="text-5xl mb-3 opacity-40">📊</div>
                        <p class="mb-2">La cache del excel está vacía.</p>
                        <p class="text-xs">Sube un Excel y pulsa <strong class="text-accent">"Actualizar"</strong>.</p>
                    </div>
                </div>
            </div>

        </div>
    `,
};
