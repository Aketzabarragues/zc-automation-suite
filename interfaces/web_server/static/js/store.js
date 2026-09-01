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
import { reactive } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";

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

    /** Resumen devuelto por ``POST /api/v1/excel/upload``. */
    uploadSummary: null,

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
     * (bloques + tag tables + UDTs). Alimentado por los helpers
     * ``loadPlcBlocksCache`` / ``refreshPlcBlocksCache`` desde
     * los endpoints ``GET / POST /api/v1/plcs/<plc>/blocks[/refresh]``.
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
    store.uploadSummary = null;
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
 * Dispara el scan de bloques del PLC en el backend. Es un **thin
 * wrapper** sobre ``apiScanPlcBlocks`` / ``apiRefreshPlcBlocks``: NO
 * mantiene estado local en el store.
 *
 * La única fuente de verdad del feedback de la operación es el
 * ``ProgressTracker`` backend (mismo Singleton que ya usan
 * ``/sync/preview``, ``/sync/commit`` y el upload de Excel). El
 * ``ProgressIndicator`` del sidebar (anclado al fondo, polling 500 ms
 * desde ``main.js``) lo muestra automáticamente como un task más.
 *
 * Comportamiento:
 *   * ``plcName`` vacío → no hace nada (operario deseleccionó el PLC).
 *   * ``force=false`` (default) → llama a ``GET /blocks``. El backend
 *     decide si re-escanear o servir desde su cache (mismo TTL 5 min).
 *   * ``force=true`` → llama a ``POST /blocks/refresh`` (fuerza re-scan).
 *   * Loggea vía ``pushLog`` en éxito y error (los warnings de
 *     timeline caen en la ConsolaLogs).
 */
export async function refreshPlcBlocks(plcName, { force = false } = {}) {
    if (!plcName) return;
    const { apiScanPlcBlocks, apiRefreshPlcBlocks } = await import("./api.js");
    try {
        const r = force
            ? await apiRefreshPlcBlocks(plcName)
            : await apiScanPlcBlocks(plcName);
        if (!r.ok) {
            const msg =
                (r.data && (r.data.detail || r.data.error)) ||
                `HTTP ${r.status}`;
            pushLog(`Cache ${plcName}: ${msg}`, "warning");
        }
        // Si r.ok, el ProgressTracker del backend ya emitió los
        // eventos. El ProgressIndicator los recoge sin que el store
        // tenga que recordar nada.
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
 * Carga (o recarga) el snapshot cacheado de bloques del PLC en
 * ``store.plcBlocksCache`` desde el endpoint ``GET``.
 *
 * Diferencia con ``refreshPlcBlocks``:
 *   * ``refreshPlcBlocks`` es el wrapper "thin" que solo dispara
 *     el scan y deja que el ``ProgressTracker`` haga el feedback.
 *     NO toca ``store.plcBlocksCache``.
 *   * ``loadPlcBlocksCache`` es la versión "data": trae el
 *     snapshot actual y lo guarda en el store para que la vista
 *     ``BloquesCacheView`` lo pinte.
 *
 * Los dos se llaman en el ``@change`` del desplegable PLC del
 * Sidebar (``refreshPlcBlocks`` para el progreso,
 * ``loadPlcBlocksCache`` para los datos) y de nuevo al refrescar
 * manualmente desde la vista. La doble llamada es deliberada: la
 * segunda al ``GET`` suele ser cache-hit en el backend.
 *
 * ``plcName`` vacío → vacía el cache (operario deseleccionó).
 */
export async function loadPlcBlocksCache(plcName) {
    if (!plcName) {
        store.plcBlocksCache = null;
        return;
    }
    const { apiScanPlcBlocks } = await import("./api.js");
    try {
        const r = await apiScanPlcBlocks(plcName);
        if (r.ok) {
            _applyBlocksSnapshot(plcName, r.data);
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
 * Fuerza el re-scan del PLC y guarda el snapshot resultante en
 * ``store.plcBlocksCache``. Es la versión "fresca" de
 * ``loadPlcBlocksCache``: llama al ``POST /blocks/refresh`` en
 * lugar del ``GET /blocks``, así invalida la cache del backend.
 *
 * Es el handler del botón "↻ Refrescar" de la vista
 * ``BloquesCacheView``. El progreso "scaneando..." lo sigue
 * mostrando el ``ProgressIndicator`` del sidebar (la task
 * "Cache de bloques de <plc>" es la misma que dispara el
 * ``@change`` del desplegable PLC).
 */
export async function refreshPlcBlocksCache(plcName) {
    if (!plcName) return;
    const { apiRefreshPlcBlocks } = await import("./api.js");
    try {
        const r = await apiRefreshPlcBlocks(plcName);
        if (r.ok) {
            _applyBlocksSnapshot(plcName, r.data);
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

export default store;
