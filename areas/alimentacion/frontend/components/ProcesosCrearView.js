/**
 * Componente ProcesosCrearView.
 *
 * Vista inline que permite al operario clonar un proceso industrial
 * desde una plantilla TIA. Se monta como panel hijo de 'Procesos.js'
 * (paralelo a '<procesos-sync-view>') y NO cambia 'store.currentView'.
 *
 * El Excel del operario es la fuente de verdad: este componente NO
 * pide al operario los datos del proceso nuevo (uid, codigo, nombre,
 * N_MAX). En su lugar:
 *   1. Lee la lista de plantillas disponibles con
 *      'apiListPlantillas'. Si no hay 'plantillas_path' configurado
 *      (warning), el operario puede abrir el modal y editarlo via
 *      'apiUpdatePlantillasPath' (PUT). Tras guardar, se recarga la
 *      lista.
 *   2. Lee los procesos del Excel ya cacheado en
 *      'store.memoryState.procesos' (NO hace falta volver a pedirlo).
 *   3. Click "Generar prevision" -> llama
 *      'apiProcesosCrearPreview' pasando solo 'dir_plantilla_nombre'
 *      y 'proc_uid'. El backend resuelve los N_MAX desde el Excel y
 *      dispara el FB.
 *   4. Click "Aplicar al PLC" -> llama 'apiProcesosCrearAplicar'.
 *      Mientras esta en vuelo el boton esta disabled. Al terminar
 *      muestra OK o el error del backend.
 *
 * Si no hay Excel cargado, la card padre (Procesos.js) ya pinta un
 * banner ambar. Aqui se refuerza mostrando tambien un mensaje claro.
 *
 * Tema: Industrial Claro. Solo tokens semanticos ('bg-surface*',
 * 'border-line*', 'text-ink*', 'bg-accent', 'text-green-700',
 * 'text-amber-700', 'text-red-700').
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * 'vue.esm-browser.prod.js' NO acepta string literals multi-linea
 * dentro de arrays de ':class'. Cada literal va en una sola linea.
 * Ademas, prohibido usar backticks literales `` dentro de comentarios
 * HTML del template (cierran prematuramente el string template JS).
 * Usar comillas simples o nada.
 */
import { computed, ref, watch } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";
import {
    apiListPlantillas,
    apiUpdatePlantillasPath,
    apiProcesosCrearPreview,
    apiProcesosCrearAplicar,
} from "/js/api.js";

export default {
    name: "ProcesosCrearView",
    emits: ["close"],
    setup(props, { emit }) {
        // -----------------------------------------------------------------
        // Estado: plantillas (config + disponibles)
        // -----------------------------------------------------------------
        const plantillas = ref([]);
        const plantillasLoading = ref(false);
        const plantillasWarning = ref(null);
        const plantillasPathActual = ref("");

        const selectedPlantillaCarpeta = ref("");

        // -----------------------------------------------------------------
        // Estado: proceso del Excel seleccionado
        // -----------------------------------------------------------------
        const selectedProcUid = ref(null);

        // -----------------------------------------------------------------
        // Estado: preview + apply
        // -----------------------------------------------------------------
        const previewData = ref(null);
        const aplicacionEstado = ref("");          // "" | "aplicando" | "ok" | "error"
        const aplicacionError = ref(null);

        // -----------------------------------------------------------------
        // Estado: modal de la ruta
        // -----------------------------------------------------------------
        const showPathModal = ref(false);
        const pathEditBuffer = ref("");

        // -----------------------------------------------------------------
        // Computed
        // -----------------------------------------------------------------

        // Lista de procesos del Excel (data-driven desde store).
        // Cada item ya tiene al menos 'uid', 'codigo' y 'nombre'.
        const procesosExcel = computed(
            () => (store.memoryState && store.memoryState.procesos) || []
        );

        // Proceso del Excel actualmente seleccionado (para mostrar en
        // la cabecera los valores que el backend va a usar).
        const selectedProc = computed(
            () =>
                procesosExcel.value.find(
                    (p) => p && Number(p.uid) === Number(selectedProcUid.value)
                ) || null
        );

        const hayExcel = computed(
            () =>
                store.memoryState !== null &&
                store.memoryState !== undefined &&
                procesosExcel.value.length > 0
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
                Boolean(selectedProc.value) &&
                Number.isFinite(Number(selectedProcUid.value)) &&
                !aplicacionBotonDisabled.value
        );

        const aplicacionBotonDisabled = computed(
            () =>
                !previewData.value ||
                (Array.isArray(previewData.value.colisiones) &&
                    previewData.value.colisiones.length > 0) ||
                aplicacionEstado.value === "aplicando"
        );

        // -----------------------------------------------------------------
        // Funciones
        // -----------------------------------------------------------------

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
                // Si la plantilla seleccionada ya no existe, la
                // limpiamos para no quedar con un estado inconsistente.
                if (
                    selectedPlantillaCarpeta.value &&
                    !plantillas.value.some(
                        (p) => p.carpeta === selectedPlantillaCarpeta.value
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
                proc_uid: Number(selectedProcUid.value),
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
                proc_uid: Number(selectedProcUid.value),
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

        // Si el operario cambia de proceso del Excel mientras hay un
        // preview aplicado, limpiamos el preview: el anterior ya no
        // es valido para el nuevo procUid.
        watch(
            () => Number(selectedProcUid.value),
            () => {
                previewData.value = null;
                aplicacionEstado.value = "";
                aplicacionError.value = null;
            }
        );

        // -----------------------------------------------------------------
        // Wire al cargarse
        // -----------------------------------------------------------------
        loadPlantillas();

        // -----------------------------------------------------------------
        // Return: todo lo que el template debe leer o invocar.
        // -----------------------------------------------------------------
        return {
            plantillas,
            plantillasLoading,
            plantillasWarning,
            plantillasPathActual,
            selectedPlantillaCarpeta,
            selectedPlantilla,
            procesosExcel,
            selectedProcUid,
            selectedProc,
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
                        Clona una plantilla TIA (tags + DBs + bloques) para un proceso del Excel.
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

            <!-- Mini-modal: editar la ruta. Coherente con "sub-view inline
                 NO usa overlays". -->
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

            <!-- Banner si NO hay Excel cargado. -->
            <div v-if="!hayExcel"
                 class="mt-3 px-3 py-2 bg-amber-100 border border-amber-300 rounded text-xs text-amber-800">
                No hay procesos en el Excel. Sube un Excel antes de continuar.
            </div>

            <!-- Selector de proceso del Excel: el Excel ES la fuente de verdad.
                 El backend extrae 'uid' = proc.uid, 'codigo' = proc.codigo,
                 'nombre' = proc.nombre, N_MAX_* = proc.preal/pint/alarmas/alm_hmi. -->
            <div v-if="hayExcel" class="mt-3">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-1">
                    Proceso del Excel a crear
                </label>
                <select v-model.number="selectedProcUid"
                        data-testid="procesos-crear-proc-select"
                        class="w-full bg-white border border-line text-accent font-bold text-sm rounded focus:border-accent focus:outline-none px-3 py-1.5 font-mono cursor-pointer">
                    <option :value="null">
                        Selecciona un proceso...
                    </option>
                    <option v-for="p in procesosExcel" :key="p.uid" :value="p.uid">
                        {{ p.codigo }} - {{ p.nombre }} (uid {{ p.uid }})
                    </option>
                </select>

                <!-- Mostrar los valores del proceso seleccionado para que el
                     operario verifique que el backend va a usar estos N_MAX. -->
                <div v-if="selectedProc"
                     class="mt-2 grid grid-cols-3 gap-2 text-xs">
                    <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                        <div class="text-ink-muted">PREAL</div>
                        <div class="font-mono font-bold text-accent text-sm">
                            {{ selectedProc.preal }}
                        </div>
                    </div>
                    <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                        <div class="text-ink-muted">PINT</div>
                        <div class="font-mono font-bold text-accent text-sm">
                            {{ selectedProc.pint }}
                        </div>
                    </div>
                    <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                        <div class="text-ink-muted">ALM</div>
                        <div class="font-mono font-bold text-accent text-sm">
                            {{ selectedProc.alarmas }}
                        </div>
                    </div>
                    <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                        <div class="text-ink-muted">ALM HMI</div>
                        <div class="font-mono font-bold text-accent text-sm">
                            {{ selectedProc.alm_hmi }}
                        </div>
                    </div>
                    <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                        <div class="text-ink-muted">UID</div>
                        <div class="font-mono font-bold text-accent text-sm">
                            {{ selectedProc.uid }}
                        </div>
                    </div>
                    <div class="bg-surface-sunken border border-line rounded px-2 py-1">
                        <div class="text-ink-muted">Codigo</div>
                        <div class="font-mono font-bold text-accent text-sm">
                            {{ selectedProc.codigo }}
                        </div>
                    </div>
                </div>
            </div>

            <button type="button"
                    :disabled="!canGenerate"
                    data-testid="procesos-crear-generar-preview"
                    class="mt-4 px-3 py-1.5 bg-accent text-ink-inverse rounded-md text-xs font-semibold hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed">
                Generar prevision
            </button>

            <!-- Tabla de archivos previstos. -->
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
