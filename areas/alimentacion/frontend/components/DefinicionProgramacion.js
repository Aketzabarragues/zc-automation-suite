/**
 * Componente DefinicionProgramacion.
 *
 * Vista "shell" de la pestaña **Definición programación**. Se compone
 * de sub-componentes para resolver el rediseño de tabs principales.
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
 * Los datos del Excel viven en
 * ``store.appCache.areas["alimentacion"].excel_full`` (hidratado
 * por SSE ``cache_snapshot`` + ``cache_changed``). El ``@event
 * refresh`` se conserva por compat con el template del shell pero
 * ya NO dispara una llamada HTTP: el backend empuja el cache via
 * SSE al subir el archivo.
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
import { store, waitForFbJob } from "/js/store.js";
import { apiUploadExcel } from "/js/api.js";

export default {
    name: "DefinicionProgramacion",
    emits: ["refresh"],
    setup(_, { emit }) {
        const fileInput = ref(null);
        // Estado local UI: el nombre del ultimo archivo Excel
        // subido por el operario (referencia browser-side, efimera).
        // El backend ya cachea el archivo en
        // ``store.appCache.areas["alimentacion"].excel_full`` con
        // su ``source_filename``; aqui solo guardamos el ``File``
        // para que el boton "Volver a seleccionar" funcione
        // (reset del input + re-trigger del picker).
        const lastFileName = ref(null);

        /**
         * ``excel_full`` reactivo desde el AppCache del area activa
         * (``store.appCache.areas["alimentacion"].excel_full``,
         * hidratado por SSE ``cache_snapshot`` al conectar +
         * ``cache_changed`` en cada ``excel_set_full`` del backend).
         */
        const excelFull = computed(
            () => store.appCache?.areas?.alimentacion?.excel_full || null
        );

        /**
         * Conteos para los badges de los 4 tabs principales.
         * Se recalculan reactivamente al cambiar ``excel_full``
         * (subida de Excel, refresco SSE, etc.).
         */
        const dispositivosCount = computed(() => {
            const d = excelFull.value && excelFull.value.dispositivos;
            if (!d || typeof d !== "object") return 0;
            return Object.values(d).reduce(
                (sum, lst) => sum + (Array.isArray(lst) ? lst.length : 0),
                0
            );
        });

        const procesosCount = computed(() => {
            const ms = excelFull.value;
            if (!ms) return 0;
            const n = (Array.isArray(ms.procesos) ? ms.procesos.length : 0)
                + (Array.isArray(ms.parametros_int) ? ms.parametros_int.length : 0)
                + (Array.isArray(ms.parametros_real) ? ms.parametros_real.length : 0)
                + (Array.isArray(ms.alarmas) ? ms.alarmas.length : 0);
            return n;
        });

        /**
         * Conteo de entidades del feature ENTIDADES. Se computa
         * reactivamente al cambiar ``excel_full`` (subida de Excel,
         * refresco, etc.). Si el Excel no tiene hoja ENTIDADES,
         * devuelve 0.
         */
        const entidadesCount = computed(() => {
            const ms = excelFull.value;
            if (!ms) return 0;
            const lst = ms.entidades;
            return Array.isArray(lst) ? lst.length : 0;
        });

        /**
         * ``true`` solo cuando hay Excel cargado (``excel_full`` no
         * nulo). Mismo patron que ``DispositivosPanel`` y
         * ``ProcesosPanel``: sin datos, los tabs ``<main-tabs>`` se
         * ocultan y solo se ve el "La cache del excel esta vacia"
         * del panel activo.
         */
        const hasMemory = computed(() => excelFull.value != null);

        /**
         * Datos que se pasan al ``<main-tabs>``. Se computan
         * aquí (no en MainTabs) para que los conteos reflejen
         * ``excel_full`` sin acoplar MainTabs al shape
         * del dataclass.
         *
         * El tab "Configuracion" muestra la ``Tabla_Dimensiones``
         * del Excel con shape multi-PLC (una fila por PLC).
         */
        const configuracionCount = computed(() => {
            const d = excelFull.value && excelFull.value.n_max;
            if (!d || typeof d !== "object") return 0;
            return Object.keys(d).length;
        });

        const mainTabsData = computed(() => [
            {
                key: "configuracion",
                label: "Configuracion",
                icon: "⚙",
                badge: configuracionCount.value,
            },
            {
                key: "dispositivos",
                label: "Dispositivos",
                icon: "📟",
                badge: dispositivosCount.value,
            },
            {
                key: "procesos",
                label: "Procesos",
                icon: "📋",
                badge: procesosCount.value,
            },
            {
                key: "entidades",
                label: "Entidades",
                icon: "🗂️",
                badge: entidadesCount.value,
            },
        ]);

        /**
         * Sube el .xlsm al backend. Si OK, el backend reescribe
         * ``excel_full`` en el AppCache y emite SSE
         * ``cache_changed`` (slot="excel_full", area=alimentacion).
         * La reactividad de ``excelFull`` (computed) propaga el
         * cambio a las cards de N_MAX y la tabla sin que el
         * usuario tenga que pulsar "Actualizar".
         *
         * El router no bloquea: devuelve 202 con el ``job_id`` del
         * trabajo encolado en el OB1. El resultado llega por SSE
         * (evento ``fb_state``), asi que aqui esperamos al terminal
         * del FB ``subir_excel`` para distinguir exito de error.
         */
        async function handleExcel(ev) {
            const file = ev.target.files && ev.target.files[0];
            if (!file) return;
            store.busy = true;
            try {
                const r = await apiUploadExcel(file);
                if (r && r.ok && r.data && r.data.job_id) {
                    // El Excel ya viaja al AppCache (``excel_full``),
                    // asi que la vista se refresca sola por SSE.
                    // Aqui solo esperamos al terminal del trabajo.
                    let st = null;
                    try {
                        st = await waitForFbJob(r.data.job_id, "subir_excel");
                    } catch (e) {
                        st = {
                            error_msg: String(
                                e && e.message ? e.message : e
                            ),
                        };
                    }
                    if (st.error_msg) {
                        alert("Error cargando Excel: " + st.error_msg);
                    } else {
                        lastFileName.value = file.name;
                    }
                } else {
                    alert(
                        "Error cargando Excel: " +
                        ((r && r.data && (r.data.error || r.data.detail)) ||
                            (r ? r.status : "?"))
                    );
                }
            } finally {
                store.busy = false;
                if (fileInput.value) fileInput.value.value = "";
            }
        }

        /**
         * "Volver a seleccionar" el Excel: abre el file picker
         * para que el operario re-seleccione el archivo (con sus
         * cambios en disco). El ``@change`` del input dispara
         * ``handleExcel``, que sube el archivo via
         * ``apiUploadExcel`` (mismo flujo que la primera carga).
         *
         * Por que esto y no un "reload" que re-lea desde la ruta
         * del archivo original: los navegadores NO exponen la ruta
         * completa del archivo original (restriccion W3C de
         * seguridad: el File API solo expone basename, size y tipo).
         * Por tanto, no podemos re-leer el archivo del operario
         * desde disco sin su intervencion. La unica forma honesta
         * de "refrescar" es pedirle que re-seleccione, asi que el
         * boton hace exactamente eso.
         *
         * Si no hay ``lastFileName`` (operario acaba de arrancar
         * o cambio de area), pedimos al padre que emita el evento
         * ``refresh`` (compat con el contrato del componente).
         */
        function handleActualizar() {
            if (!lastFileName.value) {
                emit("refresh");
                return;
            }
            // Reset del input para que el @change se dispare aunque
            // el operario re-seleccione el MISMO archivo (los
            // inputs nativos ignoran el evento change si el valor
            // no cambia entre selecciones).
            if (fileInput.value) {
                fileInput.value.value = "";
                fileInput.value.click();
            }
        }

        return {
            store,
            fileInput,
            excelFull,
            hasMemory,
            mainTabsData,
            handleExcel,
            handleActualizar,
            entidadesCount,
            lastFileName,
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
                    <button @click="handleActualizar" :disabled="store.busy"
                        data-testid="def-programacion-actualizar"
                        class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                        🔄 Volver a seleccionar
                    </button>
                </div>
                <div v-if="excelFull" class="mt-2 text-xs text-ink-muted">
                    <div class="text-accent">✅ Excel cargado</div>
                </div>
                <div v-if="lastFileName" class="mt-2 text-xs text-ink-muted">
                    <div class="text-ink-muted">📎 Último archivo: <span class="font-mono text-ink">{{ lastFileName }}</span></div>
                </div>
            </section>

            <!-- ★ Tabs principales + Panel activo (segundo card: engloba
                 tanto el strip Dispositivos|Procesos como el panel
                 reactivo de la pestaña activa). El operario pidió que
                 TODA la información de la tabla viviera dentro de un
                 único card, así que el strip sube al card.

                 El strip <main-tabs> se oculta cuando !hasMemory
                 (mismo patron que los sub-tabs de DispositivosPanel/
                 ProcesosPanel y los tabs de BloquesCacheView): sin
                 datos cargados no tiene sentido mostrar navegacion
                 entre sub-vistas, solo el empty state del panel
                 activo. Cuando el operario carga un Excel, los tabs
                 aparecen y puede alternar Dispositivos/Procesos. ★ -->
            <section class="flex-1 mt-2 mb-4 bg-surface-raised border border-line rounded p-4 flex flex-col overflow-hidden"
                     data-testid="def-programacion-card-tablas">
                <main-tabs v-if="hasMemory" :tabs="mainTabsData" />
                <div class="flex-1 mt-3 flex flex-col overflow-hidden">
                    <configuracion-panel v-if="store.activeMainTab === 'configuracion'" />
                    <dispositivos-panel v-else-if="store.activeMainTab === 'dispositivos'" />
                    <procesos-panel v-else-if="store.activeMainTab === 'procesos'" />
                    <entidades-panel v-else-if="store.activeMainTab === 'entidades'" />
                    <procesos-panel v-else />
                </div>
            </section>

        </section>
    `,
};
