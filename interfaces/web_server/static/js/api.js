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
