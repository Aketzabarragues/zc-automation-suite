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

        // Mapeo filas de la tabla N_MAX <-> claves del manifest. Solo
        // las 4 N_MAX canonicasson las que disparan bloqueo; UID y
        // CODIGO no tienen minimo que cubrir.
        const N_MAX_KEYS_BY_ROW = {
            PREAL: "N_MAX_PREAL",
            PINT: "N_MAX_PINT",
            ALM: "N_MAX_ALM",
            ALM_HMI: "N_MAX_ALM_HMI",
        };

        // Lista las filas que NO cumplen los minimos (N_MAX del
        // proceso del Excel < minimo de la plantilla). Usado para
        // pintar la celda en rojo y para el tooltip del boton.
        const minimosProblemas = computed(() => {
            const pl = selectedPlantilla.value;
            const proc = procesoExcel.value;
            if (!pl || !proc) return [];
            const min = pl.minimos || {};
            const problemas = [];
            for (const [rowKey, manifestKey] of Object.entries(N_MAX_KEYS_BY_ROW)) {
                const plantillaVal = Number(min[manifestKey] ?? 0);
                const usuarioVal = Number(proc[_excelFieldForRow(rowKey)] ?? 0);
                if (usuarioVal < plantillaVal) {
                    problemas.push({
                        row: rowKey,
                        manifestKey,
                        plantilla: plantillaVal,
                        usuario: usuarioVal,
                    });
                }
            }
            return problemas;
        });
        function _excelFieldForRow(rowKey) {
            // Campo del proceso del Excel que corresponde a la fila
            // de la tabla N_MAX. Coincide con el orden de las
            // columnas de ``procesoExcel`` (parser del Excel del
            // operario).
            return {
                PREAL: "preal",
                PINT: "pint",
                ALM: "alarmas",
                ALM_HMI: "alm_hmi",
            }[rowKey];
        }

        // ``true`` cuando las 4 N_MAX del proceso del Excel cubren
        // los minimos de la plantilla. UID/CODIGO no se chequean
        // (no tienen minimo).
        const minimosCumplidos = computed(() => minimosProblemas.value.length === 0);

        // Botón "Generar prevision": plantilla + Excel/proceso + PLC
        // con cache de bloques + N_MAX cumplidos + no estar
        // aplicandose. Mismo requisito de cache de bloques que el
        // sync de comentarios: sin esa cache no podemos calcular el
        // ESTADO de cada bloque previsto, asi que mejor bloquear que
        // avisar a medias.
        const canGenerate = computed(
            () =>
                Boolean(selectedPlantilla.value) &&
                hayExcel.value &&
                hasPlcBlocks.value &&
                minimosCumplidos.value &&
                aplicacionEstado.value !== "aplicando"
        );

        // Tooltip accionable cuando la card esta deshabilitada por
        // faltar PLC, cache de bloques o N_MAX que no cubren los
        // minimos. Misma estructura que ``syncCardTooltip`` del
        // padre ``Procesos.js``.
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
            const problemas = minimosProblemas.value;
            if (problemas.length) {
                const lista = problemas
                    .map((p) => `${p.row}: ${p.usuario} < ${p.plantilla}`)
                    .join(", ");
                return `Los N_MAX del proceso no cubren los minimos de la plantilla (${lista}). Cambia el proceso o la plantilla.`;
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
                // Cache de bloques del PLC: el backend la usa para
                // detectar colisiones reales en ``detectar_colisiones``
                // y poblar ``archivos_previstos[i].colisiona``. Si
                // no se envia, el FB solo detecta 1 colision
                // genérica "cache no inicializado" y todas las filas
                // quedan OK en la SPA (falso positivo de OK).
                plc_blocks_cache: _blocksToNames(plcBlocksCache.value),
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
                plc_blocks_cache: _blocksToNames(plcBlocksCache.value),
            };
            const r = await apiProcesosCrearAplicar(params);
            aplicacionEstado.value = r && r.ok ? "ok" : "error";
            if (!r || !r.ok) {
                aplicacionError.value =
                    "Apply fallo: " +
                    ((r && r.data && r.data.error) || (r ? r.status : "?"));
            }
        }

        // Pasa la lista de bloques del PLC del store al formato
        // ``list[dict{ nombre, numero, tipo }]`` que espera el router
        // backend (commit 11b). El router deriva sets separados por
        // tipo, asi el backend puede detectar colisiones por nombre O
        // por (tipo + numero). TIA Portal distingue bloques por
        // tipo+numero (DB60010 vs FB60010 NO chocan entre si).
        //
        // Acepta tanto ``b.tipo`` como ``b.type`` del scanner.
        // Si el bloque no trae tipo (comun en scanners antiguos
        // que solo emiten nombre+numero), lo emitimos sin tipo
        // -> el backend lo trata como match por nombre solo.
        //
        // Si el cache esta vacio o el PLC no esta seleccionado,
        // devuelve array vacio (defensivo: ``canGenerate`` ya
        // filtra este caso).
        function _blocksToNames(cache) {
            if (!cache || !Array.isArray(cache.blocks)) return [];
            return cache.blocks
                .map((b) => {
                    if (!b) return null;
                    const nombre = b.nombre || b.name;
                    if (!nombre) return null;
                    const out = { nombre };
                    const numero = b.numero != null
                        ? Number(b.numero)
                        : (b.number != null ? Number(b.number) : null);
                    if (numero != null && !Number.isNaN(numero)) {
                        out.numero = numero;
                    }
                    const tipoRaw = b.tipo || b.type;
                    if (tipoRaw && typeof tipoRaw === "string") {
                        out.tipo = tipoRaw.toUpperCase().trim();
                    }
                    return out;
                })
                .filter(Boolean);
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
        //
        // Cada fila de N_MAX lleva ``cumple: boolean`` que indica
        // si el proceso del Excel cubre el minimo de la plantilla.
        // El template pinta el valor en rojo si !cumple. Las filas
        // UID/CODIGO no aplican (no tienen minimo).
        const nmaxRows = computed(() => {
            const pl = selectedPlantilla.value;
            const proc = procesoExcel.value;
            const min = (pl && pl.minimos) || {};
            const problemas = new Set(
                minimosProblemas.value.map((p) => p.row)
            );
            return [
                {
                    dato: "PREAL",
                    plantilla: min.N_MAX_PREAL ?? "-",
                    nuevo: proc ? proc.preal : "-",
                    cumple: !problemas.has("PREAL"),
                },
                {
                    dato: "PINT",
                    plantilla: min.N_MAX_PINT ?? "-",
                    nuevo: proc ? proc.pint : "-",
                    cumple: !problemas.has("PINT"),
                },
                {
                    dato: "ALM",
                    plantilla: min.N_MAX_ALM ?? "-",
                    nuevo: proc ? proc.alarmas : "-",
                    cumple: !problemas.has("ALM"),
                },
                {
                    dato: "ALM_HMI",
                    plantilla: min.N_MAX_ALM_HMI ?? "-",
                    nuevo: proc ? proc.alm_hmi : "-",
                    cumple: !problemas.has("ALM_HMI"),
                },
                {
                    dato: "UID",
                    plantilla: pl ? pl.base : "-",
                    nuevo: proc ? proc.uid : "-",
                    cumple: true,
                },
                {
                    dato: "CODIGO",
                    plantilla: pl ? pl.codigo : "-",
                    nuevo: proc ? proc.codigo : "-",
                    cumple: true,
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

        // Filas de la tabla de bloques previstos. Single source of
        // truth: el backend ya marca ``archivos_previstos[i].colisiona``
        // cruzando ``dicc_bloques`` (preview lado servidor) contra la
        // cache de bloques del PLC que la SPA envia en
        // ``plc_blocks_cache`` (commit 6). Replicar el cruce aqui
        // duplicaba logica y daba falsos positivos (todo OK) cuando
        // la SPA no enviaba la cache.
        // Orden estable: por nombre nuevo ascendente (locale-aware).
        const bloquesConEstado = computed(() => {
            const data = previewData.value;
            if (!data || !Array.isArray(data.archivos_previstos)) return [];
            const rows = data.archivos_previstos
                .filter((a) => a && a.rel_in !== undefined && a.rel_out !== undefined)
                .map((a) => {
                    // El backend ya devuelve nombre_original,
                    // nombre_nuevo, numero_original, numero_nuevo
                    // y tipo_original / tipo_nuevo (DB/FC/FB/...)
                    // extraidos del ``S7_BlockNumber := "X"`` del
                    // XML de plantilla y del prefijo del stem.
                    // Mostramos todo en columnas separadas: el
                    // operario ve de un vistazo
                    //   TIPO | BLOQUE ORIGINAL | BLOQUE NUEVO
                    //   DB   | DB50010_X - 50010 | DB60010_Y - 60010
                    const tipoOrig = a.tipo_original || "";
                    const tipoNuevo = a.tipo_nuevo || "";
                    const nombreOrig = a.nombre_original || _pathStem(a.rel_in);
                    const nombreNuevo = a.nombre_nuevo || _pathStem(a.rel_out);
                    const numeroOrig = a.numero_original || 0;
                    const numeroNuevo = a.numero_nuevo || 0;
                    return {
                        tipo: tipoNuevo || tipoOrig,
                        original: numeroOrig > 0
                            ? `${nombreOrig} - ${numeroOrig}`
                            : nombreOrig,
                        nuevo: numeroNuevo > 0
                            ? `${nombreNuevo} - ${numeroNuevo}`
                            : nombreNuevo,
                        estado: a.colisiona ? "NO OK" : "OK",
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
            minimosCumplidos,
            minimosProblemas,
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
                            class="border-b border-line"
                            :class="!row.cumple ? 'bg-red-50' : ''">
                            <td class="px-3 py-1.5 align-top text-ink font-semibold">
                                {{ row.dato }}
                            </td>
                            <td class="px-3 py-1.5 align-top text-ink font-mono">
                                {{ row.plantilla }}
                            </td>
                            <td class="px-3 py-1.5 align-top text-ink font-mono"
                                :class="!row.cumple ? 'text-red-700 font-bold' : ''">
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
                    class="mt-4 px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                <span>🔍</span>
                <span>Generar Previsión</span>
            </button>

            <div v-if="previewData" class="mt-4">
                <h3 class="text-sm font-semibold text-ink mb-2">
                    Archivos a generar ({{ bloquesConEstado.length }})
                </h3>
                <div v-if="Array.isArray(previewData.colisiones) && previewData.colisiones.length"
                     class="bg-red-50 border border-red-300 rounded p-2 mb-2 text-xs text-red-800">
                    <p class="font-semibold mb-1">
                        Aviso: {{ previewData.colisiones.length }} colision(es) detectada(s) con bloques ya existentes en el PLC.
                    </p>
                    <ul class="list-disc list-inside font-mono">
                        <li v-for="c in previewData.colisiones" :key="c">
                            {{ c }}
                        </li>
                    </ul>
                    <p class="mt-1 text-red-700">
                        Cambia el proceso o plantilla para evitar pisar bloques existentes.
                    </p>
                </div>
                <!-- Tabla TIPO / BLOQUE ORIGINAL / BLOQUE NUEVO / ESTADO.
                     Columnas por tipo explicito (DB/FC/FB/...) porque
                     TIA Portal distingue bloques por (tipo + numero),
                     asi que DB60010 y FB60010 ocupan slots distintos.
                     ESTADO = OK si el bloque nuevo NO choca por nombre
                     O por (tipo + numero) con la cache del PLC; NO OK
                     en caso contrario. La cache del PLC se carga desde
                     el sidebar; si el operario ve "?" deberia
                     recargar el PLC. -->
                <div class="flex-1 overflow-auto table-scroll-x bg-surface-raised border border-line rounded">
                    <table class="w-full text-xs">
                        <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                            <tr>
                                <th class="px-3 py-2 text-left text-ink-muted">TIPO</th>
                                <th class="px-3 py-2 text-left text-ink-muted">BLOQUE ORIGINAL</th>
                                <th class="px-3 py-2 text-left text-ink-muted">BLOQUE NUEVO</th>
                                <th class="px-3 py-2 text-left text-ink-muted">ESTADO</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="row in bloquesConEstado"
                                :key="row.original + '|' + row.nuevo"
                                class="border-b border-line">
                                <td class="px-3 py-1.5 align-top font-mono font-bold text-accent whitespace-nowrap">
                                    {{ row.tipo }}
                                </td>
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
                                <td colspan="4"
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
                        class="mt-3 w-full py-3 text-accent font-semibold text-sm bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    <span v-if="aplicacionEstado === 'aplicando'">⏳ Aplicando…</span>
                    <span v-else>✅ Aplicar Cambios en TIA Portal</span>
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
