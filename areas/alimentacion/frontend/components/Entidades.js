/**
 * Componente Entidades.
 *
 * Sub-vista de primer nivel del area "alimentacion" que se muestra
 * cuando ``store.currentView === 'entidades'``. Es gemela top-level
 * de Dispositivos y Procesos en el sidebar del shell SPA.
 *
 * Estructura (de arriba abajo):
 *   1. Card "info": PLC activo + boton "🔍 Generar Prevision".
 *   2. Card "tabla": tabla plana con los 7 campos del DTO ``Entidad``
 *      filtrada por el PLC del store. Banner del ultimo resultado
 *      del preview/apply (azul si OK, rojo si fallo).
 *   3. Boton "✅ Aplicar en TIA Portal" abajo (accion terminal del
 *      flujo).
 *
 * Stub (commit B.0): los botones llaman a ``apiEntidadesPreview`` /
 * ``apiEntidadesSync`` que devuelven ``status: "preview_stub" /
 * "sincronizar_stub"``. En commit B (FB Preview real) el backend
 * devuelve el diff Excel vs TIA online. En commit C (FB Sync real)
 * aplica los cambios transaccionalmente. Este componente no se
 * toca en B/C: solo se sustituye el backend.
 *
 * Tema: Industrial Claro. Solo tokens semanticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent``,
 * ``bg-amber-*``, ``text-amber-*``, ``text-red-*``, ``text-green-*``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * ``vue.esm-browser.prod.js`` NO acepta string literals multi-linea
 * dentro de arrays de ``:class``. Cada literal va en una sola linea.
 */
import { computed, ref } from "/js/vendor/vue.esm-browser.prod.js";
import { store, resetPlcState } from "/js/store.js";
import { apiEntidadesPreview, apiEntidadesSync } from "/js/api.js";

export default {
    name: "Entidades",
    setup() {
        /**
         * PLC activo del sidebar. Si esta vacio, los botones se
         * deshabilitan con tooltip accionable.
         */
        const plcName = computed(() => store.selectedPlc || "");

        /**
         * Entidades del PLC seleccionado (lista plana
         * ``store.memoryState.entidades`` filtrada por ``plc_name``).
         * Si no hay memoria, lista vacia (mostramos empty state).
         */
        const entities = computed(() => {
            const ms = store.memoryState;
            if (!ms || !Array.isArray(ms.entidades)) return [];
            if (!plcName.value) return [];
            return ms.entidades.filter((e) => e && e.plc_name === plcName.value);
        });

        /**
         * ``true`` solo cuando hay Excel cargado. Mismo patron
         * que ``Dispositivos.js``: empty state global si no hay
         * memoria.
         */
        const hasMemory = computed(
            () => store.memoryState !== null
                && store.memoryState !== undefined
        );

        /**
         * ``true`` solo si hay PLC activo + entidades del PLC.
         * Para que la tabla no muestre empty state confuso cuando
         * hay memoria pero el PLC no tiene entidades en el Excel.
         */
        const hasEntities = computed(
            () => hasMemory.value && plcName.value && entities.value.length > 0
        );

        /**
         * True mientras hay un request al backend en vuelo (preview
         * o apply). Los 2 botones se deshabilitan mutuamente.
         */
        const isWorking = ref(false);

        /**
         * Ultimo resultado de un endpoint stub: ``null`` o
         * ``{ kind: "preview"|"apply", ok: bool, status, note,
         * plc_name, error }``. El template lo pinta en un banner
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
                };
                return;
            }
            isWorking.value = true;
            store.busy = true;
            try {
                const r = await apiEntidadesPreview(plcName.value);
                if (r && r.ok) {
                    lastResult.value = {
                        kind: "preview",
                        ok: true,
                        status: r.data.status || "ok",
                        note: r.data.note || "",
                        plc_name: plcName.value,
                    };
                } else if (r && r.errorType === "TIAConnectionError") {
                    resetPlcState();
                    lastResult.value = {
                        kind: "preview",
                        ok: false,
                        error: "TIA Portal no responde. Reconecta e intentalo de nuevo.",
                    };
                } else {
                    lastResult.value = {
                        kind: "preview",
                        ok: false,
                        error: (r && r.data && (r.data.error || r.data.detail))
                            || "Error generando prevision",
                    };
                }
            } catch (e) {
                lastResult.value = {
                    kind: "preview",
                    ok: false,
                    error: String(e && e.message ? e.message : e),
                };
            } finally {
                isWorking.value = false;
                store.busy = false;
            }
        }

        /**
         * Click en "✅ Aplicar en TIA". Llama al stub
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
                };
                return;
            }
            isWorking.value = true;
            store.busy = true;
            try {
                const r = await apiEntidadesSync(plcName.value);
                if (r && r.ok) {
                    lastResult.value = {
                        kind: "apply",
                        ok: true,
                        status: r.data.status || "ok",
                        note: r.data.note || "",
                        plc_name: plcName.value,
                    };
                } else if (r && r.errorType === "TIAConnectionError") {
                    resetPlcState();
                    lastResult.value = {
                        kind: "apply",
                        ok: false,
                        error: "TIA Portal no responde. Reconecta e intentalo de nuevo.",
                    };
                } else {
                    lastResult.value = {
                        kind: "apply",
                        ok: false,
                        error: (r && r.data && (r.data.error || r.data.detail))
                            || "Error aplicando entidades",
                    };
                }
            } catch (e) {
                lastResult.value = {
                    kind: "apply",
                    ok: false,
                    error: String(e && e.message ? e.message : e),
                };
            } finally {
                isWorking.value = false;
                store.busy = false;
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
            store,
            plcName,
            entities,
            hasMemory,
            hasEntities,
            isWorking,
            lastResult,
            displayValue,
            handlePreview,
            handleApply,
            dismissResult,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- ★ Card "info" (estilo Dispositivos.js): PLC activo +
                 boton "Generar Prevision". ★ -->
            <div class="mb-4 bg-surface-raised border border-line rounded p-4 flex justify-between items-center"
                 data-testid="entidades-card-info">
                <div class="text-xs text-ink-muted">
                    PLC activo:
                    <span v-if="plcName" class="font-mono text-ink font-semibold">{{ plcName }}</span>
                    <span v-else class="text-amber-700">ninguno (selecciona uno en el sidebar)</span>
                    <span v-if="hasEntities" class="ml-3 text-ink-muted">
                        · <span class="text-ink font-semibold">{{ entities.length }}</span> entidades
                    </span>
                </div>
                <button @click="handlePreview"
                    :disabled="!plcName || isWorking"
                    data-testid="entidades-preview-btn"
                    class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    🔍 Generar Prevision
                </button>
            </div>

            <!-- ★ Banner del ultimo resultado del stub. Azul si OK,
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

            <!-- ★ Card "tabla" (estilo Dispositivos.js): tabla plana
                 con las entidades del PLC seleccionado + boton
                 "Aplicar en TIA" abajo. ★ -->
            <div class="flex-1 bg-surface-raised border border-line rounded p-4 mb-4 flex flex-col overflow-hidden"
                 data-testid="entidades-card-tabla">

                <div class="flex-1 overflow-auto table-scroll-x bg-surface-raised border border-line rounded">
                    <table v-if="hasEntities" class="w-full text-xs">
                        <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                            <tr>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">N°</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">Descripcion</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Tag</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Tipo</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Index</th>
                                <th class="px-3 py-2 text-left text-ink-muted whitespace-nowrap">PLC.Comentario</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="e in entities" :key="e.numero + '-' + e.plc_tag"
                                class="border-b border-line">
                                <td class="px-3 py-1.5 align-top text-ink font-mono whitespace-nowrap">
                                    {{ displayValue(e.numero) }}
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
                        </tbody>
                    </table>

                    <div v-else-if="!hasMemory" class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                        <div>
                            <div class="text-5xl mb-3 opacity-40">📊</div>
                            <p class="mb-2">La cache del excel esta vacia.</p>
                            <p class="text-xs">Sube un Excel y pulsa <strong class="text-accent">"Actualizar"</strong>.</p>
                        </div>
                    </div>

                    <div v-else-if="!plcName" class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                        <div>
                            <div class="text-5xl mb-3 opacity-40">🔌</div>
                            <p class="mb-2">Selecciona un PLC en el sidebar para ver sus entidades.</p>
                        </div>
                    </div>

                    <div v-else class="flex-1 flex items-center justify-center p-10 text-center text-ink-muted">
                        <div>
                            <div class="text-5xl mb-3 opacity-40">🗂️</div>
                            <p class="mb-2">El PLC <span class="font-mono text-ink">{{ plcName }}</span> no tiene entidades en el Excel.</p>
                            <p class="text-xs">Verifica que la hoja ENTIDADES tenga la fila <strong class="text-accent">{{ plcName }}</strong>.</p>
                        </div>
                    </div>
                </div>

                <button @click="handleApply"
                    :disabled="!plcName || isWorking"
                    data-testid="entidades-apply-btn"
                    class="mt-3 w-full py-3 text-accent font-semibold text-sm bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    ✅ Aplicar en TIA Portal
                </button>
            </div>
        </section>
    `,
};