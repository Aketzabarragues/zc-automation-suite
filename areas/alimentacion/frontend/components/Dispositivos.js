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
import { computed, ref, watch } from "/js/vendor/vue.esm-browser.prod.js";
// Imports absolutos: ver nota en ``Sidebar.js``.
import { store, resetPlcState } from "/js/store.js";
import { apiGeneratePreview, apiCommit } from "/js/api.js";
import { STATUS_META } from "../lib/disp_status.js";

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

        /**
         * Set de hw_types seleccionados para el proximo sync.
         * Inicializado con TODOS los hw_types activos (back-compat: si
         * el operario nunca toca el selector, el sync cubre todo como
         * antes). El operario puede desmarcar para acotar el sync a
         * un subconjunto (e.g. "solo SA" o "ED + EA").
         *
         * Si los tabs llegan tarde (catalog async), el watch de abajo
         * rellena el set con cualquier hw_type nuevo que aparezca.
         * N_MAX siempre se procesa en backend independientemente del
         * filtro (es config transversal); aqui no se representa.
         */
        const selectedHwTypes = ref(
            new Set(tabs.value.map((t) => t.key))
        );

        // Si el catalog se carga tarde (SPA arrancando sin backend)
        // y ``selectedHwTypes`` quedo vacio, re-popular con los
        // hw_types disponibles en cuanto lleguen. Igual que el patron
        // usado para ``activeTab``.
        watch(
            () => tabs.value.map((t) => t.key),
            (keys) => {
                const current = selectedHwTypes.value;
                for (const k of keys) {
                    if (!current.has(k)) current.add(k);
                }
                // Si el operario deselecciono todos y desaparece un
                // hw_type, ``current`` queda con un set vacio. No
                // forzamos reseleccion: el boton "Generar Prevision"
                // ya se deshabilita con canPreview === false.
            },
            { immediate: true }
        );

        /**
         * True si hay al menos 1 hw_type seleccionado (filtro valido).
         * Si no, deshabilitamos preview/commit para no mandar 400.
         */
        const canPreview = computed(() => selectedHwTypes.value.size > 0);

        /**
         * Lista ordenada de hw_types seleccionados (Set -> Array)
         * para pasarla al backend. ``Array.from`` mantiene orden de
         * insercion; backend no asume orden, pero asi es estable.
         */
        const selectedHwTypesList = computed(
            () => Array.from(selectedHwTypes.value)
        );

        /** Alternar un hw_type en el Set. */
        function toggleHwType(key) {
            const s = selectedHwTypes.value;
            if (s.has(key)) {
                s.delete(key);
            } else {
                s.add(key);
            }
        }

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
            if (!canPreview.value) return;
            const hwTypes = selectedHwTypesList.value;
            store.busy = true;
            try {
                const r = await apiGeneratePreview(store.selectedPlc, hwTypes);
                if (r.ok) {
                    store.previewData = r.data;
                    pushLog("Previsión generada OK", "success");
                } else if (r.errorType === "TIAConnectionError") {
                    // TIA Portal no responde: el backend ya invalido
                    // su cache; limpiamos el state del PLC en el SPA
                    // para evitar trabajar con datos stale.
                    pushLog(
                        "TIA Portal no responde. Reconecta y vuelve a seleccionar el PLC.",
                        "error"
                    );
                    resetPlcState();
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
            const hwTypes = selectedHwTypesList.value;
            const total = summary.value.agregados +
                          summary.value.renombrados +
                          summary.value.eliminados +
                          nmaxSummary.value.actualizar;
            const tiposMsg = hwTypes.length < tabs.value.length
                ? `\n\nSolo tipos seleccionados: ${hwTypes.join(", ")}\n(N_MAX siempre se procesa)`
                : "";
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
                    `Esta operacion modifica el PLC.` +
                    tiposMsg
                )
            ) {
                return;
            }
            store.busy = true;
            try {
                const r = await apiCommit(
                    store.selectedPlc,
                    store.previewData,
                    hwTypes
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
                        } else if (rp.errorType === "TIAConnectionError") {
                            // TIA Portal cerro durante el commit. El
                            // backend ya invalido su cache; limpiamos
                            // el state del SPA para evitar operar con
                            // datos stale.
                            pushLog(
                                "TIA Portal no responde. Reconecta y vuelve a seleccionar el PLC.",
                                "error"
                            );
                            resetPlcState();
                        }
                        pushLog(
                            "Transacción aplicada OK. Preview refrescado (fallback).",
                            "success"
                        );
                    }
                } else if (r.errorType === "TIAConnectionError") {
                    // TIA Portal no responde. Limpiamos el state del
                    // PLC en el SPA (backend ya invalido su cache).
                    pushLog(
                        "TIA Portal no responde. Reconecta y vuelve a seleccionar el PLC.",
                        "error"
                    );
                    resetPlcState();
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
            selectedHwTypes,
            selectedHwTypesList,
            canPreview,
            toggleHwType,
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
            <div class="mb-4 bg-surface-raised border border-line rounded p-4"
                 data-testid="dispositivos-card-info">
                <div class="flex justify-between items-center">
                    <p v-if="hasPreview" class="text-xs text-ink-muted">
                        {{ summary.total }} dispositivos analizados —
                        <span class="text-accent">{{ summary.agregados }} a agregar</span> ·
                        <span class="text-amber-700">{{ summary.renombrados }} a renombrar</span> ·
                        <span class="text-red-700">{{ summary.eliminados }} a eliminar</span> ·
                        <span class="text-ink-muted">{{ summary.sin_cambios }} sin cambios</span>
                    </p>
                    <span v-else></span>
                    <button @click="generarPreview"
                        :disabled="!store.selectedPlc || store.busy || !canPreview"
                        data-testid="dispositivos-generar-prevision"
                        class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                        🔍 Generar Previsión
                    </button>
                </div>

                <!-- Selector de tipos a sincronizar (selector "todos o
                     los que nos interese", pedido operario sept-2026).
                     Solo aparece si hay >=2 hw_types (con 1 seria
                     redundante). Inicial: todos seleccionados
                     (back-compat). El operador puede desmarcar para
                     acotar el preview/commit a un subconjunto.
                     N_MAX siempre se procesa en backend
                     independientemente del filtro (es transversal). -->
                <div v-if="tabs.length >= 2"
                     class="mt-3 pt-3 border-t border-line"
                     data-testid="dispositivos-hw-types-filter">
                    <div class="flex items-center gap-3 flex-wrap">
                        <span class="text-xs font-semibold text-ink-muted uppercase whitespace-nowrap">
                            Sincronizar:
                        </span>
                        <label v-for="t in tabs" :key="t.key"
                               class="flex items-center gap-1.5 text-xs cursor-pointer select-none">
                            <input type="checkbox"
                                   :checked="selectedHwTypes.has(t.key)"
                                   @change="toggleHwType(t.key)"
                                   :data-testid="'hw-type-' + t.key"
                                   class="accent-accent cursor-pointer">
                            <span :class="selectedHwTypes.has(t.key) ? 'text-ink font-semibold' : 'text-ink-muted'">
                                {{ t.label }}
                            </span>
                        </label>
                        <span v-if="selectedHwTypes.size === 0"
                              class="text-xs text-amber-700 italic">
                            (ninguno seleccionado)
                        </span>
                        <span v-else-if="selectedHwTypes.size < tabs.length"
                              class="text-xs text-ink-muted">
                            ({{ selectedHwTypes.size }}/{{ tabs.length }})
                        </span>
                    </div>
                </div>
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
                            class="border-b border-line"
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

                <!-- Botón "Aplicar Cambios en TIA Portal" — acción
                     destructiva/commit. Mismo lenguaje pill que el
                     resto de botones (text-accent, bg-surface-sunken,
                     border border-line) pero un escalón más prominente
                     (w-full py-3 text-sm, contenido centrado) porque
                     es la acción terminal del flujo. Vive dentro de la
                     card 2, debajo del área de scroll, para que el
                     operario tenga todo el contexto del diff y el
                     confirm en el mismo bloque visual. -->
                <button id="btn-commit" @click="ejecutarCommit"
                    :disabled="!hasPreview || (summary.agregados + summary.renombrados + summary.eliminados + nmaxSummary.actualizar === 0) || store.busy"
                    data-testid="dispositivos-aplicar"
                    class="mt-3 w-full py-3 text-accent font-semibold text-sm bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    ✅ Aplicar Cambios en TIA Portal
                    <span v-if="hasPreview" class="text-xs font-normal text-ink-muted">
                        ({{ summary.agregados + summary.renombrados + summary.eliminados +
                           nmaxSummary.actualizar }} cambios)
                    </span>
                </button>
            </div><!-- /card 2 (N_MAX + tabs + tabla + botón) -->
        </section>
    `,
};
