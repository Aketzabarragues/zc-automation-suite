/**
 * Componente DefinicionProgramacion.
 *
 * Vista "shell" de la pestaña **Definición programación**. Ya NO
 * contiene la tabla de dispositivos ni las 4 tablas de software
 * (Fase 6) en línea: se compone de sub-componentes para resolver el
 * rediseño de tabs principales acordado con el operario.
 *
 * Estructura del template (de arriba abajo):
 *   1. Carga excel + botón "Actualizar" (unificados en el mismo
 *      card tras el rediseño "Modern Corporate"). El título de
 *      la vista ya vive en el topbar, así que el botón se mueve
 *      aquí para que el operario tenga todo el flujo de subida
 *      de Excel + refresh en un único bloque visible.
 *   2. ``<main-tabs>`` (Dispositivos | Procesos) con badges de
 *      conteo. Componente reutilizable, vive en MainTabs.js.
 *   3. Panel activo: ``<dispositivos-panel>`` o ``<procesos-panel>``
 *      según ``store.activeMainTab``.
 *
 * Las N_MAX cards (dimensiones) vivían aquí como info transversal,
 * pero el operario las pidió DENTRO del tab Dispositivos (porque
 * describen tamaños de arrays de dispositivos: N_MAX_DISP_ED, etc.).
 * Ahora viven en ``DispositivosPanel.js``.
 *
 * La lógica de sub-tabs y tablas vive en:
 *   - ``DispositivosPanel.js`` (sub-tabs ED|EA|SA|V|M|MVF + N_MAX cards
 *     + tabla reactiva del dataclass activo).
 *   - ``ProcesosPanel.js`` (sub-tabs Procesos|PInt|PReal|Alarmas
 *     + 4 tablas; reemplaza los ``<details>`` plegables).
 *
 * @event refresh  El componente padre debe llamar a la API que
 *                 recarga ``store.memoryState``. Lo consume ``main.js``
 *                 para llamar a ``apiFetchMemory``.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent``,
 * ``bg-amber-*``, ``text-amber-*``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 */
import { computed, ref } from "/js/vendor/vue.esm-browser.prod.js";
// Imports absolutos: ver nota en ``Sidebar.js``.
import { store, pushLog } from "/js/store.js";
import { apiUploadExcel, apiFetchMemory } from "/js/api.js";

export default {
    name: "DefinicionProgramacion",
    emits: ["refresh"],
    setup() {
        const fileInput = ref(null);

        /**
         * Conteos para los badges de los 2 tabs principales.
         * Se recalculan reactivamente al cambiar ``memoryState``
         * (subida de Excel, refresco, etc.).
         */
        const dispositivosCount = computed(() => {
            const d = store.memoryState && store.memoryState.dispositivos;
            if (!d || typeof d !== "object") return 0;
            return Object.values(d).reduce(
                (sum, lst) => sum + (Array.isArray(lst) ? lst.length : 0),
                0
            );
        });

        const procesosCount = computed(() => {
            const ms = store.memoryState;
            if (!ms) return 0;
            const n = (Array.isArray(ms.procesos) ? ms.procesos.length : 0)
                + (Array.isArray(ms.parametros_int) ? ms.parametros_int.length : 0)
                + (Array.isArray(ms.parametros_real) ? ms.parametros_real.length : 0)
                + (Array.isArray(ms.alarmas) ? ms.alarmas.length : 0);
            return n;
        });

        /**
         * Datos que se pasan al ``<main-tabs>``. Se computan
         * aquí (no en MainTabs) para que los conteos reflejen
         * ``store.memoryState`` sin acoplar MainTabs al shape
         * de la AppState.
         */
        const mainTabsData = computed(() => [
            {
                key: "dispositivos",
                label: "Dispositivos",
                icon: "📟",
                badge: dispositivosCount.value,
            },
            {
                key: "procesos",
                label: "Procesos",
                icon: "⚙️",
                badge: procesosCount.value,
            },
        ]);

        /**
         * Sube el .xlsm al backend. Si OK, refresca la memoria
         * automáticamente (para que las cards de N_MAX y la tabla
         * se rellenen sin que el usuario tenga que pulsar
         * "Actualizar").
         *
         * Antes vivía en el Sidebar.js; se mudó aquí porque el
         * flujo natural del usuario es: subir Excel → ver
         * inmediatamente su contenido en la tabla de esta misma
         * vista.
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

        return {
            store,
            fileInput,
            mainTabsData,
            handleExcel,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- ★ Carga excel + botón "Actualizar" (unificados en
                 el mismo card tras el rediseño "Modern Corporate": el
                 título de la vista ya vive en el topbar, así que
                 movemos el botón al card para que el operario
                 tenga todo el flujo de subida de Excel + refresh
                 en un único bloque visible). ★ -->
            <section class="mb-4 bg-surface-raised border border-line rounded p-4">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Carga excel</label>
                <div class="flex items-center gap-3">
                    <input ref="fileInput" type="file" accept=".xlsm"
                        @change="handleExcel" :disabled="store.busy"
                        class="flex-1 text-xs text-ink file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:bg-surface-sunken file:text-ink hover:file:bg-surface-sunken" />
                    <button @click="$emit('refresh')" :disabled="store.busy"
                        data-testid="def-programacion-actualizar"
                        class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                        🔄 Actualizar
                    </button>
                </div>
                <div v-if="store.uploadSummary" class="mt-2 text-xs text-ink-muted">
                    <div class="text-accent">✅ Excel cargado</div>
                </div>
            </section>

            <!-- ★ Tabs principales (NUEVO) ★ -->
            <main-tabs :tabs="mainTabsData" />

            <!-- ★ Panel activo según store.activeMainTab ★ -->
            <div class="flex-1 mt-2 flex flex-col overflow-hidden">
                <dispositivos-panel v-if="store.activeMainTab === 'dispositivos'" />
                <procesos-panel v-else />
            </div>

        </section>
    `,
};
