/**
 * Funciones puras de fetch hacia la SPA (``/api/v1/...``).
 *
 * Cada función:
 *  * Devuelve ``{ ok, status, data }`` (mismo contrato que la SPA
 *    legacy consumía).
 *  * NO toca ``store`` directamente: la orquestación (éxito/error,
 *    logs, estado) se hace en el componente que invoca la API.
 *  * Tolera respuestas no-JSON (``data = {}`` por defecto).
 *
 * Mantener estas funciones PURAS facilita:
 *   * Reutilizarlas desde varios componentes sin duplicación.
 *   * Mockearlas en tests con ``vi.mock`` o sustituyendo el módulo.
 *   * Localizar el cambio cuando evolucione el endpoint backend.
 */

async function _request(method, url, body) {
    /** @type {RequestInit} */
    const opts = { method, headers: {} };
    if (body instanceof FormData) {
        opts.body = body;
    } else if (body !== undefined && body !== null) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    try {
        const resp = await fetch(url, opts);
        const data = await resp.json().catch(() => ({}));
        return { ok: resp.ok, status: resp.status, data };
    } catch (e) {
        return { ok: false, status: 0, data: { detail: String(e) } };
    }
}

/** Sube el .xlsx seleccionado y devuelve el resumen del parser. */
export function apiUploadExcel(file) {
    const fd = new FormData();
    fd.append("file", file);
    return _request("POST", "/api/v1/excel/upload", fd);
}

/**
 * Devuelve el catálogo de áreas configuradas en el backend.
 * Cada elemento: ``{ key, label, description, icon, available }``.
 * Alimenta la pantalla de bienvenida.
 */
export const apiFetchAreas = () => _request("GET", "/api/v1/areas");

/** Devuelve la lista de PLCs del TIA Portal conectado. */
export const apiFetchPlcs = () => _request("GET", "/api/v1/plcs");

/**
 * Devuelve las propiedades básicas del proyecto TIA activo
 * (al menos ``name``; opcionalmente ``path``, ``author``,
 * ``creation_time``, ``last_modified``, ``last_modified_by``,
 * ``version``). Mismo contrato de error que ``apiFetchPlcs``:
 * si TIA no está conectado, devuelve ``{ok: false, error: ...}``.
 */
export const apiFetchProjectInfo = () =>
    _request("GET", "/api/v1/portal/project-info");

/** Dispara el hot-attach contra una instancia abierta de TIA Portal. */
export const apiAttachPortal = () => _request("POST", "/api/v1/portal/attach");

/** Abre un .apxx en frío (cold-start) y lo carga. */
export const apiOpenNewPortal = (projectFilePath) =>
    _request("POST", "/api/v1/portal/open-new", { project_file_path: projectFilePath });

/** Vuelca el ``AppState`` (IT-only) para alimentar el Inspector. */
export const apiFetchMemory = () => _request("GET", "/api/v1/state/dispositivos");

/**
 * Devuelve el catálogo de presentación: device_tabs, nmax,
 * model_columns, col_labels, mono_cols. La SPA lo cachea en
 * ``store.catalog`` al arrancar; cualquier nuevo tipo de
 * dispositivo o N_MAX añadido al ``config.json`` aparece sin
 * tocar JS.
 */
export const apiFetchCatalog = () => _request("GET", "/api/v1/catalog");

/** Pide a TIA Portal una Pre-Flight (Diff) completa: N_MAX + devices. NO toca TIA. */
export const apiGeneratePreview = (plcName) =>
    _request("POST", "/api/v1/sync/preview", { plc_name: plcName });

/** Aplica el Diff completo (N_MAX + devices) en UNA transacción COM única. */
export const apiCommit = (plcName, prevision) =>
    _request("POST", "/api/v1/sync/commit", { plc_name: plcName, prevision });

/** Snapshot de logs para pintar la consola. */
export const apiFetchLogs = () => _request("GET", "/api/v1/logs");

/** Vacía el buffer de logs (botón "Limpiar"). */
export const apiClearLogs = () => _request("POST", "/api/v1/logs/clear");

/**
 * Snapshot del ``ProgressTracker`` backend.
 *
 * Devuelve la forma ``{ ok, progress: { active, operation, label, current,
 * total, percent, stages, started_at, finished_at, error } }``.
 *
 * Llamado por el polling 500 ms en ``main.js``. NO escribe al backend
 * (la SPA es solo observadora; el backend emite los cambios cuando
 * los use cases avanzan).
 */
export const apiFetchProgress = () =>
    _request("GET", "/api/v1/progress/current");

/**
 * Resetea el ``ProgressTracker`` backend al estado vacío.
 *
 * Disparado por el frontend tras el auto-close del overlay
 * (3-5 s tras éxito) o cuando el operario pulsa "Cerrar" en
 * estados terminales. Idempotente.
 */
export const apiClearProgress = () =>
    _request("POST", "/api/v1/progress/clear");

/**
 * Devuelve el snapshot de bloques+tag_tables cacheado del PLC.
 * Endpoint: GET /api/v1/plcs/{plc_name}/blocks
 *
 * El backend puede responder 404 mientras el router no está
 * desplegado; el SPA lo trata como "cache miss" y permite
 * reintento (ver ``store.refreshPlcBlocks``).
 *
 * Devuelve la forma ``{ ok, status, data }`` estándar. En éxito
 * ``data`` suele traer ``{ ok, snapshot }`` donde ``snapshot`` es
 * ``{ plc_name, blocks, tag_tables, scanned_at, from_cache }``.
 */
export function apiScanPlcBlocks(plcName) {
    return _request(
        "GET",
        `/api/v1/plcs/${encodeURIComponent(plcName)}/blocks`
    );
}

/**
 * Fuerza re-scan del PLC (ignora caché del backend).
 * Endpoint: POST /api/v1/plcs/{plc_name}/blocks/refresh
 *
 * Usado por el botón ↻ del badge en el Sidebar para que el
 * operario pueda invalidar manualmente sin esperar al TTL de
 * 5 minutos del cache local.
 */
export function apiRefreshPlcBlocks(plcName) {
    return _request(
        "POST",
        `/api/v1/plcs/${encodeURIComponent(plcName)}/blocks/refresh`
    );
}

/**
 * Pide al backend un preview del diff de comentarios de DBs de
 * un proceso (PReal + PInt + ALM) sin tocar TIA.
 * Endpoint: POST /api/v1/procesos/sync/preview
 *
 * Devuelve el shape esperado por ``ProcesosSyncView``: incluye
 * ``precondiciones_ok``, ``missing_blocks``, ``arrays`` (PReal,
 * PInt, ALM con sus slot_maps y summaries) y un ``summary`` global.
 *
 * @param {number} procUid - uid del ProcesoPLC seleccionado.
 * @param {string} [plcName] - nombre del PLC activo (opcional, solo
 *                             para logging del backend).
 * @returns {Promise<{ok, status, data}>}
 */
export function apiProcesosSyncPreview(procUid, plcName) {
    return _request(
        "POST",
        "/api/v1/procesos/sync/preview",
        { proc_uid: procUid, plc_name: plcName || "" }
    );
}

/**
 * Aplica el diff de comentarios de DBs de un proceso en UNA sola
 * transacción TIA atómica (con rollback si algo falla).
 * Endpoint: POST /api/v1/procesos/sync/commit
 *
 * El backend recalcula el diff desde el AppState (NO usa la
 * ``prevision`` del body para evitar race conditions con cambios
 * de Excel entre el preview y el commit). El ``plc_name`` es
 * obligatorio.
 *
 * @param {number} procUid - uid del ProcesoPLC seleccionado.
 * @param {string} plcName - nombre del PLC activo.
 * @param {object} prevision - dict con el preview previo (el
 *                            backend lo re-calcula; el cliente
 *                            puede pasar el mismo que recibió).
 * @returns {Promise<{ok, status, data}>}
 */
export function apiProcesosSyncCommit(procUid, plcName, prevision) {
    return _request(
        "POST",
        "/api/v1/procesos/sync/commit",
        { proc_uid: procUid, plc_name: plcName, prevision: prevision || {} }
    );
}
