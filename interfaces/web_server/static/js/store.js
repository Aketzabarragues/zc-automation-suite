/**
 * Store global reactivo (ESM) compartido por todos los componentes.
 *
 * Implementado con ``reactive`` de Vue 3: cualquier componente que
 * lea ``store.xxx`` desde su ``template`` o ``computed`` se re-renderiza
 * automáticamente cuando otra parte de la app hace ``store.xxx = ...``.
 *
 * NO usamos ningún singleton exportado por fuera de Vue: el estado
 * vive dentro del proxy de ``reactive`` y se accede siempre a través
 * de la referencia ``store``.
 */
import { reactive } from "/js/vendor/vue.esm-browser.prod.js";

export const store = reactive({
    /**
     * Vista de ALTO NIVEL de la SPA. Es la que usa el componente raíz
     * (``main.js``) para decidir si renderiza la pantalla de bienvenida
     * o el layout de área (Sidebar + main + ConsolaLogs).
     *
     * Valores:
     *   ``'welcome'`` → pantalla de selección de área (sin sidebar).
     *   ``'area'``    → dentro de un área (sidebar + main + logs).
     *
     * Se mantiene SEPARADO de ``currentView`` (que es la sub-vista
     * interna del área) para no acoplar el routing de alto nivel
     * con el de las vistas de cada área.
     */
    topLevelView: "welcome",

    /**
     * Sub-vista DENTRO del área activa. Decide qué componente se
     * muestra en ``<main>``. Valores:
     *   ``'landing'`` → ``<AreaLanding>`` (pantalla de aterrizaje con
     *                   tarjetas de las dos sub-vistas).
     *   ``'def'``     → ``<DefinicionProgramacion>`` (antes "Inspector de Memoria").
     *   ``'disp'``    → ``<Dispositivos>`` (antes "Sincronización TIA").
     *
     * El Sidebar y el AreaLanding NO lo modifican directamente:
     * pasan por ``goToSubview(key)`` para mantener la mutación
     * centralizada.
     */
    currentView: "disp",

    /** Área seleccionada por el usuario (``'alimentacion'``). ``null`` en welcome. */
    selectedArea: null,

    /** Catálogo de áreas devuelto por ``GET /api/v1/areas``. */
    availableAreas: [],

    /** Cola FIFO de mensajes para la consola de trazabilidad. */
    logs: [],

    /** Lista de PLCs detectada en TIA Portal. */
    plcs: [],

    /** Nombre del PLC seleccionado en el desplegable. */
    selectedPlc: "",

    /**
     * Propiedades básicas del proyecto TIA activo, devueltas por
     * ``GET /api/v1/portal/project-info``. ``null`` antes de pulsar
     * "Buscar PLCs" por primera vez. Tras un fetch OK tiene al menos
     * ``{ name: "..." }``; el resto de campos es opcional.
     *
     * El ShellTopbar lo muestra como caption encima del desplegable
     * de PLCs para que el operario verifique a qué proyecto está
     * enganchado antes de tocar nada.
     */
    projectInfo: null,

    /** Resumen devuelto por ``POST /api/v1/excel/upload``. */
    uploadSummary: null,

    /**
     * Referencia al último ``File`` Excel subido por el operario.
     * Vive en el store (no como ``ref`` local del componente) para
     * que el caption "📎 Último archivo: ..." y el botón "🔄
     * Actualizar" de ``DefinicionProgramacion.js`` mantengan el
     * contexto cuando el operario navega a otra sub-vista del área
     * y vuelve. Se resetea al cambiar de área (ver ``goToArea`` y
     * el reset equivalente en ``main.js::onAreaSelected``), igual
     * que ``uploadSummary``.
     *
     * NO sobrevive a un F5: un ``File`` no se puede serializar a
     * ``localStorage`` sin perderlo. Si tras un F5 el operario
     * quiere re-leer el archivo, debe volver a seleccionarlo del
     * picker; mientras tanto, el botón "🔄 Actualizar" cae al
     * fallback ``emit("refresh")`` (refresco de memoria sin
     * re-upload).
     */
    lastExcelFile: null,

    /**
     * Estado del ``AppState`` volcado por la API
     * ``GET /api/v1/state/dispositivos``.
     *
     * Shape (estable):
     *   {
     *     ok: true,
     *     dimensiones: { num_disp_ed: int, ... },
     *     dispositivos: { "DispED": [...], ... },
     *     // Nuevos (Fase 6): 4 dominios de software.
     *     // Cada uno es [] si el operario no ha subido Excel.
     *     procesos:             Array<ProcesoPLC>,
     *     parametros_int:       Array<ParamIntPLC>,
     *     parametros_real:      Array<ParamRealPLC>,
     *     alarmas:              Array<AlarmaPLC>,
     *     // Flag: si es false, la SPA pinta banner "Datos de software pendientes".
     *     software_parsers_implemented: boolean,
     *   }
     *
     * El flag ``software_parsers_implemented`` permite a la SPA
     * funcionar en modo degradado (banner ámbar) si el backend aún
     * no trae los 4 nuevos campos (caso back-compat con una versión
     * anterior a Fase 6 del plan canónico).
     */
    memoryState: null,

    /**
     * Previsión de cambios actual generada por
     * ``POST /api/v1/sync/preview``.
     */
    previewData: null,

    /**
     * Catálogo de presentación cargado al arrancar desde
     * ``GET /api/v1/catalog``. Contiene:
     *   - ``device_tabs``   ``[{hw_type, canonical, label}, ...]``
     *   - ``nmax``          ``[{name, label}, ...]``
     *   - ``model_columns`` ``{canonical: [field_name, ...], ...}``
     *   - ``col_labels``    ``{col_name: "Label humano", ...}``
     *   - ``mono_cols``     ``[col_name, ...]``
     *
     * Es la **fuente única de verdad** del frontend: añadir un
     * nuevo tipo de dispositivo o N_MAX al ``config.json`` se
     * refleja automáticamente sin tocar JS.
     */
    catalog: null,

    /** Tab activa del Inspector (canonical: ``'DispED' | 'DispEA' | ...``). */
    activeTab: "",

    /**
     * Tab PRINCIPAL activo en la vista "Definición programación".
     * Decide si se muestra ``<DispositivosPanel>`` o ``<ProcesosPanel>``.
     *
     * Valores:
     *   ``'dispositivos'`` → tabla de dispositivos (sub-tabs
     *                         ED|EA|SA|V|M|MVF). Default.
     *   ``'procesos'``     → dump de Procesos / PInt / PReal / Alarmas
     *                         (sub-tabs del ProcesosPanel).
     *
     * Lo muta ``MainTabs`` al hacer click en uno de los dos botones
     * del strip. Centralizado aquí para que ``DefinicionProgramacion``
     * pueda decidir el panel a pintar leyendo este único flag.
     */
    activeMainTab: "dispositivos",

    /** Flag de operación en curso (deshabilita botones). */
    busy: false,

    /**
     * Estado del progress overlay (espejo reactivo del
     * ``ProgressTracker`` backend). Actualizado por el polling
     * cada 500 ms en ``main.js`` mientras hay una operación activa
     * o un resultado terminal pendiente de leer.
     *
     * Estructura espejo del ``ProgressSnapshot`` del backend
     * (``application/progress_buffer.py``).
     *
     * ``active=false`` + ``stages=[]`` → overlay oculto (idle).
     * ``active=true`` → overlay visible con stages en progreso.
     * ``active=false`` + ``error`` no nulo → overlay rojo 5s.
     * ``active=false`` + ``stages`` no vacíos (sin error) → overlay
     *   verde "Completado" 3s, luego auto-clear.
     */
    progress: {
        active: false,
        operation: null,
        label: null,
        current: 0,
        total: 0,
        percent: 0,
        stages: [],
        started_at: null,
        finished_at: null,
        error: null,
    },

    /**
     * Snapshot cacheado de la estructura del PLC activo
     * (bloques + tag tables + UDTs). Alimentado por el helper
     * unificado ``loadAndApplyPlcBlocks`` desde los endpoints
     * ``GET / POST /api/v1/plcs/<plc>/blocks[/refresh]``.
     *
     * Estructura (defensiva: cualquier campo puede faltar):
     *   {
     *     plc_name:   string,
     *     blocks:     Array<{ name, type, number, path, ... }>,
     *     tag_tables: Array<{ name, path, ... }>,
     *     udts:       Array<{ name, type, number, path, ... }>,
     *     scanned_at: string (ISO timestamp),
     *   }
     *
     * La vista ``BloquesCacheView`` lo consume en modo solo
     * lectura: 3 pestañas (Bloques / Variables / UDT) y un
     * botón "Refrescar" que dispara el helper de refresh.
     *
     * ``null`` antes del primer fetch o cuando el operario
     * deselecciona el PLC.
     *
     * El progreso de la operación larga (escaneo contra TIA)
     * NO vive aquí: lo emite el ``ProgressTracker`` backend
     * y lo pinta el ``ProgressIndicator`` del sidebar. Esta
     * slot es **solo datos**.
     */
    plcBlocksCache: null,

    /**
     * Estado del flujo "Sync comentarios DB de procesos".
     * Consumido por ``ProcesosSyncView.js`` y escrito por los
     * handlers de Procesos.js (openSyncView) y los botones de la
     * propia vista (generar preview / aplicar).
     *
     * Shape:
     *   - ``preview``: ``null`` o el dict devuelto por
     *     ``apiProcesosSyncPreview`` (con ``arrays``, ``summary``,
     *     ``missing_blocks``, etc.).
     *   - ``applying``: ``true`` mientras hay una operación larga
     *     en vuelo (preview o commit). El ``ProgressIndicator``
     *     del sidebar lee su propio tracker, así que este flag es
     *     solo para deshabilitar botones.
     *   - ``error``: ``null`` o mensaje de error accionable.
     *   - ``lastAppliedAt``: ``null`` o ISO timestamp del último
     *     commit exitoso.
     */
    procesosSync: {
        preview: null,
        applying: false,
        error: null,
        lastAppliedAt: null,
    },

    /**
     * Estado de conexión del worker TIA persistente
     * (PR 5b / §4.3 del design doc). Slot espejo del snapshot
     * ``GET /api/v1/tia/connection`` que el backend mantiene en
     * ``TIAProcessGateway._connection_state``.
     *
     * Shape (estable, alineado con el backend, sept-2026
     * state machine):
     *   {
     *     state:              "connected" | "connecting"
     *                        | "idle" | "error",
     *     project:            { name, path, version } | null,
     *     plcs:               string[],
     *     last_ping_ok_unix:  number | null,
     *     last_error:         string | null,
     *   }
     *
     * ``idle`` (sept-2026) sustituye al antiguo ``disconnected``:
     * el worker arranca en idle (subproceso vivo, SIN portal
     * attached) y el operario decide cuándo pulsar "Conectar"
     * del topbar para transicionar a ``connecting`` ->
     * ``connected``. La respuesta del backend al
     * ``GET /api/v1/tia/connection`` refleja esta misma
     * maquina de estados; el ``_applyTiaSnapshot`` valida el
     * ``state`` contra los 4 valores estables y descarta
     * silenciosamente cualquier otro.
     *
     * El polling cada 2 s (en ``main.js``) llama a
     * ``refreshTiaConnection()``, que actualiza este slot vía
     * ``Object.assign`` para no perder la reactividad de Vue 3
     * con arrays/objetos anidados.
     *
     * El ``TiaConnectionIndicator`` del ``ShellTopbar`` lee
     * ``store.tiaConnection.state`` reactivamente y renderiza el
     * color del círculo (verde/ámbar/gris/rojo). El click en
     * el círculo emite ``"connect"`` cuando el estado es
     * ``idle`` o ``error``, y el handler del topbar llama
     * a ``connectTia()``.
     */
    tiaConnection: {
        // Estado inicial: "idle" (worker persistente recien
        // arrancado, subproceso vivo sin portal attached). El
        // primer tick del polling (2s) lo confirmara con el
        // GET al backend.
        state: "idle",
        project: null,
        plcs: [],
        last_ping_ok_unix: null,
        last_error: null,
        // ``worker_alive`` (sept-2026): ``true`` si el subproceso
        // del worker persistente esta vivo, INDEPENDIENTEMENTE
        // del estado de attach a TIA (``state``). Ortogonal:
        // el worker puede estar vivo pero en idle (subproceso
        // vivo, sin portal attached) o vivo y conectado. El
        // ``WorkerStatusIndicator`` del topbar lee este flag.
        worker_alive: false,
        // ``project_changed`` (sept-2026, fix audit X1): ``true``
        // si el operario cambio de proyecto en TIA Portal desde el
        // ultimo attach del worker persistente. Es un flag one-shot
        // que el backend expone en ``GET /tia/connection`` (lo lee
        // de ``gateway.consume_project_changed()`` y lo resetea).
        // El frontend lo guarda aqui para que ``WorkerStatusIndicator``
        // u otros componentes puedan mostrar un aviso "el proyecto
        // TIA ha cambiado". Si el backend NO incluye el campo
        // (modo 1-shot / MCP), queda ``false`` (sin aviso).
        project_changed: false,
    },

    /**
     * Manifest del área activa, cargado por
     * ``core/interfaces/web_server/static/js/area-loader.js``.
     *
     * Shape esperado (alineado con
     * ``areas/alimentacion/frontend/manifest.js`` y con el
     * endpoint ``GET /api/v1/areas/<id>/manifest`` del backend):
     *
     *   {
     *     id, label, icon,
     *     components: {
     *       sidebar: "<ComponentName>",
     *       landing: "<ComponentName>",
     *       views:    { "<key>": "<ComponentName>", ... },
     *     },
     *     loaders: {
     *       "<ComponentName>": () => import("<url>"),
     *       ...
     *     },
     *   }
     *
     * ``null`` antes de seleccionar un área. Si el endpoint
     * ``/manifest`` no está implementado (PR 4 del backend aún no
     * lo ha añadido) o falla, ``goToArea`` lo deja ``null`` y la
     * SPA funciona en modo degradado (mensaje claro en el main).
     */
    areaManifest: null,
});

/**
 * Forma esperada de ``store.catalog`` cuando está poblado.
 * Documentado para IDEs (no se usa en runtime, los JS leen
 * ``store.catalog.X`` directamente con fallback defensivo).
 *
 * @typedef {Object} CatalogView
 * @property {Array<{hw_type: string, canonical: string, label: string}>} device_tabs
 * @property {Array<{name: string, label: string}>} nmax
 * @property {Object<string, string[]>} model_columns
 * @property {Object<string, string>} col_labels
 * @property {string[]} mono_cols
 */

/**
 * Helpers de routing. Encapsulan la transición ``welcome`` ↔ ``area``
 * para que el resto de la app no toque ``store.topLevelView``
 * directamente.
 *
 * Al entrar a un área, se hace **reset suave** del estado operativo
 * (plcs, uploadSummary, previewData) para que la nueva área no
 * arrastre datos de otra. El ``AppState`` real (``memoryState``) NO
 * se borra: la API lo recalibra con el siguiente fetch.
 */
export function goToWelcome() {
    store.topLevelView = "welcome";
    // No reseteamos selectedArea para que el Sidebar pueda mostrar
    // "último área visitada" si se decide en una iteración futura.
}

/**
 * Cambia el área activa. Resuelve el manifest del backend (vía
 * ``area-loader.loadArea``), lo guarda en ``store.areaManifest`` y
 * transiciona a la vista de área (``topLevelView = 'area'``).
 *
 * Si el endpoint ``GET /api/v1/areas/<id>/manifest`` no existe
 * todavía (PR 4 del backend aún no lo ha añadido) o responde con
 * error, ``loadArea`` cae al manifest vacío (``loaders: {}``).
 * En ese caso la SPA queda en modo degradado: ``topLevelView``
 * pasa a ``'area'``, ``areaManifest`` queda ``null``, y el
 * template raíz muestra un mensaje "Área no soportada en el
 * frontend" en lugar de los componentes. El área sigue siendo
 * navegable (volver a welcome con el botón "←" del sidebar) y
 * ningún componente crashea.
 *
 * La **transición de estado** (reset suave de plcs / selectedPlc /
 * uploadSummary / previewData) se hace antes de la carga del
 * manifest para que la UI no parpadee con datos del área anterior.
 *
 * Async porque depende de un fetch al backend. El handler del
 * shell (``main.js::onAreaSelected``) hace ``await`` y encadena
 * ``mountArea`` después de este resolve.
 */
export async function goToArea(key) {
    if (!key) return;
    store.selectedArea = key;
    store.currentView = "landing";   // arrancar siempre en el landing del área.
    // Reset suave del estado operativo de la SPA.
    store.plcs = [];
    store.selectedPlc = "";
    store.projectInfo = null;
    store.uploadSummary = null;
    store.lastExcelFile = null;
    store.previewData = null;
    // Cargar el manifest del área antes de cambiar ``topLevelView``.
    // Si falla, log warning y continuar (modo degradado).
    try {
        const { loadArea } = await import("./area-loader.js");
        const manifest = await loadArea(key);
        // Si el manifest viene con un id distinto al que pedimos
        // (p. ej. fallback genérico del backend), respetamos lo
        // que diga el manifest.
        store.areaManifest = manifest && manifest.id ? manifest : null;
    } catch (e) {
        console.warn(`[store] no se pudo cargar el manifest de "${key}":`, e);
        store.areaManifest = null;
    }
    store.topLevelView = "area";
}

/**
 * Cambia la sub-vista dentro del área activa. Centraliza la mutación
 * de ``store.currentView`` para que ningún componente lo toque
 * directamente. Llamado por:
 *   - AreaLanding (click en una tarjeta).
 *   - Sidebar (botones "Inicio del área" / "Definición programación"
 *     / "Dispositivos").
 *
 * La lista de keys válidas YA NO está hardcoded: se valida contra
 * ``store.areaManifest?.components?.views``. Si la key no está en el
 * manifest del área activa (área distinta, manifest aún no cargado
 * o key incorrecta), se ignora silenciosamente. Esto permite que
 * un área nueva traiga sus propias sub-vistas sin tocar este
 * helper.
 */
export function goToSubview(key) {
    const views = (store.areaManifest && store.areaManifest.components
                   && store.areaManifest.components.views) || null;
    if (!views || typeof views !== "object") return;
    if (!Object.prototype.hasOwnProperty.call(views, key)) return;
    store.currentView = key;
}

/**
 * Cambia el tab principal de la vista "Definición programación".
 * Encapsula la mutación de ``store.activeMainTab`` para que ningún
 * componente lo toque directamente (mismo patrón que ``goToSubview``
 * para ``store.currentView``).
 *
 * Si ``key`` no es uno de los dos valores conocidos (``'dispositivos'``
 * o ``'software'``), se ignora silenciosamente. Esto evita que un
 * input corrupto (typo, valor antiguo tras un rename) deje la SPA
 * en estado inconsistente.
 *
 * Llamado por ``MainTabs`` al hacer click. ``DefinicionProgramacion``
 * lee ``store.activeMainTab`` reactivamente y pinta el panel
 * correspondiente.
 */
export function goToMainTab(key) {
    if (key !== "dispositivos" && key !== "procesos") return;
    store.activeMainTab = key;
}

/**
 * Etiqueta humano-legible del área seleccionada, derivada de
 * ``availableAreas``. Devuelve ``''`` si no hay área o si el área
 * seleccionada no está en el catálogo (p.ej. tras un cambio de
 * config en runtime). Usado por el Sidebar para mostrar el nombre.
 */
export function selectedAreaLabel() {
    if (!store.selectedArea) return "";
    const a = store.availableAreas.find((x) => x.key === store.selectedArea);
    return a ? a.label : store.selectedArea;
}

/**
 * Carga el catálogo de presentación desde el backend
 * (``GET /api/v1/catalog``) y lo guarda en ``store.catalog``.
 *
 * Llamado al arrancar la SPA (en ``main.js``) y opcionalmente
 * desde un botón "Refrescar catálogo" si se quiere permitir
 * recargar sin recargar la página.
 *
 * Si el backend responde con error, ``store.catalog`` queda
 * ``null`` y los componentes que dependen de él (los 2
 * que muestran pestañas/tablas) caen a sus fallbacks
 * defensivos (``[]`` / ``{}``). El error se loggea pero NO se
 * lanza: la SPA sigue funcionando en modo degradado.
 */
export async function loadCatalog() {
    const { apiFetchCatalog } = await import("./api.js");
    try {
        const r = await apiFetchCatalog();
        if (r.ok && r.data && r.data.ok && r.data.catalog) {
            store.catalog = r.data.catalog;
            // Si ``activeTab`` aún no está inicializado y el
            // catálogo tiene device_tabs, fijar el primero.
            if (!store.activeTab && Array.isArray(r.data.catalog.device_tabs)) {
                const first = r.data.catalog.device_tabs[0];
                if (first && first.canonical) {
                    store.activeTab = first.canonical;
                }
            }
        } else {
            pushLog(
                "⚠️ No se pudo cargar el catálogo. La SPA funcionará " +
                "en modo degradado (sin pestañas dinámicas).",
                "warning"
            );
        }
    } catch (e) {
        pushLog(
            "⚠️ Error cargando catálogo: " + String(e),
            "warning"
        );
    }
}

/**
 * Empuja un mensaje al buffer de logs. La cola se trunca a 200
 * entradas para evitar fugas de memoria en sesiones largas.
 */
export function pushLog(message, level = "info") {
    store.logs.push({
        message: String(message),
        level,
        timestamp: new Date().toISOString(),
    });
    if (store.logs.length > 200) {
        store.logs.splice(0, store.logs.length - 200);
    }
}

/**
 * Trae el snapshot de bloques del PLC y lo aplica al store.
 *
 * Unifica los antiguos ``refreshPlcBlocks`` (thin wrapper del
 * progreso), ``loadPlcBlocksCache`` (versión datos) y
 * ``refreshPlcBlocksCache`` (versión forzada) en una sola
 * llamada. Mismo contrato observable para los call-sites
 * (``Sidebar.onPlcSelected``, ``BloquesCacheView.handleRefresh``
 * y el reload reactivo de la vista) y un solo round-trip HTTP
 * por cambio de PLC.
 *
 *   * ``plcName`` vacío → vacía ``store.plcBlocksCache``
 *     (operario deseleccionó el PLC).
 *   * ``force=false`` (default) → ``GET /blocks``. El backend
 *     decide si re-escanear o servir desde su cache (TTL 5 min).
 *   * ``force=true`` → ``POST /blocks/refresh`` (fuerza re-scan
 *     e invalida la cache del backend). Es el comportamiento que
 *     necesita el botón "↻ Refrescar" de ``BloquesCacheView``.
 *
 * La única fuente de verdad del feedback de la operación es el
 * ``ProgressTracker`` backend. El ``ProgressIndicator`` del
 * sidebar lo muestra automáticamente (polling 500 ms desde
 * ``main.js``); esta función no mantiene estado local de
 * progreso.
 *
 * En éxito aplica la respuesta al slot ``store.plcBlocksCache``
 * vía ``_applyBlocksSnapshot``. En error o excepción loggea vía
 * ``pushLog(..., "warning")`` (los warnings de timeline caen en
 * la ConsolaLogs).
 */
export async function loadAndApplyPlcBlocks(plcName, { force = false } = {}) {
    if (!plcName) {
        store.plcBlocksCache = null;
        return;
    }
    const { apiScanPlcBlocks, apiRefreshPlcBlocks } = await import("./api.js");
    try {
        const r = force
            ? await apiRefreshPlcBlocks(plcName)
            : await apiScanPlcBlocks(plcName);
        if (r.ok) {
            _applyBlocksSnapshot(plcName, r.data);
        } else if (r.errorType === "TIAConnectionError") {
            // TIA Portal no responde. El backend ya invalido su
            // cache; el frontend debe hacer lo propio para que
            // la SPA no siga trabajando con datos stale.
            pushLog(
                `TIA Portal no responde. Reconecta y vuelve a seleccionar el PLC.`,
                "error"
            );
            resetPlcState();
        } else {
            const msg =
                (r.data && (r.data.detail || r.data.error)) ||
                `HTTP ${r.status}`;
            pushLog(`Cache ${plcName}: ${msg}`, "warning");
        }
    } catch (e) {
        pushLog(
            `Cache ${plcName}: error — ${String(e && e.message ? e.message : e)}`,
            "warning"
        );
    }
}

/**
 * Aplica la respuesta del endpoint de bloques al slot
 * ``store.plcBlocksCache``. Helper privado: normaliza los
 * nombres de campos (``snapshot`` envoltorio o datos directos) y
 * rellena con arrays vacíos cualquier campo que falte, para que
 * la vista ``BloquesCacheView`` no tenga que hacer defensiva
 * extra en cada ``computed``.
 *
 * Si la respuesta está vacía o malformada, deja el cache como
 * está (mejor no pisar un snapshot válido que ya teníamos con
 * un ``null`` accidental).
 */
function _applyBlocksSnapshot(plcName, payload) {
    if (!plcName || !payload || typeof payload !== "object") return;
    const snap = (payload.snapshot && typeof payload.snapshot === "object")
        ? payload.snapshot
        : payload;
    if (!snap || typeof snap !== "object") return;
    store.plcBlocksCache = {
        plc_name: snap.plc_name || plcName,
        blocks: Array.isArray(snap.blocks) ? snap.blocks : [],
        tag_tables: Array.isArray(snap.tag_tables) ? snap.tag_tables : [],
        // ``udts`` puede no estar si el backend aún no lo expone
        // (PR paralelo de tia-ot-worker); la vista lo trata como
        // lista vacía.
        udts: Array.isArray(snap.udts) ? snap.udts : [],
        scanned_at: snap.scanned_at || new Date().toISOString(),
    };
}

/**
 * Resetea TODO el state del SPA relacionado con la selección y
 * cache de PLCs.
 *
 * Pensado para llamarse cuando el backend reporta un error de
 * conexion con TIA Portal (``X-Error-Type: TIAConnectionError``
 * en la respuesta HTTP, lanzado por la excepcion
 * ``TIAConnectionError`` en ``core/infrastructure/gateway.py``).
 * En ese caso la cache del gateway puede tener datos stale de
 * un escaneo anterior y el frontend debe volver al estado
 * "esperando reconexion" para forzar al operario a re-seleccionar
 * el PLC tras reconectar TIA.
 *
 * Slots que se resetean:
 *   - ``selectedPlc``        → ``""`` (dropdown a "Selecciona un PLC").
 *   - ``plcBlocksCache``     → ``null`` (sin snapshot de bloques).
 *   - ``plcs``               → ``[]`` (lista de PLCs disponibles).
 *   - ``previewData``        → ``null`` (preview de dispositivos N_MAX+devices).
 *   - ``procesosSync.preview``     → ``null`` (preview de comentarios de procesos).
 *   - ``procesosSync.applying``    → ``false`` (sin operación en vuelo).
 *   - ``procesosSync.error``       → mensaje accionable para el operario.
 *   - ``procesosSync.lastAppliedAt`` → ``null`` (ultimo commit perdido).
 *
 * NO se toca ``store.projectInfo`` (se reintentara en el siguiente
 * "Buscar PLCs") ni ``store.uploadSummary`` / ``store.lastExcelFile``
 * (datos del Excel son independientes de TIA). El Excel sigue siendo
 * la fuente maestra; el operario puede re-disparar el sync tras
 * reconectar.
 */
export function resetPlcState() {
    store.selectedPlc = "";
    store.plcBlocksCache = null;
    store.plcs = [];
    store.previewData = null;
    store.procesosSync.preview = null;
    store.procesosSync.applying = false;
    store.procesosSync.lastAppliedAt = null;
    store.procesosSync.error =
        "TIA Portal no responde. Reconecta el portal y vuelve a seleccionar el PLC.";
}

/**
 * Trae el snapshot del estado de conexión del worker TIA
 * persistente (PR 5b / §4.3 del design doc) desde
 * ``GET /api/v1/tia/connection`` y lo aplica a
 * ``store.tiaConnection``.
 *
 * Reglas:
 *   * Delega SIEMPRE en ``_applyTiaSnapshot(r)`` (helper privado
 *     declarado debajo) para que la logica de merge sea identica
 *     a la de ``connectTia`` y ``disconnectTia`` (DRY, fix
 *     audit X1 / sept-2026).
 *   * Si la respuesta no es OK o el snapshot no tiene un ``state``
 *     valido, ``_applyTiaSnapshot`` lo descarta silenciosamente y
 *     el slot conserva el ultimo estado conocido (preferible a
 *     un parpadeo ``connected`` → ``error`` → ``connected`` en
 *     cada timeout de la red).
 *   * La deteccion de transiciones de estado y el logueo en
 *     ``ConsolaLogs`` se hace dentro de ``_applyTiaSnapshot``
 *     (formato §4.4 del design doc).
 *
 * Idempotente y segura para llamarse en bucle (polling 2s).
 * Devuelve la respuesta cruda por si el caller quiere
 * inspeccionarla; lo normal es ignorar el retorno.
 */
export async function refreshTiaConnection() {
    const { apiFetchTiaConnection } = await import("./api.js");
    const r = await apiFetchTiaConnection();
    _applyTiaSnapshot(r);
    return r;
}

/**
 * Helper privado: loguea una transición de estado del worker
 * TIA persistente en la ``ConsolaLogs``. Usado por
 * ``_applyTiaSnapshot`` (y por tanto por ``refreshTiaConnection``,
 * ``connectTia`` y ``disconnectTia``) para mantener el formato
 * consistente (PR 5b / §4.4 del design doc).
 *
 * Tras el refactor de state machine (sept-2026), el antiguo
 * ``disconnected`` se reemplaza por ``idle``: el worker arranca
 * en idle (subproceso vivo, sin portal attached). Mantenemos el
 * mismo mensaje "Desconectado" para que la ``ConsolaLogs`` no
 * cambie de wording (el operario percibe la misma transición
 * "ya no estoy en TIA Portal"); el copy del topbar (botón
 * "Conectar") se actualiza por su cuenta en ShellTopbar.
 */
function _logTiaStateTransition(prevState, newState, snapshot) {
    if (newState === "connected") {
        const project = snapshot && snapshot.project;
        if (project && project.name) {
            const nplcs =
                (snapshot && Array.isArray(snapshot.plcs)
                    ? snapshot.plcs.length
                    : 0);
            const version = project.version ? ` v${project.version}` : "";
            pushLog(
                `[TIA] Conectado a "${project.name}" (TIA${version}, ${nplcs} PLCs).`
            );
        } else {
            pushLog("[TIA] Conectado.");
        }
    } else if (newState === "idle") {
        // Tras pulsar "Desconectar" el worker pasa a idle
        // (subproceso vivo, sin portal). El operario entiende
        // "Desconectado" como "ya no estoy en TIA Portal" sin
        // entrar en el detalle del state machine.
        pushLog(
            "[TIA] Desconectado. Pulsa 'Conectar' en el topbar para volver a abrir un portal."
        );
    } else if (newState === "error") {
        const err =
            (snapshot && snapshot.last_error) || "desconocido";
        pushLog(`[TIA] Error: ${err}`, "error");
    }
    // "connecting" se ignora: es estado transitorio.
}

/**
 * Helper privado: aplica un snapshot de ``GET /api/v1/tia/connection``
 * (o de ``POST /tia/{connect,disconnect}``) al slot
 * ``store.tiaConnection`` de forma consistente entre los 3 helpers
 * de la SPA. Encapsula el ``Object.assign`` con defaults defensivos
 * para que ``refresh``, ``connect`` y ``disconnect`` no dupliquen
 * el mismo bloque de 12 lineas (DRY, fix audit X1 / sept-2026).
 *
 * Reglas:
 *   * Valida ``r.data.state`` contra los 4 valores estables del
 *     state machine sept-2026 (``connected`` / ``connecting`` /
 *     ``idle`` / ``error``). Si el ``state`` falta o es
 *     desconocido, retorna ``false`` SIN tocar el store (mantenemos
 *     el ultimo estado conocido para evitar parpadeo en cada
 *     timeout de la red). El siguiente tick del polling (2s)
 *     reintenta. El antiguo ``disconnected`` ya NO se acepta
 *     (el backend no lo emite nunca; el frontend no lo espera).
 *   * Hace ``Object.assign(store.tiaConnection, {...})`` con los 7
 *     campos estables del snapshot, con defaults sensatos si el
 *     backend los omite (compat con respuestas sinteticas de tests
 *     y con el modo 1-shot / MCP que solo expone ``state`` y
 *     ``error``):
 *       - ``state``             → validado arriba (4 valores).
 *       - ``project``           → ``null`` (snapshot sin proyecto).
 *       - ``plcs``              → ``[]`` (sin PLCs detectados).
 *       - ``last_ping_ok_unix`` → ``null`` (nunca llego un ping OK).
 *       - ``last_error``        → ``null``.
 *       - ``worker_alive``      → ``false`` (modo 1-shot / MCP).
 *       - ``project_changed``   → ``false`` (sin cambio pendiente).
 *   * Usa ``Object.assign`` (no reasignacion completa
 *     ``store.tiaConnection = r.data``) para preservar la
 *     reactividad de los campos anidados (``project``, ``plcs``):
 *     si reasignamos, cualquier ``computed`` que tuviese una ref
 *     al objeto antiguo deja de actualizarse.
 *   * Detecta si el ``state`` cambió respecto al valor previo y
 *     delega el logueo en ``_logTiaStateTransition`` (no loguea
 *     transiciones a ``connecting`` por ser estado transitorio).
 *
 * Devuelve ``true`` si aplicó el snapshot, ``false`` si lo descartó
 * (respuesta no OK, ``r.data`` malformado o ``state`` invalido).
 * Los callers normalmente ignoran el retorno.
 */
function _applyTiaSnapshot(r) {
    if (!r || !r.ok || !r.data || typeof r.data !== "object") return false;
    const newState = r.data.state;
    if (
        newState !== "connected" &&
        newState !== "connecting" &&
        newState !== "idle" &&
        newState !== "error"
    ) {
        // Snapshot malformado: lo descartamos silenciosamente para
        // no romper el polling. El siguiente tick (2s) lo reintenta.
        return false;
    }
    const prevState = store.tiaConnection && store.tiaConnection.state;
    // Merge defensivo: conservamos los slots no presentes en la
    // respuesta (p.ej. ``worker_alive`` y ``project_changed`` pueden
    // faltar en respuestas sinteticas de tests o en el modo 1-shot
    // del backend, que solo expone ``state`` y ``error``) y
    // machacamos el resto.
    Object.assign(store.tiaConnection, {
        state: newState,
        project:
            r.data.project !== undefined ? r.data.project : null,
        plcs: Array.isArray(r.data.plcs) ? r.data.plcs : [],
        last_ping_ok_unix:
            r.data.last_ping_ok_unix !== undefined
                ? r.data.last_ping_ok_unix
                : null,
        last_error:
            r.data.last_error !== undefined ? r.data.last_error : null,
        // Merge defensivo (sept-2026, fix parpadeo "muerto"): si
        // el backend no incluye ``worker_alive`` en la respuesta
        // (p.ej. un POST antiguo que olvida propagar el campo, o
        // un GET en modo 1-shot del MCP), conservamos el valor
        // previo del store en vez de pisarlo con ``false``. Asi
        // el indicador del worker no parpadea "muerto" -> "vivo"
        // en cada click de Conectar/Desconectar (mismo patron
        // que ``project``, ``plcs``, ``last_ping_ok_unix`` y
        // ``last_error`` justo arriba).
        worker_alive:
            r.data.worker_alive === undefined
                ? store.tiaConnection.worker_alive
                : r.data.worker_alive === true,
        project_changed: r.data.project_changed === true,
    });
    if (prevState !== newState) {
        _logTiaStateTransition(prevState, newState, r.data);
    }
    return true;
}

/**
 * Fuerza la reconexión del worker TIA persistente.
 * PR 5b / §4.3 del design doc.
 *
 * Flujo:
 *   1. Setea ``store.tiaConnection.state = "connecting"`` para
 *      que el indicador se vuelva ámbar pulsante inmediatamente
 *      (feedback visual antes de que llegue la respuesta del
 *      backend, que puede tardar 5-30s en un cold-attach).
 *   2. Llama a ``POST /api/v1/tia/connect``.
 *   3. Si la respuesta es OK, delega en ``_applyTiaSnapshot(r)``
 *      para mergear el snapshot (incluidos ``worker_alive`` y
 *      ``project_changed``, que el backend expone en su respuesta).
 *      Si falla, deja el estado en ``"error"`` con el mensaje
 *      del backend (la respuesta de error NO trae snapshot, solo
 *      ``{ok: false, data: {error: ...}}``).
 *
 * Devuelve la respuesta cruda del endpoint. El handler del
 * ShellTopbar la ignora (el componente se re-renderiza solo
 * gracias a la reactividad del store).
 */
export async function connectTia() {
    const { apiConnectTia, apiFetchProjectInfo } = await import("./api.js");
    const prevState = store.tiaConnection && store.tiaConnection.state;
    store.tiaConnection = {
        ...store.tiaConnection,
        state: "connecting",
        last_error: null,
    };
    const r = await apiConnectTia();
    if (r && r.ok) {
        // ``_applyTiaSnapshot`` valida ``r.data.state`` y los 7
        // campos del snapshot. Si la respuesta es OK pero el
        // snapshot esta malformado, retorna ``false`` SIN tocar
        // el store: preferimos mantener el "connecting" optimista
        // a pisar con datos corruptos. El proximo tick del
        // polling (2s) reintentara con un GET fresco.
        _applyTiaSnapshot(r);

        // Sept-2026 (pedido operario): tras el connect OK leemos
        // las propiedades del proyecto TIA (name + path) y las
        // dejamos listas para la card de "cache del plc". Sin
        // esto, el operario tenía que esperar al siguiente poll
        // del GET /tia/connection (1s) o pulsar "Buscar PLCs" para
        // ver el nombre del proyecto, y el path ni se mostraba.
        // El round trip extra (~50ms, lectura barata) se compensa
        // con UX inmediata: el operario confirma que está conectado
        // al proyecto correcto ANTES de buscar PLCs.
        //
        // Replicamos la info en DOS slots para cubrir todos los
        // consumers:
        //   - ``store.projectInfo``: slot histórico, lo lee el
        //     ``tiaProjectName`` computed como fallback y muchos
        //     tests lo validan.
        //   - ``store.tiaConnection.project``: slot nuevo, lo usa
        //     el ``tiaProjectName`` computed como fuente principal
        //     y permite que el path se vea sin esperar al poll.
        try {
            const infoResp = await apiFetchProjectInfo();
            if (
                infoResp && infoResp.ok && infoResp.data
                && infoResp.data.project_info
            ) {
                store.projectInfo = infoResp.data.project_info;
                store.tiaConnection = {
                    ...store.tiaConnection,
                    project: infoResp.data.project_info,
                };
            } else if (infoResp && infoResp.ok === false) {
                store.projectInfo = null;
                store.tiaConnection = {
                    ...store.tiaConnection,
                    project: null,
                };
            }
        } catch (e) {
            // No tumbar el connect si la lectura del proyecto falla:
            // el operario ya está connected, y el próximo poll del
            // GET /tia/connection rellenara el project. Solo
            // dejamos un warning en la consola del navegador.
            // eslint-disable-next-line no-console
            console.warn(
                `[connectTia] No se pudo leer project info tras ` +
                `connect: ${e && e.message ? e.message : e}`
            );
        }
    } else if (r) {
        // Error path: la respuesta trae ``{ok: false, data: {error,
        // detail}}`` (o similar). Forzamos ``state='error'`` y
        // propagamos el mensaje al ``last_error`` del store.
        const err =
            (r.data && (r.data.error || r.data.detail)) ||
            `HTTP ${r.status || "?"}`;
        store.tiaConnection = {
            ...store.tiaConnection,
            state: "error",
            last_error: err,
        };
        if (prevState !== "error") {
            _logTiaStateTransition(prevState, "error", {
                last_error: err,
            });
        }
    }
    return r;
}

/**
 * Desconexión explícita del worker TIA persistente.
 * PR 5b / §4.3 del design doc + refactor state machine sept-2026.
 *
 * Llamado por el operario al pulsar el botón "Desconectar" del
 * ``ShellTopbar`` (visible cuando ``state in {connecting, connected}``).
 *
 * Idéntico patrón a ``connectTia`` pero contra
 * ``POST /api/v1/tia/disconnect``: si la respuesta es OK,
 * delega en ``_applyTiaSnapshot`` para mergear el snapshot
 * (incluidos ``worker_alive`` y ``project_changed`` si vienen).
 * Si el backend no los incluye (modo 1-shot, error response
 * parcial, etc.), el helper pone los defaults sensatos
 * (``false`` para ambos) sin romper.
 *
 * Tras el éxito del detach (sept-2026, refactor state machine),
 * limpia tambien los slots del SPA relacionados con la selección
 * y cache de PLCs:
 *   - ``plcs``            → ``[]`` (lista de PLCs, ya no aplica).
 *   - ``selectedPlc``     → ``""`` (dropdown a "Selecciona un PLC").
 *   - ``plcBlocksCache``  → ``null`` (snapshot de bloques stale).
 *   - ``projectInfo``     → ``null`` (caption del proyecto arriba).
 *
 * Sin esta limpieza, tras un "Conectar / Desconectar" rápido, el
 * topbar seguiría mostrando la lista de PLCs del attach anterior
 * y el caption del proyecto viejo, dando la falsa sensación de
 * que sigue conectado. El operario vería el círculo gris del
 * ``TiaConnectionIndicator`` pero el ``<select>`` con PLCs
 * "viejos" y el nombre del proyecto anterior en el caption.
 *
 * NO tocamos ``previewData`` ni ``procesosSync`` (slots de sync
 * de dispositivos / comentarios de procesos: son ortogonales al
 * attach a TIA Portal; el operario puede querer ver el último
 * preview tras un detach temporal). Si el operario quiere
 * limpieza total, ya tiene el botón "Limpiar" del sync.
 *
 * La limpieza se hace SIEMPRE que la respuesta del backend sea
 * OK (i.e. el detach funciono), aunque el ``_applyTiaSnapshot``
 * no haya aceptado el ``state`` (p.ej. respuesta sintetica de
 * test sin ``state`` valido). Asi el reset del PLC es
 * independiente del path de error del snapshot.
 */
export async function disconnectTia() {
    // Guard de idempotencia (sept-2026 round 3, fix de auditoría):
    // ``store.busy`` ya se setea en ``handleRefreshPlcs`` y otros
    // handlers del topbar. Sin este guard, un doble-click rápido
    // en "Desconectar" mandaba 2 POSTs en paralelo, y el segundo
    // se quedaba en cola detrás del primero en el ``_worker_lock``
    // del backend, viendo ``state="connected"`` durante segundos.
    // El botón del topbar usa ``:disabled="store.busy"`` para
    // bloquear visualmente, pero un programático / teclado rápido
    // puede saltarse el disabled. Aquí blindamos la lógica.
    if (store.busy) {
        return { ok: false, busy: true, state: store.tiaConnection?.state };
    }
    store.busy = true;
    try {
        const { apiDisconnectTia } = await import("./api.js");
        const r = await apiDisconnectTia();
        _applyTiaSnapshot(r);
        // Limpieza post-detach de los slots del PLC. Se ejecuta
        // tambien en error path: si la respuesta no es OK, dejamos
        // los slots como estaban (preferible un "stale" visible a
        // un "vacio" confuso si el detach fallo). Por eso el guard
        // ``r && r.ok``.
        if (r && r.ok) {
            store.plcs = [];
            store.selectedPlc = "";
            store.plcBlocksCache = null;
            store.projectInfo = null;
        }
        return r;
    } finally {
        store.busy = false;
    }
}

/**
 * Regresion (2026-09-05): ``main.js`` y otros callers hacen
 * ``store.refreshTiaConnection?.()`` / ``store.connectTia?.()`` /
 * ``store.disconnectTia?.()``. Asumen que el ``store`` expone los
 * helpers como metodos (mismo patron que el resto del codigo
 * reactivo). Si NO se asignan, el ``?.()`` los skipea
 * silenciosamente y la SPA queda SIN polling de TIA, sin
 * reconexion manual desde el topbar, etc.
 *
 * Las funciones ``refreshTiaConnection``, ``connectTia`` y
 * ``disconnectTia`` se exportan como funciones independientes (arriba)
 * para que el codigo de los componentes las importe y use
 * directamente (``import { connectTia } from "./store.js"``). Pero
 * ademas las EXPONEMOS en el ``store`` para los callers que las
 * invocan reactivamente (``store.refreshTiaConnection?.()``).
 */
Object.assign(store, {
    refreshTiaConnection,
    connectTia,
    disconnectTia,
});

export default store;
