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
    /** 'sync' | 'memory' — qué vista principal se muestra. */
    currentView: "sync",

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
     */
    memoryState: null,

    /**
     * Previsión de cambios actual generada por
     * ``POST /api/v1/sync/preview``.
     */
    previewData: null,

    /** Tab activa del Inspector (``'DispED' | 'DispEA' | ...``). */
    activeTab: "DispED",

    /** Flag de operación en curso (deshabilita botones). */
    busy: false,
});

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

export default store;
