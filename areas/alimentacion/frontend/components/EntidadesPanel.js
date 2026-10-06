/**
 * Componente EntidadesPanel.
 *
 * Panel que se muestra cuando ``store.activeMainTab === 'entidades'``.
 * Contiene dos bloques:
 *
 *   1. Cabecera con 2 botones de accion ("🔍 Generar Prevision" +
 *      "✓ Aplicar en TIA") que llaman a los stubs del feature
 *      ENTIDADES (``/api/v1/entidades/preview`` +
 *      ``/api/v1/entidades/sincronizar``). En commit B.0 son stubs
 *      que devuelven ``status: "preview_stub" / "sincronizar_stub"``.
 *      Los commits B (FB Preview real) y C (FB Sync real)
 *      sustituyen el backend sin tocar este componente.
 *   2. Tabla reactiva con TODAS las columnas del DTO ``Entidad``,
 *      leidas de ``store.memoryState.entidades`` (lista plana
 *      multi-PLC; el filtro por PLC vive en el preview del PLC
 *      concreto, igual que ``DispositivosPanel``).
 *
 * Multi-PLC: la lista del cache viene plana con todas las entidades
 * de todos los PLCs. La columna ``plc_name`` se muestra siempre.
 *
 * Si ``store.memoryState`` esta vacio, pinta el mismo empty state
 * que ``DispositivosPanel`` / ``ProcesosPanel``.
 *
 * Tema: Industrial Claro. Solo tokens semanticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent*``).
 */
import { computed, ref } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";
import { apiEntidadesPreview, apiEntidadesSync } from "/js/api.js";

export default {
    name: "EntidadesPanel",
    setup() {
        /**
         * Filas de la tabla: ``store.memoryState.entidades``
         * (lista plana multi-PLC del DTO ``Entidad``). Si la lista
         * esta vacia o ``memoryState`` es null, devolvemos ``[]``.
         */
        const entities = computed(() => {
            if (!store.memoryState) return [];
            const lst = store.memoryState.entidades;
            return Array.isArray(lst) ? lst : [];
        });

        /**
         * ``true`` si hay Excel cargado. Mismo patron que
         * ``DispositivosPanel``: empty state global si no hay memoria.
         */
        const hasMemory = computed(
            () => store.memoryState !== null
                && store.memoryState !== undefined
        );

        /**
         * PLC activo del sidebar. Los 2 botones llaman al stub
         * con este nombre. Si esta vacio, los botones se deshabilitan
         * con tooltip accionable.
         */
        const plcName = computed(() => store.selectedPlc || "");

        /**
         * True mientras hay un request al backend en vuelo (preview
         * o apply). Los 2 botones se deshabilitan mutuamente.
         */
        const isWorking = ref(false);

        /**
         * Ultimo resultado de un endpoint stub: ``null`` o
         * ``{ kind: "preview"|"apply", ok: bool, status, note,
         * plc_name, ts: ISO }``. El template lo pinta en un banner
         * azul (info) o rojo (error) bajo los botones.
         */
        const lastResult = ref(null);

        /**
         * Helper UX: ``displayValue`` muestra ``-`` para
         * ``null/undefined/""`` en vez de celdas vacias feas.
         */
        function displayValue(value) {
            if (value === null || value === undefined) return "-";
            if (typeof value === "string" && value.trim() === "") return "-";
            return String(value);
        }

        /**
         * Click en "🔍 Generar Prevision". Llama al stub
         * ``/api/v1/entidades/preview`` con el PLC del store.
         * Si el operario no ha seleccionado PLC, no hace nada y
         * muestra un banner con el motivo.
         */
        async function handlePreview() {
            if (isWorking.value) return;
            if (!plcName.value) {
                lastResult.value = {
                    kind: "preview",
                    ok: false,
                    error: "Selecciona un PLC en el sidebar antes de generar la prevision.",
                    ts: new Date().toISOString(),
                };
                return;
            }
            isWorking.value = true;
            try {
                const r = await apiEntidadesPreview(plcName.value);
                if (r && r.ok) {
                    lastResult.value = {
                        kind: "preview",
                        ok: true,
                        status: r.data.status || "ok",
                        note: r.data.note || "",
                        plc_name: plcName.value,
                        ts: new Date().toISOString(),
                    };
                } else {
                    lastResult.value = {
                        kind: "preview",
                        ok: false,
                        error: (r && r.data && (r.data.error || r.data.detail))
                            || "Error generando prevision",
                        ts: new Date().toISOString(),
                    };
                }
            } catch (e) {
                lastResult.value = {
                    kind: "preview",
                    ok: false,
                    error: String(e && e.message ? e.message : e),
                    ts: new Date().toISOString(),
                };
            } finally {
                isWorking.value = false;
            }
        }

        /**
         * Click en "✓ Aplicar en TIA". Llama al stub
         * ``/api/v1/entidades/sincronizar`` con el PLC del store.
         * Mismo guard de PLC que el preview.
         */
        async function handleApply() {
            if (isWorking.value) return;
            if (!plcName.value) {
                lastResult.value = {
                    kind: "apply",
                    ok: false,
                    error: "Selecciona un PLC en el sidebar antes de aplicar.",
                    ts: new Date().toISOString(),
                };
                return;
            }
            isWorking.value = true;
            try {
                const r = await apiEntidadesSync(plcName.value);
                if (r && r.ok) {
                    lastResult.value = {
                        kind: "apply",
                        ok: true,
                        status: r.data.status || "ok",
                        note: r.data.note || "",
                        plc_name: plcName.value,
                        ts: new Date().toISOString(),
                    };
                } else {
                    lastResult.value = {
                        kind: "apply",
                        ok: false,
                        error: (r && r.data && (r.data.error || r.data.detail))
                            || "Error aplicando entidades",
                        ts: new Date().toISOString(),
                    };
                }
            } catch (e) {
                lastResult.value = {
                    kind: "apply",
                    ok: false,
                    error: String(e && e.message ? e.message : e),
                    ts: new Date().toISOString(),
                };
            } finally {
                isWorking.value = false;
            }
        }

        /**
         * Cierra el banner del ultimo resultado. UX: si el operario
         * lo ha leido, le deja limpiarlo sin esperar a la siguiente
         * accion.
         */
        function dismissResult() {
            lastResult.value = null;
        }

        return {
            entities,
            hasMemory,
            plcName,
            isWorking,
            lastResult,
            displayValue,
            handlePreview,
            handleApply,
            dismissResult,
        };
    },
    template: /* html */ `
        <div class="flex-1 flex flex-col overflow-hidden">

            <!-- ★ Cabecera con 2 botones de accion (commit B.0 stubs).
                 Los 2 botones llaman al backend contra el PLC del
                 sidebar. Se deshabilitan si no hay PLC o si hay un
                 request en vuelo. ★ -->
            <div class="mb-3 bg-surface-raised border border-line rounded p-3 flex items-center gap-3">
                <div class="flex-1">
                        <div class="text-xs font-semibold text-ink-muted uppercase">Acciones sobre el PLC</div>
                        <div class="text-xs text-ink-muted mt-0.5">
                            PLC activo:
                            <span v-if="plcName" class="font-mono text-ink">{{ plcName }}</span>
                            <span v-else class="text-amber-700">ninguno (selecciona uno en el sidebar)</span>
                        </div>
                    </div>
                    <button @click="handlePreview"
                        :disabled="isWorking"
                        data-testid="entidades-preview-btn"
                        class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                        🔍 Generar Prevision
                    </button>
                    <button @click="handleApply"
                        :disabled="isWorking"
                        data-testid="entidades-apply-btn"
                        class="px-3 py-1.5 bg-accent text-ink-inverse font-semibold text-xs rounded-md transition-colors duration-200 hover:bg-accent-hover flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                        ✓ Aplicar en TIA
                    </button>
                </div>

                <!-- ★ Banner del ultimo resultado stub. Azul si OK,
                     rojo si error. ★ -->
                <div v-if="lastResult"
                    :class="lastResult.ok
                        ? 'mb-3 bg-accent-subtle border border-line rounded p-3 text-xs text-ink'
                        : 'mb-3 bg-red-50 border border-red-300 rounded p-3 text-xs text-red-700'"
                    data-testid="entidades-result-banner">
                    <div class="flex justify-between items-start gap-3">
                        <div class="flex-1">
                            <div v-if="lastResult.ok" class="font-semibold">
                                {{ lastResult.kind === "preview" ? "Prevision (stub)" : "Aplicar (stub)" }}: {{ lastResult.status }}
                                <span class="ml-1 text-ink-muted font-normal">({{ lastResult.plc_name }})</span>
                            </div>
                            <div v-else class="font-semibold">
                                Error en {{ lastResult.kind === "preview" ? "prevision" : "aplicar" }}
                            </div>
                            <div v-if="lastResult.note" class="mt-0.5 text-ink-muted">{{ lastResult.note }}</div>
                            <div v-else-if="lastResult.error" class="mt-0.5">{{ lastResult.error }}</div>
                        </div>
                        <button @click="dismissResult"
                            class="text-ink-muted hover:text-ink text-xs"
                            aria-label="Cerrar">✕</button>
                    </div>
                </div>

                <!-- ★ Tabla reactiva multi-PLC con los 7 campos del
                     DTO Entidad. ★ -->
                <div class="flex-1 overflow-auto table-scroll-x bg-surface-raised border border-line rounded">
                    <table v-if="hasMemory" class="w-full text-xs">
                        <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                            <tr>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">N°</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">Descripcion</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Tag</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Tipo</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Index</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Comentario</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="e in entities" :key="e.plc_name + '-' + e.numero + '-' + e.plc_tag"
                                class="border-b border-line">
                                <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                                    {{ displayValue(e.numero) }}
                                </td>
                                <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                                    {{ displayValue(e.plc_name) }}
                                </td>
                                <td class="px-3 py-1.5 align-top text-ink whitespace-nowrap">
                                    {{ displayValue(e.descripcion) }}
                                </td>
                                <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                                    {{ displayValue(e.plc_tag) }}
                                </td>
                                <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                                    {{ displayValue(e.plc_tipo) }}
                                </td>
                                <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                                    {{ displayValue(e.plc_index) }}
                                </td>
                                <td class="px-3 py-1.5 align-top text-ink-muted">
                                    {{ displayValue(e.plc_comentario) }}
                                </td>
                            </tr>
                            <tr v-if="entities.length === 0">
                                <td colspan="7"
                                    class="px-3 py-6 text-center text-ink-muted italic">
                                    No contiene entidades. Verifique que la hoja ENTIDADES exista y la Tabla_Entidades tenga filas validas.
                                </td>
                            </tr>
                        </tbody>
                    </table>
                    <div v-else class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                        <div>
                            <div class="text-5xl mb-3 opacity-40">📊</div>
                            <p class="mb-2">La cache del excel esta vacia.</p>
                            <p class="text-xs">Sube un Excel y pulsa <strong class="text-accent">"Actualizar"</strong>.</p>
                        </div>
                    </div>
                </div>
            </div>
        `,
};