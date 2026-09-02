/**
 * Componente ProcesosSyncView.
 *
 * Vista inline que muestra el diff de comentarios de los 3 arrays de
 * un proceso (PReal, PInt, ALM) y permite aplicarlo al PLC en
 * una sola transacción TIA. Análogo a ``BloquesCacheView`` pero
 * con interacción de preview/diff/apply.
 *
 * Estructura:
 *   1. Cabecera: nombre del proceso, código, UID, y los 3 nombres
 *      TIA resueltos (DB_PARAM, DB_ALM, tabla de variables).
 *   2. Banner ámbar si ``store.procesosSync.error`` está poblado.
 *   3. Banner ámbar si el preview tiene ``precondiciones_ok=false``
 *      (lista los bloques ausentes en el PLC).
 *   4. 3 tabs (PReal, PInt, Alarmas) con badge del nº de cambios
 *      (to_update + to_insert).
 *   5. Tabla con columnas: Slot | Valor actual | Valor deseado
 *      (Excel) | Acción. Colores por acción.
 *   6. Botón "↻ Generar preview" (top-right).
 *   7. Botón "✓ Aplicar" (bottom). Deshabilitado si no hay preview
 *      o si el summary es 0 ops.
 *   8. Botón "← Volver" que emite el evento ``close`` (el padre
 *      ``Procesos.js`` lo usa para colapsar la vista inline).
 *
 * Modo de uso (inline, NO standalone):
 *   El componente se monta como hijo de ``Procesos.js`` debajo de
 *   las cards de acción. Recibe el ``procUid`` del proceso
 *   seleccionado como prop (en lugar de leerlo del store). Si el
 *   operario cambia el proceso en el selector, el sync view se
 *   re-renderiza reactivamente con el nuevo ``procUid`` y se limpia
 *   el preview antiguo (para evitar mostrar diff del proceso
 *   equivocado). El botón "← Volver" emite ``close`` y el padre
 *   colapsa la vista; el operario puede entonces cambiar de
 *   proceso o navegar a otra sub-vista.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``bg-accent``,
 * ``text-green-600``, ``text-amber-600``, ``text-red-600``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * ``vue.esm-browser.prod.js`` NO acepta string literals multi-línea
 * dentro de arrays de ``:class``. Cada literal va en una sola línea.
 */
import {
    computed,
    ref,
    watch,
} from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store, pushLog } from "/js/store.js";
import {
    apiProcesosSyncPreview,
    apiProcesosSyncCommit,
} from "/js/api.js";

export default {
    name: "ProcesosSyncView",
    props: {
        /**
         * UID del proceso del que se muestran/operan los comentarios.
         * ProcsyncView es un componente controlado: NO busca el
         * proceso por su cuenta; el padre (``Procesos.js``) se lo
         * pasa y se re-renderiza reactivamente cuando cambia.
         * Si el operario cambia el proceso en el selector, este
         * prop cambia y el sync view se actualiza.
         */
        procUid: {
            type: Number,
            default: null,
        },
    },
    emits: ["close"],
    setup(props, { emit }) {
        /**
         * Tab activa. Una de ``"PReal" | "PInt" | "ALM"``.
         */
        const activeTab = ref("PReal");

        /**
         * True mientras hay un preview o commit en vuelo.
         * Refleja ``store.procesosSync.applying`` para reactividad
         * local, pero el botón Aplicar también mira el store.
         */
        const isWorking = ref(false);

        /**
         * Local view of the preview; sincronizado con
         * ``store.procesosSync.preview`` cuando el proc_uid coincide.
         */
        const preview = computed(() => {
            const p = store.procesosSync && store.procesosSync.preview;
            if (!p) return null;
            if (props.procUid == null) return null;
            if (p.proc_uid !== props.procUid) return null;
            return p;
        });

        /**
         * Proceso del Excel cacheado que coincide con el uid del
         * prop. Recalculado reactivamente cuando cambia el
         * selector de proceso del padre.
         */
        const selectedProc = computed(() => {
            const ms = store.memoryState;
            if (!ms || !Array.isArray(ms.procesos)) return null;
            if (props.procUid == null) return null;
            return ms.procesos.find(
                (p) => p && p.uid === props.procUid
            ) || null;
        });

        /**
         * Banner: error global del flujo.
         */
        const flowError = computed(() => {
            return (store.procesosSync && store.procesosSync.error) || null;
        });

        /**
         * Banner: precondiciones del preview (missing_blocks).
         */
        const precondError = computed(() => {
            const p = preview.value;
            if (!p) return null;
            if (p.precondiciones_ok) return null;
            return p.missing_blocks && p.missing_blocks.length > 0
                ? p.missing_blocks.join(" · ")
                : "Precondiciones no cumplidas";
        });

        /**
         * Filas de la pestaña activa (formato uniforme para la
         * tabla). Para cada slot del array, devuelve:
         *   { slot, current, desired, action }
         * ``current`` viene del preview (puede ser ``null`` porque
         * el preview no consulta TIA; el backend lo deja así por
         * ahora). ``desired`` es el comentario del Excel. ``action``
         * es ``"equal" | "update" | "new"``.
         */
        const activeRows = computed(() => {
            const p = preview.value;
            if (!p || !p.arrays) return [];
            const arr = p.arrays[activeTab.value];
            if (!arr || !arr.slot_map) return [];
            const rows = [];
            Object.keys(arr.slot_map)
                .map((k) => parseInt(k, 10))
                .sort((a, b) => a - b)
                .forEach((slot) => {
                    const e = arr.slot_map[slot];
                    rows.push({
                        slot,
                        current: e.current,
                        desired: e.desired,
                        action: e.action,
                    });
                });
            return rows;
        });

        /**
         * Badge count para cada tab: ``to_update + to_insert``.
         */
        function tabBadge(tabName) {
            const p = preview.value;
            if (!p || !p.arrays || !p.arrays[tabName]) return 0;
            const s = p.arrays[tabName].summary;
            if (!s) return 0;
            return (s.to_update || 0) + (s.to_insert || 0) + (s.to_prune || 0);
        }

        /**
         * Total ops (suma de los 3 arrays).
         */
        const totalOps = computed(() => {
            const p = preview.value;
            if (!p || !p.summary) return 0;
            return p.summary.total_ops || 0;
        });

        /**
         * Nombre del PLC activo (viene del store). Si está vacío,
         * el botón Aplicar se deshabilita con tooltip.
         */
        const plcName = computed(() => store.selectedPlc || "");

        /**
         * Si podemos aplicar: hay preview, hay PLC, hay ops > 0,
         * y no estamos trabajando.
         */
        const canApply = computed(() => {
            return (
                !!preview.value &&
                preview.value.precondiciones_ok === true &&
                totalOps.value > 0 &&
                !!plcName.value &&
                !isWorking.value
            );
        });

        /**
         * Click en "↻ Generar preview".
         */
        async function handleGeneratePreview() {
            if (isWorking.value) return;
            if (props.procUid == null) return;
            isWorking.value = true;
            store.procesosSync.applying = true;
            store.procesosSync.error = null;
            try {
                const r = await apiProcesosSyncPreview(
                    props.procUid,
                    plcName.value
                );
                if (r && r.ok) {
                    store.procesosSync.preview = r.data;
                    if (r.data && r.data.precondiciones_ok) {
                        pushLog(
                            `Preview comentarios proceso ${props.procUid}: ${r.data.summary && r.data.summary.total_ops} ops`,
                            "success"
                        );
                    } else {
                        pushLog(
                            `Preview comentarios proceso ${props.procUid}: precondiciones NO cumplidas`,
                            "warning"
                        );
                    }
                } else {
                    const detail = (r && r.data && r.data.detail) ||
                                    "Error generando preview";
                    store.procesosSync.error = detail;
                    pushLog(detail, "error");
                }
            } catch (e) {
                store.procesosSync.error = String(e && e.message ? e.message : e);
                pushLog(store.procesosSync.error, "error");
            } finally {
                isWorking.value = false;
                store.procesosSync.applying = false;
            }
        }

        /**
         * Click en "✓ Aplicar".
         */
        async function handleApply() {
            if (!canApply.value) return;
            if (!plcName.value) {
                store.procesosSync.error =
                    "Selecciona un PLC en el sidebar antes de aplicar.";
                return;
            }
            isWorking.value = true;
            store.procesosSync.applying = true;
            store.procesosSync.error = null;
            try {
                const r = await apiProcesosSyncCommit(
                    props.procUid,
                    plcName.value,
                    preview.value
                );
                if (r && r.ok) {
                    store.procesosSync.lastAppliedAt =
                        new Date().toISOString();
                    pushLog(
                        `Comentarios aplicados al PLC ${plcName.value}: ${r.data && r.data.operations_executed} ops`,
                        "success"
                    );
                    // Tras aplicar, el preview queda obsoleto. Lo
                    // limpiamos para forzar al operario a
                    // regenerarlo si quiere ver el nuevo estado.
                    store.procesosSync.preview = null;
                } else {
                    const detail = (r && r.data && r.data.detail) ||
                                    "Error aplicando comentarios";
                    store.procesosSync.error = detail;
                    pushLog(detail, "error");
                }
            } catch (e) {
                store.procesosSync.error = String(e && e.message ? e.message : e);
                pushLog(store.procesosSync.error, "error");
            } finally {
                isWorking.value = false;
                store.procesosSync.applying = false;
            }
        }

        /**
         * Botón "← Volver" — emite el evento ``close`` para que el
         * padre (``Procesos.js``) colapse la vista inline. NO
         * cambiamos ``store.currentView`` porque la SPA sigue en
         * "proc"; el sync view es solo un panel hijo.
         */
        function handleBack() {
            emit("close");
        }

        /**
         * Watcher: cuando el operario cambia el proceso en el
         * selector del padre, ``procUid`` cambia y debemos limpiar
         * el preview y el error del proceso anterior para no
         * mostrar datos del proceso equivocado.
         *
         * Solo dispara cuando el uid pasa de uno a OTRO (no en el
         * mount inicial, donde ``procUid`` puede ser null → null
         * o null → primer uid; en ambos casos la limpieza es
         * benigna).
         */
        watch(
            () => props.procUid,
            (newUid, oldUid) => {
                if (newUid !== oldUid) {
                    // Cambio de proceso: reset del estado del sync
                    // para que el operario tenga que regenerar el
                    // preview (si quiere) contra el nuevo proceso.
                    store.procesosSync.preview = null;
                    store.procesosSync.error = null;
                    // Reset de la pestaña activa a la primera, por
                    // consistencia visual.
                    activeTab.value = "PReal";
                }
            }
        );

        /**
         * ``procUid`` reactivo expuesto al template. Es un
         * ``computed`` que envuelve ``props.procUid`` para que el
         * template pueda usar ``procUid == null`` directamente
         * (Vue 3 auto-desempaqueta refs en el template).
         */
        const procUid = computed(() => props.procUid);

        return {
            store,
            selectedProc,
            procUid,
            activeTab,
            preview,
            activeRows,
            tabBadge,
            totalOps,
            plcName,
            canApply,
            flowError,
            precondError,
            isWorking,
            handleGeneratePreview,
            handleApply,
            handleBack,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <header class="flex justify-between items-start mb-4">
                <div>
                    <h2 class="text-lg font-bold text-ink">💬 Sync comentarios de DB</h2>
                    <p v-if="selectedProc"
                       class="text-xs text-ink-muted mt-0.5">
                        Proceso
                        <span class="font-semibold text-ink">{{ selectedProc.nombre }}</span>
                        (<span class="font-mono">{{ selectedProc.codigo }}</span>,
                         uid <span class="font-mono">{{ selectedProc.uid }}</span>)
                    </p>
                    <p v-else class="text-xs text-amber-700 mt-0.5">
                        Selecciona un proceso en la vista "Procesos" primero.
                    </p>
                </div>
                <div class="flex gap-2">
                    <button @click="handleBack"
                        data-testid="proc-sync-back"
                        class="px-3 py-2 bg-surface border border-line rounded text-xs font-medium text-ink-muted hover:bg-surface-sunken">
                        ← Volver
                    </button>
                    <button @click="handleGeneratePreview"
                        :disabled="procUid == null || isWorking"
                        data-testid="proc-sync-generate-preview"
                        class="px-4 py-2 bg-accent hover:bg-accent-hover disabled:opacity-50 rounded text-sm font-medium text-ink-inverse">
                        <span v-if="isWorking">⏳ Generando…</span>
                        <span v-else>↻ Generar preview</span>
                    </button>
                </div>
            </header>

            <!-- Banner de error global -->
            <div v-if="flowError"
                 class="mb-3 px-3 py-2 bg-red-100 border border-red-300 rounded text-xs text-red-800">
                ⚠️ {{ flowError }}
            </div>

            <!-- Banner de precondiciones -->
            <div v-if="precondError"
                 class="mb-3 px-3 py-2 bg-amber-100 border border-amber-300 rounded text-xs text-amber-800">
                ⚠️ Precondiciones no cumplidas: {{ precondError }}
            </div>

            <!-- Nombres TIA resueltos -->
            <div v-if="preview && preview.db_param_name"
                 class="mb-3 bg-surface-raised border border-line rounded p-3 text-xs">
                <div class="text-ink-muted mb-1 font-semibold">Bloques TIA objetivo</div>
                <div class="font-mono text-ink">
                    DB parámetros: <span class="font-semibold">{{ preview.db_param_name }}</span>
                </div>
                <div class="font-mono text-ink">
                    DB alarmas: <span class="font-semibold">{{ preview.db_alm_name }}</span>
                </div>
                <div class="font-mono text-ink">
                    Tabla de variables: <span class="font-semibold">{{ preview.table_name }}</span>
                </div>
            </div>

            <!-- Tabs -->
            <div v-if="preview && preview.precondiciones_ok"
                 class="flex border-b border-line bg-surface-sunken overflow-x-auto">
                <button @click="activeTab = 'PReal'"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeTab === 'PReal' ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    PReal
                    <span v-if="tabBadge('PReal') > 0"
                          class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full bg-accent text-ink-inverse">
                        {{ tabBadge('PReal') }}
                    </span>
                </button>
                <button @click="activeTab = 'PInt'"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeTab === 'PInt' ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    PInt
                    <span v-if="tabBadge('PInt') > 0"
                          class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full bg-accent text-ink-inverse">
                        {{ tabBadge('PInt') }}
                    </span>
                </button>
                <button @click="activeTab = 'ALM'"
                    :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                             activeTab === 'ALM' ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                    Alarmas
                    <span v-if="tabBadge('ALM') > 0"
                          class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full bg-accent text-ink-inverse">
                        {{ tabBadge('ALM') }}
                    </span>
                </button>
            </div>

            <!-- Tabla de diff -->
            <div v-if="preview && preview.precondiciones_ok"
                 class="flex-1 overflow-auto table-scroll-x mt-2">
                <table class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted w-16">Slot</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Valor actual (es-ES)</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Valor deseado (Excel)</th>
                            <th class="px-3 py-2 text-left text-ink-muted w-28">Acción</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in activeRows"
                            :key="activeTab + '-' + row.slot"
                            :data-testid="'proc-sync-row-' + activeTab + '-' + row.slot"
                            class="border-b border-line bg-surface-raised">
                            <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">
                                {{ row.slot }}
                            </td>
                            <td class="px-3 py-1.5 text-ink-muted">
                                <span v-if="row.current === null" class="italic">—</span>
                                <span v-else>{{ row.current }}</span>
                            </td>
                            <td class="px-3 py-1.5 font-mono text-ink">
                                {{ row.desired }}
                            </td>
                            <td class="px-3 py-1.5 whitespace-nowrap">
                                <span v-if="row.action === 'update'"
                                      class="text-amber-600 font-semibold">
                                    actualizar
                                </span>
                                <span v-else-if="row.action === 'new'"
                                      class="text-green-600 font-semibold">
                                    nuevo
                                </span>
                                <span v-else class="text-ink-muted italic">
                                    igual
                                </span>
                            </td>
                        </tr>
                        <tr v-if="activeRows.length === 0">
                            <td colspan="4"
                                class="px-3 py-6 text-center text-ink-muted italic">
                                No hay slots en este array.
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- Empty state: sin preview todavía -->
            <div v-else-if="!preview"
                 class="flex-1 flex items-center justify-center bg-surface-raised border border-line rounded">
                <div class="text-center text-ink-muted text-sm">
                    <p class="mb-2">⚠️ Aún no se ha generado el preview.</p>
                    <p class="text-xs">Pulsa "↻ Generar preview" para calcular el diff.</p>
                </div>
            </div>

            <!-- Botón Aplicar (footer) -->
            <div v-if="preview && preview.precondiciones_ok"
                 class="mt-3 flex justify-end items-center gap-3">
                <span v-if="store.procesosSync.lastAppliedAt"
                      class="text-xs text-green-600">
                    ✓ Aplicado: {{ store.procesosSync.lastAppliedAt }}
                </span>
                <button @click="handleApply"
                    :disabled="!canApply"
                    :title="!plcName ? 'Selecciona un PLC en el sidebar primero' : (totalOps === 0 ? 'No hay cambios que aplicar' : '')"
                    data-testid="proc-sync-apply"
                    class="px-6 py-2 bg-accent hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed rounded text-sm font-medium text-ink-inverse">
                    <span v-if="isWorking">⏳ Aplicando…</span>
                    <span v-else>✓ Aplicar al PLC</span>
                </button>
            </div>
        </section>
    `,
};
