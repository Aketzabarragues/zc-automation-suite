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

        // Cache de bloques del PLC activo (``store.plcBlocksCache``).
        // Lo necesitamos para calcular el ESTADO de cada bloque
        // previsto (NO OK si el nombre+numero ya existen en el PLC).
        const plcBlocksCache = computed(
            () => store.plcBlocksCache || null
        );
        const hasPlcBlocks = computed(() => {
            const c = plcBlocksCache.value;
            return Boolean(c) && Array.isArray(c.blocks) && c.blocks.length > 0;
        });

        // Botón "Generar prevision": plantilla + Excel/proceso + PLC
        // con cache de bloques + no estar aplicándose. Mismo
        // requisito de cache de bloques que el sync de comentarios:
        // sin esa cache no podemos calcular el ESTADO de cada bloque
        // previsto, asi que mejor bloquear que avisar a medias.
        const canGenerate = computed(
            () =>
                Boolean(selectedPlantilla.value) &&
                hayExcel.value &&
                hasPlcBlocks.value &&
                aplicacionEstado.value !== "aplicando"
        );

        // Tooltip accionable cuando la card esta deshabilitada por
        // faltar PLC o cache de bloques. Misma estructura que
        // ``syncCardTooltip`` del padre ``Procesos.js``.
        const crearCardTooltip = computed(() => {
            if (!hayExcel.value) {
                return "Carga primero el Excel y pulsa 'Actualizar' en 'Definicion programacion'.";
            }
            if (!Boolean(selectedPlantilla.value)) {
                return "Selecciona una plantilla.";
            }
            if (!hasPlcBlocks.value) {
                return "Selecciona un PLC en el sidebar y espera al escaneo de bloques.";
            }
            return "";
        });

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

        // Filas de la tabla comparativa N_MAX / UID / CODIGO entre
        // la plantilla seleccionada (manifest) y el proceso del Excel.
        // Reactivo: cambia cuando ``selectedPlantilla`` o
        // ``procesoExcel`` cambian. Si uno de los dos falta, su
        // columna muestra "-" (defensivo: el operario aun no
        // selecciono plantilla o Excel).
        const nmaxRows = computed(() => {
            const pl = selectedPlantilla.value;
            const proc = procesoExcel.value;
            const min = (pl && pl.minimos) || {};
            return [
                {
                    dato: "PREAL",
                    plantilla: min.N_MAX_PREAL ?? "-",
                    nuevo: proc ? proc.preal : "-",
                },
                {
                    dato: "PINT",
                    plantilla: min.N_MAX_PINT ?? "-",
                    nuevo: proc ? proc.pint : "-",
                },
                {
                    dato: "ALM",
                    plantilla: min.N_MAX_ALM ?? "-",
                    nuevo: proc ? proc.alarmas : "-",
                },
                {
                    dato: "ALM_HMI",
                    plantilla: min.N_MAX_ALM_HMI ?? "-",
                    nuevo: proc ? proc.alm_hmi : "-",
                },
                {
                    dato: "UID",
                    plantilla: pl ? pl.base : "-",
                    nuevo: proc ? proc.uid : "-",
                },
                {
                    dato: "CODIGO",
                    plantilla: pl ? pl.codigo : "-",
                    nuevo: proc ? proc.codigo : "-",
                },
            ];
        });

        // ── Helpers para la tabla de bloques ─────────────────────
        // ``pathStem``: ruta completa -> nombre sin extension y sin
        // carpetas. El backend manda ``rel_in`` / ``rel_out`` con
        // subcarpetas (``variables/`` / ``bloques/``) y el
        // ``manifest.json`` ya viene filtrado por el helper.
        function _pathStem(p) {
            if (!p) return "";
            const s = String(p).replace(/\\/g, "/").split("/").pop();
            return s.replace(/\.[^.]+$/, "");
        }
        // ``_blockNumber``: extrae la primera secuencia de digitos
        // del stem ("DB50010_PARAM" -> 50010, "FC50010_INTERFAZ" ->
        // 50010, "manifest" -> 0). Sirve para la comparacion con la
        // cache de bloques del PLC (que guarda ``numero`` aparte).
        function _blockNumber(stem) {
            if (!stem) return 0;
            const m = String(stem).match(/(\d+)/);
            return m ? Number(m[1]) : 0;
        }
        // ``_bloqueExisteEnPLC``: match por nombre (lowercase, sin
        // extension) Y por numero. AND logico: si el PLC tiene el
        // mismo bloque exacto (mismo nombre + mismo numero) -> NO OK
        // (no se podria importar). Solo ``true`` si AMBOS coinciden.
        function _bloqueExisteEnPLC(stemNuevo, plcBlocks) {
            if (!stemNuevo) return false;
            const targetName = String(stemNuevo).toLowerCase();
            const targetNum = _blockNumber(stemNuevo);
            for (const b of plcBlocks) {
                if (!b) continue;
                const name = String(b.nombre || b.name || "").toLowerCase();
                const num = Number(b.numero != null ? b.numero : (b.number != null ? b.number : 0));
                if (name === targetName && num === targetNum) {
                    return true;
                }
            }
            return false;
        }

        // Filas de la tabla de bloques previstos. Cada fila lleva
        // el nombre original (de la plantilla), el nuevo (con
        // prefijo renombrado) y el estado segun la cache del PLC.
        // Orden estable: por nombre nuevo ascendente (locale-aware).
        const bloquesConEstado = computed(() => {
            const data = previewData.value;
            if (!data || !Array.isArray(data.archivos_previstos)) return [];
            const cache = plcBlocksCache.value;
            const plcBlocks = (cache && Array.isArray(cache.blocks)) ? cache.blocks : [];
            const rows = data.archivos_previstos
                .filter((a) => a && a.rel_in !== undefined && a.rel_out !== undefined)
                .map((a) => {
                    const stemIn = _pathStem(a.rel_in);
                    const stemOut = _pathStem(a.rel_out);
                    return {
                        original: stemIn,
                        nuevo: stemOut,
                        estado: _bloqueExisteEnPLC(stemOut, plcBlocks) ? "NO OK" : "OK",
                    };
                });
            rows.sort((a, b) => String(a.nuevo).localeCompare(
                String(b.nuevo), undefined, { sensitivity: "base" }
            ));
            return rows;
        });

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
            nmaxRows,
            plcBlocksCache,
            hasPlcBlocks,
            crearCardTooltip,
            bloquesConEstado,
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

            <!-- Tabla comparativa N_MAX / UID / CODIGO entre la plantilla
                 seleccionada (manifest) y el proceso del Excel. Mismo
                 lenguaje visual que DispositivosPanel/ProcesosPanel
                 (sticky header, container bg-surface-raised + border
                 + rounded). Las 6 filas son estaticas (los nombres de
                 las claves canonicas); los valores son reactivos
                 (computed nmaxRows). Columna "-" si no hay
                 plantilla/proceso seleccionado (defensivo). -->
            <div class="mt-3 flex-1 overflow-auto table-scroll-x bg-surface-raised border border-line rounded">
                <table class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted">DATO</th>
                            <th class="px-3 py-2 text-left text-ink-muted">PLANTILLA</th>
                            <th class="px-3 py-2 text-left text-ink-muted">PROCESO NUEVO</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="row in nmaxRows"
                            :key="row.dato"
                            class="border-b border-line">
                            <td class="px-3 py-1.5 align-top text-ink font-semibold">
                                {{ row.dato }}
                            </td>
                            <td class="px-3 py-1.5 align-top text-ink font-mono">
                                {{ row.plantilla }}
                            </td>
                            <td class="px-3 py-1.5 align-top text-ink font-mono">
                                {{ row.nuevo }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <button type="button"
                    @click="generarPreview"
                    :disabled="!canGenerate"
                    :title="crearCardTooltip"
                    data-testid="procesos-crear-generar-preview"
                    class="mt-4 px-3 py-1.5 bg-accent text-ink-inverse rounded-md text-xs font-semibold hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed">
                Generar prevision
            </button>

            <div v-if="previewData" class="mt-4">
                <h3 class="text-sm font-semibold text-ink mb-2">
                    Archivos a generar ({{ bloquesConEstado.length }})
                </h3>
                <p v-if="Array.isArray(previewData.colisiones) && previewData.colisiones.length"
                   class="text-red-700 text-xs mb-2">
                    Aviso: {{ previewData.colisiones.length }} colision(es) detectada(s). Cambia el proceso o plantilla para evitar pisar bloques existentes en el PLC.
                </p>
                <!-- Tabla BLOQUE ORIGINAL / BLOQUE NUEVO / ESTADO.
                     Mismo lenguaje visual que DispositivosPanel.js
                     (sticky header, container bg-surface-raised +
                     border + rounded). ESTADO = OK si el bloque
                     nuevo NO existe en la cache del PLC activo
                     (por nombre + numero); NO OK si coincide. La
                     cache del PLC se carga desde el sidebar; si
                     el operario ve "?" en la columna deberia
                     recargar el PLC. -->
                <div class="flex-1 overflow-auto table-scroll-x bg-surface-raised border border-line rounded">
                    <table class="w-full text-xs">
                        <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                            <tr>
                                <th class="px-3 py-2 text-left text-ink-muted">BLOQUE ORIGINAL</th>
                                <th class="px-3 py-2 text-left text-ink-muted">BLOQUE NUEVO</th>
                                <th class="px-3 py-2 text-left text-ink-muted">ESTADO</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="row in bloquesConEstado"
                                :key="row.original + '|' + row.nuevo"
                                class="border-b border-line">
                                <td class="px-3 py-1.5 align-top font-mono text-ink whitespace-nowrap">
                                    {{ row.original }}
                                </td>
                                <td class="px-3 py-1.5 align-top font-mono text-ink whitespace-nowrap">
                                    {{ row.nuevo }}
                                </td>
                                <td class="px-3 py-1.5 align-top font-mono font-bold whitespace-nowrap"
                                    :class="row.estado === 'NO OK' ? 'text-red-700' : 'text-green-700'">
                                    {{ row.estado }}
                                </td>
                            </tr>
                            <tr v-if="bloquesConEstado.length === 0">
                                <td colspan="3"
                                    class="px-3 py-6 text-center text-ink-muted italic">
                                    (no hay archivos previstos)
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
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
