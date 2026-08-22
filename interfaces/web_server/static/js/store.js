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
     * Se mantiene SEPARADO de ``currentView`` (que sigue siendo la
     * sub-vista interna ``'sync' | 'memory'``) para no romper los
     * botones de navegación del Sidebar ni el ``v-if`` de
     * ``InspectorMemoria``.
     */
    topLevelView: "welcome",

    /**
     * Sub-vista DENTRO del área (``'sync' | 'memory'``). Decide qué
     * componente se muestra en ``<main>``. Sin cambios respecto a la
     * versión original de la SPA: los botones del Sidebar lo siguen
     * modificando directamente.
     */
    currentView: "sync",

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

export function goToArea(key) {
    if (!key) return;
    store.selectedArea = key;
    store.currentView = "sync";   // siempre arrancar en sync al entrar.
    // Reset suave del estado operativo de la SPA.
    store.plcs = [];
    store.selectedPlc = "";
    store.uploadSummary = null;
    store.previewData = null;
    store.topLevelView = "area";
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
