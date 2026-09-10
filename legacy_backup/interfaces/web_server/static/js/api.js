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
 *
 * Timeouts (sept-2026, fix AbortError):
 *   Cada endpoint se clasifica en uno de tres buckets segun cuanto
 *   puede tardar contra TIA Portal (S7-1500 con 200+ bloques es el
 *   peor caso realista). El default es ``FAST_TIMEOUT_MS`` (2 min)
 *   para cubrir holgadamente lecturas tipicas + cold-start del
 *   backend. Las operaciones largas declaran explicitamente
 *   ``MEDIUM_TIMEOUT_MS`` o ``SLOW_TIMEOUT_MS``.
 *
 *   Reglas practicas:
 *     - FAST (2 min):  default. Lecturas puras (PLC list, logs,
 *       progress, etc) que tipicamente tardan <1s pero pueden
 *       dispararse a 30-60s en cold-start del backend.
 *     - MEDIUM (5 min): attach/open/preview/upload (pueden tocar
 *       TIA Portal en cold-start o hacer export masivo).
 *     - SLOW (10 min): commits transaccionales (N_MAX + devices en
 *       una sola transaccion COM, minutos en S7-1500 grandes).
 *     - El backend (``gateway.execute_transactional_batch`` y
 *       ``gateway.commit_devices_sync``) YA calcula su propio
 *       ``dynamic_timeout = max(default, 5s x num_ops)``. El del
 *       cliente debe ser MAYOR que el del backend, si no el
 *       navegador aborta antes de que TIA termine.
 */
const FAST_TIMEOUT_MS = 120_000;
const MEDIUM_TIMEOUT_MS = 300_000;
const SLOW_TIMEOUT_MS = 600_000;

async function _request(method, url, body, timeoutMs = FAST_TIMEOUT_MS) {
    /** @type {RequestInit} */
    const opts = { method, headers: {} };
    if (body instanceof FormData) {
        opts.body = body;
    } else if (body !== undefined && body !== null) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    // Timeout defensivo (sept-2026): sin esto, si el servidor cuelga
    // (worker persistente bloqueado, deadlock del lock, etc.) el
    // navegador espera indefinidamente y el boton se queda pillado
    // con ``store.busy = true`` para siempre. El timeout concreto se
    // elige por endpoint (ver constantes arriba); el default (30s)
    // sigue siendo valido para lecturas rapidas.
    const timeoutController = new AbortController();
    const timer = setTimeout(() => timeoutController.abort(), timeoutMs);
    opts.signal = timeoutController.signal;
    try {
        const resp = await fetch(url, opts);
        const data = await resp.json().catch(() => ({}));
        // Extraer el header ``X-Error-Type`` que los routers del
        // backend emiten cuando falla la conexion con TIA Portal
        // (ver ``TIAConnectionError`` en
        // ``core/infrastructure/gateway.py``). Lo exponemos en el
        // shape de retorno para que los componentes puedan
        // distinguir "TIA no responde" de cualquier otro error
        // y resetear el state del PLC en consecuencia. ``null`` si
        // el backend no envia el header (caso normal en respuestas
        // exitosas o errores de logica).
        const errorType = resp.headers.get("X-Error-Type") || null;
        return { ok: resp.ok, status: resp.status, data, errorType };
    } catch (e) {
        // Distinguimos timeout de otros errores para que el caller
        // pueda mostrar un mensaje accionable.
        //
        // sept-2026: si es timeout, NO mostramos el ``String(e)`` crudo
        // (``"AbortError: signal is aborted without reason"``). Eso es
        // un ``DOMException`` interno del navegador y confunde al
        // operario. En su lugar, un mensaje humano con el tiempo
        // esperado y un hint accionable.
        const isTimeout = e && e.name === "AbortError";
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        const detail = isTimeout
            ? `La operación tardó más de ${timeoutSeconds}s. ` +
              `Si persiste, comprueba el estado del worker TIA (icono del topbar) ` +
              `o reinicia la app. La operación puede haberse completado en TIA Portal ` +
              `aunque el cliente la haya abortado.`
            : String(e);
        return {
            ok: false,
            status: 0,
            data: {
                detail,
                timeout: isTimeout,
                timeoutMs: isTimeout ? timeoutMs : null,
            },
            errorType: null,
        };
    } finally {
        clearTimeout(timer);
    }
}

/** Sube el .xlsx seleccionado y devuelve el resumen del parser. */
export function apiUploadExcel(file) {
    const fd = new FormData();
    fd.append("file", file);
    // MEDIUM: el parser de openpyxl puede tardar con Excels grandes
    // (varias hojas, miles de filas, formulas). 2 min cubre holgadamente
    // un Excel corporativo tipico; subir si Aketza reporta timeouts.
    return _request("POST", "/api/v1/excel/upload", fd, MEDIUM_TIMEOUT_MS);
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
export const apiAttachPortal = () =>
    // MEDIUM: el primer attach tras arranque en frio del CLR puede
    // tardar 15-20s. Los siguientes son <5s pero dejamos margen.
    _request("POST", "/api/v1/portal/attach", undefined, MEDIUM_TIMEOUT_MS);

/** Abre un .apxx en frío (cold-start) y lo carga. */
export const apiOpenNewPortal = (projectFilePath) =>
    // MEDIUM: cold-start = arrancar TIA Portal + abrir el .apxx.
    // El open_project solo tarda 5-30s segun tamano del proyecto,
    // pero el arranque del TIA Portal puede sumar 30-60s mas.
    _request("POST", "/api/v1/portal/open-new", { project_file_path: projectFilePath }, MEDIUM_TIMEOUT_MS);

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
    // MEDIUM: hace un export masivo de las 7 tablas del PLC + diff
    // IT-only. En S7-1500 con 200+ bloques el export puede tardar
    // 30-60s. 2 min cubre holgadamente.
    _request("POST", "/api/v1/sync/preview", { plc_name: plcName }, MEDIUM_TIMEOUT_MS);

/** Aplica el Diff completo (N_MAX + devices) en UNA transacción COM única. */
export const apiCommit = (plcName, prevision) =>
    // SLOW: el backend usa ``commit_devices_sync`` con
    // ``dynamic_timeout = max(default, 5s x estimated_ops)``. Para un
    // sync de 50 N_MAX + 6 device_changes eso son ~350s. El cliente
    // debe esperar MAS que el backend, si no aborta antes de que TIA
    // termine y el operario ve un falso error.
    _request("POST", "/api/v1/sync/commit", { plc_name: plcName, prevision }, SLOW_TIMEOUT_MS);

/** Snapshot de logs para pintar la consola. */
export const apiFetchLogs = () => _request("GET", "/api/v1/logs");

/** Vacía el buffer de logs (botón "Limpiar"). */
export const apiClearLogs = () => _request("POST", "/api/v1/logs/clear");

/**
 * Push de log desde el frontend al ``LogBuffer`` del backend.
 *
 * Caso de uso (sept-2026, pedido operario): el push local de
 * ``store.js::pushLog`` solo escribe a ``store.logs`` (memoria del
 * cliente), pero el poll cada 1s sobreescribe ``store.logs`` con
 * lo que devuelve ``GET /api/v1/logs``. Para que un mensaje
 * persista en la ConsolaLogs del sidebar (que lee del backend),
 * necesitamos enviarlo al ``LogBuffer`` backend via este endpoint.
 *
 * Usado por ``store._applyTiaSnapshot`` cuando detecta que TIA
 * se cerro por fuera y limpia el state PLC-related: deja un
 * aviso "warning" en la ConsolaLogs para que el operario sepa
 * por que se han vaciado los datos.
 *
 * Args:
 *   message: texto del log (max 2000 chars, validado en backend).
 *   level: uno de "info" | "success" | "warning" | "error".
 *          El backend rechaza cualquier otro valor (Pydantic Literal).
 */
export const apiPushLog = (message, level = "info") =>
    _request("POST", "/api/v1/logs", { message, level });

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
 * reintento (ver ``store.loadAndApplyPlcBlocks``).
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
        { proc_uid: procUid, plc_name: plcName || "" },
        // MEDIUM: export masivo + diff IT-only, similar a
        // apiGeneratePreview.
        MEDIUM_TIMEOUT_MS,
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

/**
 * Devuelve el snapshot del estado de conexión del worker TIA
 * persistente (PR 5a / §4.1 del design doc).
 *
 * Shape (alineado con ``GET /api/v1/tia/connection`` del backend):
 *   {
 *     state:               "connected" | "connecting" | "disconnected" | "error",
 *     project:             { name, path, version } | null,
 *     plcs:                string[],
 *     last_ping_ok_unix:   number | null,
 *     last_error:          string | null,
 *   }
 *
 * Llamado por el polling 2s en ``main.js`` y por el
 * ``TiaConnectionIndicator`` (reactivo, vía store). NO escribe
 * al backend: es solo lectura.
 */
export const apiFetchTiaConnection = () =>
    _request("GET", "/api/v1/tia/connection");

/**
 * Fuerza la reconexión del worker TIA persistente.
 * Endpoint: POST /api/v1/tia/connect (PR 5a / §4.1 del design doc).
 *
 * En éxito el backend devuelve el nuevo snapshot (con
 * ``state === "connected"`` y el proyecto recién attached). En
 * fallo devuelve ``{ok: false, state: "error", error: "..."}``
 * y el frontend lo refleja en el store y en el log.
 */
export const apiConnectTia = () =>
    // MEDIUM: el connect arranca el worker si esta parado (lazy
    // start, sept-2026 round 3) + attach_portal. Con CLR frio puede
    // tardar 15-20s.
    _request("POST", "/api/v1/tia/connect", undefined, MEDIUM_TIMEOUT_MS);

/**
 * Desconexión explícita del worker TIA persistente.
 * Endpoint: POST /api/v1/tia/disconnect (PR 5a / §4.1 del design doc).
 *
 * Tras un 200, el snapshot del backend pasa a ``state ===
 * "disconnected"`` y el indicador del topbar se vuelve gris.
 */
export const apiDisconnectTia = () =>
    _request("POST", "/api/v1/tia/disconnect");

export function apiProcesosSyncCommit(procUid, plcName, prevision) {
    return _request(
        "POST",
        "/api/v1/procesos/sync/commit",
        { proc_uid: procUid, plc_name: plcName, prevision: prevision || {} },
        // SLOW: commit transaccional sobre DBs de procesos (similar a
        // apiCommit). El backend calcula su dynamic_timeout; el cliente
        // debe esperar MAS (10 min cubre S7-1500 grandes).
        SLOW_TIMEOUT_MS,
    );
}
