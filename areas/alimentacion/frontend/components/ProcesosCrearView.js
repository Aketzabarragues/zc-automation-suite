/**
 * Componente ProcesosCrearView.
 *
 * Sub-vista INLINE que permite "Crear proceso completo desde
 * plantilla TIA". Se monta como panel hijo de ``Procesos.js``
 * (paralelo a ``<procesos-sync-view>``) y NO cambia
 * ``store.currentView``. El componente emite ``close`` cuando el
 * operario pulsa "Cerrar" y el padre colapsa la vista.
 *
 * Flujo:
 *   1. Carga las plantillas disponibles con ``apiListPlantillas``.
 *      Si no hay ``plantillas_path`` configurado (warning), el
 *      operario puede abrir el mini-modal "Configurar ruta" y
 *      llamar a ``apiUpdatePlantillasPath`` (PUT). Tras guardar, se
 *      recarga la lista automaticamente.
 *   2. El operario selecciona una plantilla (carpeta) y rellena el
 *      formulario: ``base_nueva`` (int >= 10000), ``codigo_nuevo``
 *      (str), ``nombre_nuevo`` (str) y los 4 N_MAX
 *      (PReal/PInt/ALM/ALM_HMI). Los campos se exponen al template
 *      via ``computed`` (Vue 3 runtime no expone refs importados al
 *      scope del template).
 *   3. Click "Generar prevision" -> ``apiProcesosCrearPreview``.
 *      Renderiza la tabla de archivos previstos + banner rojo si
 *      hay colisiones.
 *   4. Click "Aplicar al PLC" -> ``apiProcesosCrearAplicar``.
 *      Mientras esta en vuelo el boton esta disabled. Al terminar
 *      muestra OK o el error del backend.
 *
 * Estado:
 *   - 100% local (refs). NO toca ``store.memoryState`` ni
 *     ``store.procesosSync``. Esto es intencional: el crear proceso
 *     es un flujo aislado que no comparte estado con el sync de
 *     comentarios.
 *   - ``pushLog`` NO se importa (``store.js`` no lo exporta). El
 *     feedback al operario vive en ``aplicacionEstado`` /
 *     ``aplicacionError`` (reflejados en el template).
 *
 * Tema: Industrial Claro. Solo tokens semanticos (``bg-surface*``,
 * ``border-line*``, ``text-ink*``, ``bg-accent``,
 * ``text-green-700``, ``text-amber-700``, ``text-red-700``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * ``vue.esm-browser.prod.js`` NO acepta string literals multi-linea
 * dentro de arrays de ``:class``. Cada literal va en una sola linea.
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
    emits: ["close"],
    setup(props, { emit }) {
        // -----------------------------------------------------------------
        // Estado reactivo (todo local; el componente es autocontenido).
        // -----------------------------------------------------------------

        /** Lista de plantillas del backend (``apiListPlantillas``). */
        const plantillas = ref([]);

        /** True mientras llega la respuesta de ``apiListPlantillas``. */
        const plantillasLoading = ref(false);

        /** Warning del backend (p.ej. "no hay plantillas_path"). */
        const plantillasWarning = ref(null);

        /** Ruta actual de plantillas cacheada en el backend. */
        const plantillasPathActual = ref("");

        /**
         * Carpeta (string) seleccionada en el ``<select>``. Se
         * compara contra ``p.carpeta`` de cada plantilla para
         * encontrar la activa. ``""`` = ninguna.
         */
        const selectedPlantillaCarpeta = ref("");

        /**
         * Formulario. ``base_nueva`` debe ser >= 10000 (mismo
         * rango que usan los procesos del Excel); los N_MAX son
         * enteros no negativos.
         */
        const form = ref({
            base_nueva: 0,
            codigo_nuevo: "",
            nombre_nuevo: "",
            minimos_usuario: {
                N_MAX_PREAL: 0,
                N_MAX_PINT: 0,
                N_MAX_ALM: 0,
                N_MAX_ALM_HMI: 0,
            },
        });

        /**
         * Resultado del ultimo ``apiProcesosCrearPreview``. Shape:
         * ``{archivos_previstos, colisiones, ...}``. ``null`` hasta
         * que el operario pulsa "Generar prevision".
         */
        const previewData = ref(null);

        /**
         * Estado del apply. ``""`` = inactivo, ``"aplicando"`` =
         * fetch en vuelo, ``"ok"`` = aplicado, ``"error"`` = fallo.
         * Se refleja en el boton "Aplicar al PLC".
         */
        const aplicacionEstado = ref("");

        /** Mensaje de error legible (preview o apply). */
        const aplicacionError = ref(null);

        /** True cuando el mini-modal de "Configurar ruta" esta abierto. */
        const showPathModal = ref(false);

        /**
         * Buffer del input dentro del modal. Se inicializa con la
         * ruta actual al abrir el modal (el ``@click`` lo carga
         * justo antes de abrir).
         */
        const pathEditBuffer = ref("");

        // -----------------------------------------------------------------
        // Computed (expuestos al template via el return del setup).
        // -----------------------------------------------------------------

        /**
         * Plantilla actualmente seleccionada (objeto entero), o
         * ``null`` si el operario no ha elegido ninguna. Recalculado
         * reactivamente cuando cambia ``selectedPlantillaCarpeta``
         * o ``plantillas``.
         */
        const selectedPlantilla = computed(
            () => plantillas.value.find(
                (p) => p.carpeta === selectedPlantillaCarpeta.value
            ) || null
        );

        /**
         * Valida que el formulario este completo y sea consistente.
         * ``false`` si: no hay plantilla, ``base_nueva`` no es
         * entero positivo, ``codigo_nuevo`` o ``nombre_nuevo``
         * vacios, o algun N_MAX no es entero >= 0.
         */
        const formOk = computed(() => {
            if (!selectedPlantilla.value) return false;
            const f = form.value;
            if (!Number.isFinite(f.base_nueva) || f.base_nueva <= 0) return false;
            if (!f.codigo_nuevo.trim()) return false;
            if (!f.nombre_nuevo.trim()) return false;
            const m = f.minimos_usuario;
            const campos = ["N_MAX_PREAL", "N_MAX_PINT", "N_MAX_ALM", "N_MAX_ALM_HMI"];
            for (const k of campos) {
                const v = m[k];
                if (!Number.isFinite(v) || v < 0) return false;
            }
            return true;
        });

        /**
         * Habilita el boton "Aplicar al PLC": hay preview, no hay
         * colisiones (el backend abortara si las hay) y no estamos
         * ya aplicando.
         */
        const aplicacionBotonDisabled = computed(
            () => !previewData.value
                || previewData.value.colisiones.length > 0
                || aplicacionEstado.value === "aplicando"
        );

        // -----------------------------------------------------------------
        // Acciones (async handlers).
        // -----------------------------------------------------------------

        /**
         * GET /api/v1/procesos/plantillas. Carga la lista de
         * plantillas + warning + path actual en el estado local.
         */
        async function loadPlantillas() {
            plantillasLoading.value = true;
            plantillasWarning.value = null;
            const r = await apiListPlantillas();
            plantillasLoading.value = false;
            if (r && r.ok && r.data) {
                plantillas.value = r.data.plantillas || [];
                plantillasWarning.value = r.data.warning || null;
                plantillasPathActual.value = r.data.plantillas_path || "";
            } else {
                plantillas.value = [];
                plantillasWarning.value =
                    (r && r.data && r.data.warning) ||
                    `Error ${r ? r.status : "?"}`;
            }
        }

        /**
         * PUT /api/v1/procesos/plantillas. Persiste el nuevo path
         * en ``config.json`` (backend) y recarga la lista.
         */
        async function guardarPath() {
            const newPath = pathEditBuffer.value.trim();
            if (!newPath) return;
            const r = await apiUpdatePlantillasPath(newPath);
            if (r && r.ok) {
                plantillasPathActual.value = newPath;
                showPathModal.value = false;
                await loadPlantillas();
            } else {
                aplicacionError.value = `No se pudo guardar: ${
                    (r && r.data && r.data.error) || (r ? r.status : "?")
                }`;
            }
        }

        /**
         * POST /api/v1/procesos/crear/preview. Construye los
         * params a partir del estado local y pinta el resultado en
         * ``previewData``. Limpia errores previos para no mostrar
         * feedback stale.
         */
        async function generarPreview() {
            if (!formOk.value) return;
            aplicacionEstado.value = "";
            aplicacionError.value = null;
            previewData.value = null;
            const params = {
                plantillas_path: plantillasPathActual.value,
                dir_plantilla_nombre: selectedPlantillaCarpeta.value,
                base_nueva: form.value.base_nueva,
                codigo_nuevo: form.value.codigo_nuevo,
                nombre_nuevo: form.value.nombre_nuevo,
                minimos_usuario: { ...form.value.minimos_usuario },
                plc_blocks_cache: null,
            };
            const r = await apiProcesosCrearPreview(params);
            if (r && r.ok && r.data && r.data.result) {
                previewData.value = r.data.result;
            } else {
                aplicacionError.value = `Preview fallo: ${
                    (r && r.data && r.data.error) || (r ? r.status : "?")
                }`;
            }
        }

        /**
         * POST /api/v1/procesos/crear/aplicar. Dispara el commit
         * transaccional en el PLC activo. Mismo ``params`` que
         * ``generarPreview`` (el backend re-deriva el plan desde
         * la plantilla + el form).
         */
        async function aplicar() {
            if (aplicacionBotonDisabled.value) return;
            aplicacionEstado.value = "aplicando";
            aplicacionError.value = null;
            const params = {
                plantillas_path: plantillasPathActual.value,
                dir_plantilla_nombre: selectedPlantillaCarpeta.value,
                base_nueva: form.value.base_nueva,
                codigo_nuevo: form.value.codigo_nuevo,
                nombre_nuevo: form.value.nombre_nuevo,
                minimos_usuario: { ...form.value.minimos_usuario },
                plc_blocks_cache: null,
            };
            const r = await apiProcesosCrearAplicar(params);
            aplicacionEstado.value = (r && r.ok) ? "ok" : "error";
            if (!(r && r.ok)) {
                aplicacionError.value = `Apply fallo: ${
                    (r && r.data && (r.data.error || r.data.detail))
                    || (r ? r.status : "?")
                }`;
            }
        }

        // -----------------------------------------------------------------
        // Ciclo de vida.
        // -----------------------------------------------------------------

        // Carga inicial de plantillas al montar. Si el operario
        // cambia el path desde el modal, ``guardarPath`` llama a
        // ``loadPlantillas`` otra vez.
        loadPlantillas();

        // -----------------------------------------------------------------
        // Return: TODO lo que el template debe leer o invocar.
        // (Vue 3 sin build step NO expone imports al scope del
        // template; hay que devolver explicitamente refs/computeds/
        // funciones del setup.)
        // -----------------------------------------------------------------
        return {
            store,
            plantillas,
            plantillasLoading,
            plantillasWarning,
            plantillasPathActual,
            selectedPlantillaCarpeta,
            selectedPlantilla,
            form,
            previewData,
            aplicacionEstado,
            aplicacionError,
            showPathModal,
            pathEditBuffer,
            formOk,
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
                    <h2 class="text-lg font-bold text-ink">🏗️ Crear proceso completo desde plantilla</h2>
                    <p class="text-xs text-ink-muted mt-0.5">
                        Clona una plantilla TIA (tags + DBs + bloques) y la aplica al PLC activo.
                    </p>
                </div>
                <button @click="cerrar"
                        data-testid="procesos-crear-close"
                        class="bg-surface border border-line rounded px-3 py-1 text-xs text-ink hover:bg-surface-sunken">
                    Cerrar
                </button>
            </header>

            <!-- Bloque "ruta de plantillas": boton para abrir el
                 mini-modal + texto con la ruta actual (o warning
                 si esta vacia). -->
            <div class="flex items-center gap-2">
                <button @click="showPathModal = true; pathEditBuffer = plantillasPathActual"
                        data-testid="procesos-crear-configure-path"
                        class="bg-surface border border-line rounded px-3 py-1 text-xs text-ink hover:bg-surface-sunken">
                    📁 Configurar ruta de plantillas
                </button>
                <span v-if="plantillasPathActual" class="text-xs text-ink-muted">
                    ({{ plantillasPathActual }})
                </span>
                <span v-else class="text-xs text-amber-700">
                    (ruta no configurada)
                </span>
            </div>

            <!-- Mini-modal inline para editar la ruta. NO es un
                 overlay: vive dentro del propio bloque, plegable.
                 Coherente con la regla "sub-view inline NO usa
                 position: fixed / overlay". -->
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

            <!-- Warning del backend (ruta vacia, dir no existe, etc). -->
            <div v-if="plantillasWarning"
                 data-testid="procesos-crear-warning"
                 class="text-amber-700 text-xs mt-2">
                ⚠ {{ plantillasWarning }}
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

            <!-- Formulario: solo se monta cuando hay plantilla
                 seleccionada. 2 columnas. Inputs controlados con
                 'v-model.number' para los numericos. -->
            <form v-if="selectedPlantilla"
                  data-testid="procesos-crear-form"
                  class="mt-3 grid grid-cols-2 gap-2"
                  @submit.prevent>
                <label class="flex flex-col text-xs font-semibold text-ink-muted">
                    NUEVA_BASE
                    <input v-model.number="form.base_nueva"
                           type="number" min="10000"
                           data-testid="procesos-crear-base"
                           class="mt-1 bg-white border border-line rounded px-2 py-1 text-sm font-mono focus:border-accent focus:outline-none" />
                </label>
                <label class="flex flex-col text-xs font-semibold text-ink-muted">
                    NUEVO_CODIGO
                    <input v-model="form.codigo_nuevo"
                           maxlength="16"
                           data-testid="procesos-crear-codigo"
                           class="mt-1 bg-white border border-line rounded px-2 py-1 text-sm font-mono focus:border-accent focus:outline-none" />
                </label>
                <label class="col-span-2 flex flex-col text-xs font-semibold text-ink-muted">
                    NUEVO_NOMBRE
                    <input v-model="form.nombre_nuevo"
                           data-testid="procesos-crear-nombre"
                           class="mt-1 bg-white border border-line rounded px-2 py-1 text-sm focus:border-accent focus:outline-none" />
                </label>
                <label class="flex flex-col text-xs font-semibold text-ink-muted">
                    N_MAX_PREAL
                    <input v-model.number="form.minimos_usuario.N_MAX_PREAL"
                           type="number" min="0"
                           class="mt-1 bg-white border border-line rounded px-2 py-1 text-sm font-mono focus:border-accent focus:outline-none" />
                </label>
                <label class="flex flex-col text-xs font-semibold text-ink-muted">
                    N_MAX_PINT
                    <input v-model.number="form.minimos_usuario.N_MAX_PINT"
                           type="number" min="0"
                           class="mt-1 bg-white border border-line rounded px-2 py-1 text-sm font-mono focus:border-accent focus:outline-none" />
                </label>
                <label class="flex flex-col text-xs font-semibold text-ink-muted">
                    N_MAX_ALM
                    <input v-model.number="form.minimos_usuario.N_MAX_ALM"
                           type="number" min="0"
                           class="mt-1 bg-white border border-line rounded px-2 py-1 text-sm font-mono focus:border-accent focus:outline-none" />
                </label>
                <label class="flex flex-col text-xs font-semibold text-ink-muted">
                    N_MAX_ALM_HMI
                    <input v-model.number="form.minimos_usuario.N_MAX_ALM_HMI"
                           type="number" min="0"
                           class="mt-1 bg-white border border-line rounded px-2 py-1 text-sm font-mono focus:border-accent focus:outline-none" />
                </label>
                <button type="button"
                        :disabled="!formOk"
                        @click="generarPreview"
                        data-testid="procesos-crear-preview"
                        class="col-span-2 bg-accent text-ink-inverse rounded px-3 py-1.5 text-xs font-semibold hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed">
                    Generar prevision
                </button>
            </form>

            <!-- Bloque preview: solo se muestra si hay respuesta del
                 backend. Tabla de archivos previstos + banner de
                 colisiones + boton Aplicar. -->
            <div v-if="previewData"
                 data-testid="procesos-crear-preview-block"
                 class="mt-3">
                <h3 class="text-sm font-semibold text-ink mb-2">
                    Archivos a generar ({{ previewData.archivos_previstos.length }})
                </h3>
                <p v-if="previewData.colisiones.length"
                   data-testid="procesos-crear-colisiones"
                   class="text-red-700 text-xs mb-2">
                    ⚠ {{ previewData.colisiones.length }} colision(es) detectada(s). Resuelvelas antes de aplicar.
                </p>
                <div class="overflow-x-auto bg-surface-sunken border border-line rounded">
                    <table class="w-full text-left">
                        <thead class="bg-surface">
                            <tr class="text-xs text-ink-muted uppercase">
                                <th class="px-2 py-1">Original</th>
                                <th class="px-2 py-1">Nuevo</th>
                                <th class="px-2 py-1">Tipo</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="a in previewData.archivos_previstos"
                                :key="a.rel_in"
                                :class="a.colisiona ? 'text-red-700' : 'text-ink'"
                                class="border-t border-line">
                                <td class="px-2 py-1 font-mono text-xs">{{ a.rel_in }}</td>
                                <td class="px-2 py-1 font-mono text-xs">{{ a.rel_out }}</td>
                                <td class="px-2 py-1 text-xs">{{ a.kind }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <button :disabled="aplicacionBotonDisabled"
                        @click="aplicar"
                        data-testid="procesos-crear-aplicar"
                        class="mt-3 bg-accent text-ink-inverse rounded px-3 py-1.5 text-xs font-semibold hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed">
                    {{ aplicacionEstado === "aplicando" ? "Aplicando..." : "Aplicar al PLC" }}
                </button>
                <p v-if="aplicacionEstado === 'ok'"
                   data-testid="procesos-crear-ok"
                   class="text-green-700 text-xs mt-2">
                    Proceso creado OK.
                </p>
                <p v-if="aplicacionEstado === 'error' && aplicacionError"
                   data-testid="procesos-crear-error"
                   class="text-red-700 text-xs mt-2">
                    {{ aplicacionError }}
                </p>
            </div>

        </section>
    `,
};
