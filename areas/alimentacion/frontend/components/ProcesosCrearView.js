/**
 * Componente ProcesosCrearView.
 *
 * Vista inline que permite al operario clonar un proceso industrial
 * desde una plantilla TIA. Se monta como panel hijo de 'Procesos.js'
 * (paralelo a '<procesos-sync-view>') y NO cambia 'store.currentView'.
 *
 * Recibe 'procUid' como prop desde 'Procesos.js'. La pagina padre
 * ya tiene el selector del proceso del Excel; el operario elige
 * ahi el proceso a crear y luego pulsa "Crear proceso completo".
 * Este sub-componente solo pide la plantilla a usar.
 *
 * El backend es la fuente de verdad para los N_MAX: este componente
 * NO los pide, los lee del store (que es la copia del Excel ya
 * cacheado) para mostrarlos al operario antes de generar la
 * prevision.
 *
 * Flujo:
 *   1. Carga plantillas via 'apiListPlantillas'.
 *   2. Operario selecciona plantilla (unica interaccion aqui).
 *   3. Click "Generar prevision" -> 'apiProcesosCrearPreview' con
 *      '{dir_plantilla_nombre, proc_uid}'.
 *   4. Click "Aplicar al PLC" -> 'apiProcesosCrearAplicar'.
 *
 * Tema: Industrial Claro. Solo tokens semanticos.
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime NO acepta
 * string literals multi-linea dentro de arrays ':class'. Ademas,
 * prohibido usar backticks literales dentro de comentarios HTML del
 * template (cierran prematuramente el string template JS).
 */
import { computed, ref } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";
import {
    apiListPlantillas,
    apiUpdatePlantillasPath,
    apiProcesosCrearPreview,
    apiProcesosCrearAplicar,
} from "/js/api.js";

export default {
    name: "ProcesosCrearView",
    props: {
        /**
         * UID del proceso del Excel que el operario quiere crear.
         * Lo pasa 'Procesos.js' desde su selector.
         */
        procUid: {
            type: Number,
            default: null,
        },
    },
    emits: ["close"],
    setup(props, { emit }) {
        // ── Estado: plantillas (config + disponibles) ─────────
        const plantillas = ref([]);
        const plantillasLoading = ref(false);
        const plantillasWarning = ref(null);
        const plantillasPathActual = ref("");

        const selectedPlantillaCarpeta = ref("");

        // ── Estado: preview + apply ────────────────────────────
        const previewData = ref(null);
        const aplicacionEstado = ref("");          // "" | "aplicando" | "ok" | "error"
        const aplicacionError = ref(null);

        // ── Estado: modal de la ruta ───────────────────────────
        const showPathModal = ref(false);
        const pathEditBuffer = ref("");

        // ── Computed ────────────────────────────────────────────

        // Proceso del Excel seleccionado (lo busca del store por uid).
        // La fuente de verdad son los 8 campos del Excel: uid, nombre,
        // codigo, preal, pint, index_preal, index_pint, alarmas, alm_hmi.
        const procesoExcel = computed(
            () => {
                const procs =
                    (store.memoryState &&
                        store.memoryState.procesos) ||
                    [];
                return (
                    procs.find(
                        (p) => Number(p.uid) === Number(props.procUid)
                    ) || null
                );
            }
        );

        const hayExcel = computed(
            () => Boolean(store.memoryState) && procesoExcel.value !== null
        );

        const selectedPlantilla = computed(
            () =>
                plantillas.value.find(
                    (p) => p.carpeta === selectedPlantillaCarpeta.value
                ) || null
        );

        const canGenerate = computed(
            () =>
                Boolean(selectedPlantilla.value) &&
                hayExcel.value &&
                !aplicacionBotonDisabled.value
        );

        const aplicacionBotonDisabled = computed(
            () =>
                !previewData.value ||
                (Array.isArray(previewData.value.colisiones) &&
                    previewData.value.colisiones.length > 0) ||
                aplicacionEstado.value === "aplicando"
        );

        // ── Funciones ──────────────────────────────────────────

        async function loadPlantillas() {
            plantillasLoading.value = true;
            plantillasWarning.value = null;
            const r = await apiListPlantillas();
            plantillasLoading.value = false;
            if (r && r.ok && r.data) {
                plantillas.value = r.data.plantillas || [];
                plantillasWarning.value = r.data.warning || null;
                plantillasPathActual.value =
                    r.data.plantillas_path || "";
                if (
                    selectedPlantillaCarpeta.value &&
                    !plantillas.value.some(
                        (p) =>
                            p.carpeta === selectedPlantillaCarpeta.value
                    )
                ) {
                    selectedPlantillaCarpeta.value = "";
                }
            } else {
                plantillas.value = [];
                plantillasWarning.value =
                    (r && r.data && r.data.warning) ||
                    (r ? `Error ${r.status}` : "Sin respuesta del backend");
            }
        }

        async function guardarPath() {
            const newPath = pathEditBuffer.value.trim();
            if (!newPath) return;
            const r = await apiUpdatePlantillasPath(newPath);
            if (r && r.ok) {
                plantillasPathActual.value = newPath;
                showPathModal.value = false;
                await loadPlantillas();
            } else {
                aplicacionError.value =
                    "No se pudo guardar: " +
                    ((r && r.data && r.data.error) || (r ? r.status : "?"));
            }
        }

        async function generarPreview() {
            if (!canGenerate.value) return;
            aplicacionEstado.value = "";
            aplicacionError.value = null;
            previewData.value = null;
            const params = {
                dir_plantilla_nombre: selectedPlantillaCarpeta.value,
                proc_uid: Number(props.procUid),
            };
            const r = await apiProcesosCrearPreview(params);
            if (r && r.ok && r.data) {
                previewData.value = r.data;
            } else {
                aplicacionError.value =
                    "Preview fallo: " +
                    ((r && r.data && r.data.error) || (r ? r.status : "?"));
            }
        }

        async function aplicar() {
            if (aplicacionBotonDisabled.value) return;
            aplicacionEstado.value = "aplicando";
            aplicacionError.value = null;
            const params = {
                dir_plantilla_nombre: selectedPlantillaCarpeta.value,
                proc_uid: Number(props.procUid),
                plc_name: store.selectedPlc || "",
            };
            const r = await apiProcesosCrearAplicar(params);
            aplicacionEstado.value = r && r.ok ? "ok" : "error";
            if (!r || !r.ok) {
                aplicacionError.value =
                    "Apply fallo: " +
                    ((r && r.data && r.data.error) || (r ? r.status : "?"));
            }
        }

        // ── Wire al cargarse ───────────────────────────────────
        loadPlantillas();

        // ── Return ─────────────────────────────────────────────
        const procedimientoLabel = computed(
            () => {
                const p = procesoExcel.value;
                if (!p) return "(ninguno)";
                return `${p.codigo} - ${p.nombre} (uid ${p.uid})`;
            }
        );

        return {
            plantillas,
            plantillasLoading,
            plantillasWarning,
            plantillasPathActual,
            selectedPlantillaCarpeta,
            selectedPlantilla,
            procesoExcel,
            procedimientoLabel,
            hayExcel,
            previewData,
            aplicacionEstado,
            aplicacionError,
            showPathModal,
            pathEditBuffer,
            canGenerate,
            aplicacionBotonDisabled,
            loadPlantillas,
            guardarPath,
            generarPreview,
            aplicar,
            cerrar() { emit("close"); },
        };
    },
    template: /* html */ `
        <section>
            <header class="flex justify-between items-start mb-4">
                <div>
                    <h2 class="text-lg font-bold text-ink">Crear proceso completo desde plantilla</h2>
                    <p class="text-xs text-ink-muted mt-0.5">
                        Proceso seleccionado: <span class="font-mono font-bold text-accent">{{ procedimientoLabel }}</span>
                    </p>
                </div>
                <button @click="cerrar"
                        data-testid="procesos-crear-close"
                        class="bg-surface border border-line rounded px-3 py-1 text-xs text-ink hover:bg-surface-sunken">
                    Cerrar
                </button>
            </header>

            <!-- Bloque "ruta de plantillas": boton + texto con la ruta actual. -->
            <div class="flex items-center gap-2">
                <button @click="showPathModal = true; pathEditBuffer = plantillasPathActual"
                        data-testid="procesos-crear-configure-path"
                        class="bg-surface border border-line rounded px-3 py-1 text-xs text-ink hover:bg-surface-sunken">
                    Configurar ruta de plantillas
                </button>
                <span v-if="plantillasPathActual" class="text-xs text-ink-muted">
                    ({{ plantillasPathActual }})
                </span>
                <span v-else class="text-xs text-amber-700">
                    (ruta no configurada)
                </span>
            </div>

            <div v-if="showPathModal"
                 data-testid="procesos-crear-path-modal"
                 class="bg-surface-sunken border border-line rounded p-3 mt-2">
                <label class="block text-xs font-semibold text-ink-muted mb-1">
                    Ruta base de plantillas
                </label>
                <input v-model="pathEditBuffer"
                       placeholder="C:/Users/Aketza/plantillas_tia"
                       class="w-full bg-white border border-line rounded px-2 py-1 text-xs font-mono focus:border-accent focus:outline-none" />
                <div class="flex gap-2 mt-2">
                    <button @click="guardarPath"
                            :disabled="!pathEditBuffer.trim()"
                            data-testid="procesos-crear-path-save"
                            class="bg-accent text-ink-inverse rounded px-3 py-1 text-xs hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed">
                        Guardar
                    </button>
                    <button @click="showPathModal = false"
                            class="bg-surface border border-line rounded px-3 py-1 text-xs text-ink hover:bg-surface-sunken">
                        Cancelar
                    </button>
                </div>
            </div>

            <div v-if="plantillasWarning"
                 data-testid="procesos-crear-warning"
                 class="text-amber-700 text-xs mt-2">
                Aviso: {{ plantillasWarning }}
            </div>

            <!-- Selector de plantilla. -->
            <div class="mt-3">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-1">
                    Plantilla
                </label>
                <select v-model="selectedPlantillaCarpeta"
                        :disabled="!plantillas.length || plantillasLoading"
                        data-testid="procesos-crear-plantilla-select"
                        class="w-full bg-white border border-line text-accent font-bold text-sm rounded focus:border-accent focus:outline-none px-3 py-1.5 font-mono disabled:opacity-50 cursor-pointer">
                    <option value="">
                        {{ plantillasLoading ? "Cargando..." : (plantillas.length ? "Selecciona..." : "Sin plantillas") }}
                    </option>
                    <option v-for="p in plantillas" :key="p.carpeta" :value="p.carpeta">
                        {{ p.codigo }} - {{ p.nombre }} (base {{ p.base }})
                    </option>
                </select>
            </div>

            <!-- Grid con los N_MAX del proceso del Excel seleccionado.
                 Es solo informativo (preview para el operario de lo que
                 el backend va a usar); los valores reales los resuelve
                 el backend via ProcGenerateProcExcel en AppState. -->
            <div v-if="hayExcel" class="mt-3 grid grid-cols-3 gap-2 text-xs">
                <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                    <div class="text-ink-muted">PREAL</div>
                    <div class="font-mono font-bold text-accent text-sm">
                        {{ procesoExcel.preal }}
                    </div>
                </div>
                <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                    <div class="text-ink-muted">PINT</div>
                    <div class="font-mono font-bold text-accent text-sm">
                        {{ procesoExcel.pint }}
                    </div>
                </div>
                <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                    <div class="text-ink-muted">ALM</div>
                    <div class="font-mono font-bold text-accent text-sm">
                        {{ procesoExcel.alarmas }}
                    </div>
                </div>
                <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                    <div class="text-ink-muted">ALM HMI</div>
                    <div class="font-mono font-bold text-accent text-sm">
                        {{ procesoExcel.alm_hmi }}
                    </div>
                </div>
                <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                    <div class="text-ink-muted">UID</div>
                    <div class="font-mono font-bold text-accent text-sm">
                        {{ procesoExcel.uid }}
                    </div>
                </div>
                <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                    <div class="text-ink-muted">Codigo</div>
                    <div class="font-mono font-bold text-accent text-sm">
                        {{ procesoExcel.codigo }}
                    </div>
                </div>
            </div>

            <button type="button"
                    :disabled="!canGenerate"
                    data-testid="procesos-crear-generar-preview"
                    class="mt-4 px-3 py-1.5 bg-accent text-ink-inverse rounded-md text-xs font-semibold hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed">
                Generar prevision
            </button>

            <div v-if="previewData" class="mt-4">
                <h3 class="text-sm font-semibold text-ink mb-2">
                    Archivos a generar ({{ (previewData.archivos_previstos || []).length }})
                </h3>
                <p v-if="Array.isArray(previewData.colisiones) && previewData.colisiones.length"
                   class="text-red-700 text-xs mb-2">
                    Aviso: {{ previewData.colisiones.length }} colision(es) detectada(s). Cambia el proceso o plantilla para evitar pisar bloques existentes en el PLC.
                </p>
                <table class="w-full text-xs">
                    <thead><tr class="text-left text-ink-muted">
                        <th class="py-1 pr-2">Original</th>
                        <th class="py-1 pr-2">Nuevo</th>
                        <th class="py-1 pr-2">Tipo</th>
                    </tr></thead>
                    <tbody>
                        <tr v-for="a in previewData.archivos_previstos"
                            :key="a.rel_in"
                            :class="a.colisiona ? 'text-red-700' : 'text-ink'">
                            <td class="font-mono py-1 pr-2">{{ a.rel_in }}</td>
                            <td class="font-mono py-1 pr-2">{{ a.rel_out }}</td>
                            <td class="py-1 pr-2">{{ a.kind }}</td>
                        </tr>
                    </tbody>
                </table>
                <button :disabled="aplicacionBotonDisabled"
                        data-testid="procesos-crear-aplicar"
                        @click="aplicar"
                        class="mt-3 px-3 py-1.5 bg-accent text-ink-inverse rounded-md text-xs font-semibold hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed">
                    {{ aplicacionEstado === "aplicando" ? "Aplicando..." : "Aplicar al PLC" }}
                </button>
                <p v-if="aplicacionEstado === 'ok'" class="text-green-700 text-xs mt-2">
                    Proceso creado OK.
                </p>
                <p v-if="aplicacionEstado === 'error' && aplicacionError"
                   class="text-red-700 text-xs mt-2">
                    {{ aplicacionError }}
                </p>
            </div>
        </section>
    `,
};
