// ============================================================================
// usePlc.js — Composable Vue 3 del HMI pasivo (Fase 3 greenfield).
//
//  Sustituye al singleton `store.js` del legacy. Es la UNICA puerta de
//  entrada de los componentes al backend (no se hace `fetch` directo
//  desde un componente: AGENTS.md §4).
//
//  Modelo:
//    * Reactivos Vue 3 (`reactive`) con la forma que el backend
//      publica por SSE en `core/plc/plc.py::Engine.get_snapshot`.
//    * Singleton a nivel de modulo: cualquier `usePlc()` devuelve
//      la misma referencia. Asi un `computed` declarado en cualquier
//      componente se invalida cuando CUALQUIER otro componente (o
//      el EventSource) muta el estado via SSE.
//    * Comandos async (`startFb`, `disconnectFb`, `fetchAreas`,
//      `loadAreaManifest`) que envuelven `fetch` y devuelven shapes
//      `{ok, status, data}` consistentes con la API legacy.
//
//  Comunicacion push (sin polling):
//    * `usePlc.init()` abre 1 EventSource a `/api/v1/plc/events`.
//    * El backend envia `data: {json}\n\n`. Tres tipos:
//        - "snapshot"  → reemplaza `state.DBs` y `state.FBs` con
//                        deep merge defensivo (leccion X1: no pisar
//                        campos que faltan en el snapshot, conservar
//                        el valor previo).
//        - "fb_changed"→ mergea `state.FBs[name]`.
//        - "log"       → unshift al buffer de logs (cap 500, FIFO
//                        en almacenamiento, LIFO en presentacion).
//    * Auto-reconnect nativo del navegador. NO manejamos `onerror`
//      con reintentos manuales (dejamos que el navegador decida).
// ============================================================================

import { computed, reactive } from "/js/vendor/vue.esm-browser.prod.js";

// ---------------------------------------------------------------------------
// Estado singleton (unica instancia de la SPA).
// ---------------------------------------------------------------------------

/**
 * Estado reactivo global. Se inicializa con valores neutros que
 * casan con el "primer snapshot" del Engine (estado idle, sin FBs).
 *
 * Estructura:
 *   - DBs: dict `{nombre: dataclass_to_dict(db)}`. El backend publica
 *     `estado_conexion` siempre, las areas publican las suyas.
 *   - FBs: dict `{nombre: fb.get_state()}`.
 *   - logs: cola FIFO (cap 500) de mensajes del backend.
 *   - areas: catalogo `[{key, label, icon, available, description?}]`
 *     cargado por `fetchAreas()`.
 *   - areaManifest: manifest del area activa (de `loadAreaManifest`).
 *   - topLevelView / currentView / selectedArea: routing local del SPA.
 *   - busy: flag generico de "operacion en vuelo" (deshabilita botones).
 */
const state = reactive({
    DBs: {
        estado_conexion: {
            worker_alive: false,
            tia_state: "idle",
            project_name: "",
            project_path: "",
            plcs: [],
            last_error: "",
            last_ping_ok_unix: 0.0,
        },
    },
    FBs: {},
    logs: [],
    areas: [],
    areaManifest: null,
    topLevelView: "welcome",  // "welcome" | "area"
    currentView: "landing",   // sub-vista del area activa
    selectedArea: null,
    busy: false,
});

// ---------------------------------------------------------------------------
// EventSource singleton.
// ---------------------------------------------------------------------------

let _eventSource = null;
let _initialized = false;

/**
 * Abre el EventSource al endpoint SSE del backend. **Idempotente**: si ya
 * hay uno abierto, no hace nada. La primera llamada debe hacerse desde
 * `main.js` al arrancar la app.
 *
 * Reglas:
 *   * Una sola suscripcion por SPA (singleton a nivel de modulo).
 *   * Sin polling: el backend envia los cambios cuando los FBs transitan.
 *   * En `onerror` solo pintamos un warning; dejamos que el navegador
 *     reintente con su auto-reconnect nativo.
 *   * Los mensajes se parsean como JSON; cualquier fallo se ignora
 *     silenciosamente (un snapshot malformado no debe tirar la SPA).
 */
export function init() {
    if (_initialized) return;
    _initialized = true;
    openEventSource();
}

function openEventSource() {
    try {
        _eventSource = new EventSource("/api/v1/plc/events");
    } catch (e) {
        console.warn("[usePlc] no se pudo abrir EventSource:", e);
        return;
    }
    _eventSource.onopen = () => {
        // El backend envia el snapshot inicial inmediatamente; no
        // necesitamos pintar nada aqui. Solo dejamos el log para
        // diagnostico en DevTools.
        console.log("[usePlc] EventSource abierto");
    };
    _eventSource.onmessage = (e) => {
        let payload = null;
        try {
            payload = JSON.parse(e.data);
        } catch {
            // Mensaje no JSON: ignorar. No debe pasar (el backend
            // serializa con json.dumps), pero por si acaso.
            return;
        }
        handleEvent(payload);
    };
    _eventSource.onerror = () => {
        // EventSource nativo reconecta solo. Solo dejamos warning.
        // readyState === 2 (CLOSED) → el navegador reintentara.
        if (_eventSource && _eventSource.readyState === EventSource.CLOSED) {
            console.warn("[usePlc] EventSource cerrado, el navegador reintentara…");
        }
    };
}

// ---------------------------------------------------------------------------
// Handler de eventos SSE.
// ---------------------------------------------------------------------------

/**
 * Despacha un evento SSE al estado reactivo. Tres tipos:
 *   - snapshot: reemplaza DBs/FBs con deep merge defensivo.
 *   - fb_changed: mergea un unico FB.
 *   - log: anade al buffer de logs.
 *
 * Cualquier otro tipo (forward-compat) se ignora silenciosamente.
 */
function handleEvent(payload) {
    if (!payload || typeof payload !== "object") return;
    switch (payload.type) {
        case "snapshot":
            applySnapshot(payload);
            break;
        case "fb_changed":
            applyFbChange(payload);
            break;
        case "log":
            appendLog(payload);
            break;
        default:
            // Tipo desconocido: ignorar (forward-compat).
            break;
    }
}

/**
 * Aplica un snapshot completo. **Deep merge defensivo** (leccion X1):
 * si el snapshot omite un campo, conservamos el valor previo en vez
 * de pisarlo con `undefined`. Asi si un FB en curso no expone todos
 * sus campos en el primer push, no "borramos" lo que ya teniamos.
 *
 * Solo se hace merge profundo en DBs y FBs. La raiz (tipo) se
 * acepta y se descarta.
 */
function applySnapshot(snap) {
    if (snap.dbs && typeof snap.dbs === "object") {
        for (const [name, dbData] of Object.entries(snap.dbs)) {
            const existing = state.DBs[name];
            if (existing && typeof existing === "object" && dbData && typeof dbData === "object") {
                // Merge campo a campo: conserva los previos si faltan.
                Object.assign(existing, dbData);
            } else {
                // DB nueva: reemplazo completo.
                state.DBs[name] = { ...(dbData || {}) };
            }
        }
    }
    if (snap.fbs && typeof snap.fbs === "object") {
        for (const [name, fbData] of Object.entries(snap.fbs)) {
            const existing = state.FBs[name];
            if (existing && typeof existing === "object" && fbData && typeof fbData === "object") {
                Object.assign(existing, fbData);
            } else {
                state.FBs[name] = { ...(fbData || {}) };
            }
        }
    }
}

/**
 * Aplica un cambio de un unico FB. Merge defensivo (mismo patron
 * que `applySnapshot`): conserva campos previos que el cambio no
 * incluya.
 */
function applyFbChange(evt) {
    if (!evt || !evt.name) return;
    const existing = state.FBs[evt.name];
    if (existing && typeof existing === "object") {
        Object.assign(existing, evt);
    } else {
        state.FBs[evt.name] = { ...evt };
    }
}

/**
 * Anade un mensaje al buffer de logs. FIFO en almacenamiento con
 * cap de 500 mensajes (la presentacion los invierte para LIFO).
 * Si el timestamp falta, lo generamos aqui (defensivo).
 */
function appendLog(evt) {
    if (!evt || !evt.message) return;
    const entry = {
        message: String(evt.message),
        level: evt.level || "info",
        timestamp: evt.timestamp || new Date().toISOString(),
    };
    // unshift para mantener LIFO en presentacion con ``[...logs].reverse()``
    // en el componente, pero con el orden FIFO "natural" (mensajes
    // antiguos al final, recientes al principio del array). Asi el
    // ``slice(0, 500)`` recorta los mas antiguos primero.
    state.logs.unshift(entry);
    if (state.logs.length > 500) {
        state.logs.length = 500;
    }
}

// ---------------------------------------------------------------------------
// Comandos (fetch puro al backend). No tocan estado reactivo: solo
// disparan el side-effect. El resultado llega via SSE.
//
// Excepcion: `fetchAreas` y `loadAreaManifest` SI rellenan estado
// (`state.areas`, `state.areaManifest`) porque son snapshots HTTP,
// no eventos push.
// ---------------------------------------------------------------------------

/**
 * Arranca un FB por nombre. El backend procesa la peticion y el
 * Engine tickea el FB. Los cambios llegan al SPA via SSE.
 *
 * @param {string} name - Nombre del FB (registrado en el Engine).
 * @param {Object} [params={}] - Parametros del FB. Se envian como
 *   JSON en el body del POST.
 * @returns {Promise<{ok: boolean, status: number, data: any}>}
 */
export async function startFb(name, params = {}) {
    if (!name) {
        return { ok: false, status: 0, data: { detail: "nombre de FB vacio" } };
    }
    return _request("POST", `/api/v1/plc/fb/${encodeURIComponent(name)}/start`, params);
}

/**
 * Desconecta un FB (solo si expone `disconnect()`).
 *
 * @param {string} name - Nombre del FB.
 * @returns {Promise<{ok: boolean, status: number, data: any}>}
 */
export async function disconnectFb(name) {
    if (!name) {
        return { ok: false, status: 0, data: { detail: "nombre de FB vacio" } };
    }
    return _request("POST", `/api/v1/plc/fb/${encodeURIComponent(name)}/disconnect`);
}

/**
 * Carga el catalogo de areas desde el backend. Rellena `state.areas`.
 *
 * Si el endpoint no existe (404, todavia no lo ha montado el Agente
 * B) o falla la red, deja `state.areas = []` para que el Welcome
 * muestre el estado vacio sin romper.
 *
 * @returns {Promise<{ok: boolean, status: number, data: any}>}
 */
export async function fetchAreas() {
    const r = await _request("GET", "/api/v1/areas");
    if (r.ok && Array.isArray(r.data)) {
        state.areas = r.data;
    } else {
        // Modo degradado: areas vacias. El Welcome pinta el empty state.
        state.areas = [];
    }
    return r;
}

/**
 * Carga el manifest de un area desde el backend. Rellena
 * `state.areaManifest` y devuelve el JSON.
 *
 * Si el endpoint no existe (404) o falla, rellena `state.areaManifest`
 * con un manifest vacio (id del area, loaders: {}) para que la SPA
 * pueda mostrar el "modo degradado" sin crashear.
 *
 * @param {string} id - Identificador del area.
 * @returns {Promise<{ok: boolean, status: number, data: any}>}
 */
export async function loadAreaManifest(id) {
    if (!id) {
        const empty = { id: "", label: "", icon: "", components: {}, loaders: {} };
        state.areaManifest = empty;
        return { ok: false, status: 0, data: { detail: "id de area vacio" } };
    }
    const r = await _request("GET", `/api/v1/areas/${encodeURIComponent(id)}/manifest`);
    if (r.ok && r.data && typeof r.data === "object") {
        state.areaManifest = r.data;
    } else {
        // Fallback degradado.
        state.areaManifest = {
            id,
            label: id,
            icon: "",
            components: { sidebar: null, landing: null, views: {} },
            loaders: {},
        };
    }
    return r;
}

// ---------------------------------------------------------------------------
// Helpers privados.
// ---------------------------------------------------------------------------

/**
 * Wrapper de `fetch` con shape consistente. **NO toca el estado**
 * (a diferencia de `fetchAreas` y `loadAreaManifest` que si lo
 * modifican). Usado por `startFb` y `disconnectFb`.
 *
 * Devuelve `{ok, status, data, errorType}`. `errorType` es
 * `X-Error-Type` si el backend lo envia.
 */
async function _request(method, url, body) {
    const opts = { method, headers: {} };
    if (body !== undefined && body !== null) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    try {
        const resp = await fetch(url, opts);
        let data = {};
        try {
            data = await resp.json();
        } catch {
            // Respuesta no JSON: dejar data como {}.
        }
        const errorType = resp.headers.get("X-Error-Type") || null;
        return { ok: resp.ok, status: resp.status, data, errorType };
    } catch (e) {
        return {
            ok: false,
            status: 0,
            data: { detail: String(e && e.message ? e.message : e) },
            errorType: null,
        };
    }
}

// ---------------------------------------------------------------------------
// Composable publico. Devuelve el singleton `state` con helpers.
// ---------------------------------------------------------------------------

/**
 * Composable Vue 3. Devuelve el singleton `state` + comandos + un
 * set de `computed` ya derivados (connected, connecting, idle, errorState)
 * para que el template los lea como variables planas.
 *
 * Regla Vue 3 sin build step: el template solo lee variables planas
 * retornadas del `setup()`. NUNCA accede a `state.X` directamente.
 * Por eso se exponen los `computed` aqui.
 */
export function usePlc() {
    /**
     * Estado de la conexion TIA (computed para el template). Lee de
     * `state.DBs.estado_conexion` que el backend rellena por SSE.
     * Default "idle" (estado del worker persistente recien arrancado).
     */
    const tiaState = computed(() => {
        const db = state.DBs.estado_conexion;
        return (db && db.tia_state) || "idle";
    });
    const workerAlive = computed(() => {
        const db = state.DBs.estado_conexion;
        return Boolean(db && db.worker_alive);
    });
    const projectName = computed(() => {
        const db = state.DBs.estado_conexion;
        return (db && db.project_name) || "";
    });
    const projectPath = computed(() => {
        const db = state.DBs.estado_conexion;
        return (db && db.project_path) || "";
    });
    const plcs = computed(() => {
        const db = state.DBs.estado_conexion;
        return (db && Array.isArray(db.plcs)) ? db.plcs : [];
    });
    const lastError = computed(() => {
        const db = state.DBs.estado_conexion;
        return (db && db.last_error) || "";
    });

    /**
     * Flags derivados del state machine TIA. Mapeo 1:1 con el
     * contrato del `TiaConnectionIndicator` legacy:
     *   - connected: state === "connected"
     *   - connecting: state === "connecting"
     *   - idle: state === "idle"
     *   - errorState: state === "error"
     */
    const connected = computed(() => tiaState.value === "connected");
    const connecting = computed(() => tiaState.value === "connecting");
    const idle = computed(() => tiaState.value === "idle");
    const errorState = computed(() => tiaState.value === "error");

    // -----------------------------------------------------------------
    // IMPORTANTE — patron de retorno del composable.
    //
    // El bug que esto arregla: si retornamos `{ areas: state.areas, ... }`,
    // JavaScript copia la referencia al array INICIAL (vacio) en el
    // momento de la llamada. Cuando `fetchAreas()` hace luego
    // `state.areas = r.data`, el objeto `plc` que el componente tiene
    // SIGUE apuntando al array inicial — el template nunca ve el
    // catalogo nuevo.
    //
    // Solucion: devolver un Proxy que delega las lecturas a `state`
    // (que es el `reactive` original). Asi `plc.areas` se resuelve
    // a `state.areas` en CADA acceso, y la reactividad de Vue 3
    // trackea la dependencia via el `get` trap del `reactive`.
    //
    // Los `computed` y las funciones se exponen como extensiones
    // (precedencia sobre el state si hay colision de keys, que no
    // deberia haber dado el naming usado).
    // -----------------------------------------------------------------
    const extensions = {
        // Computed para el template.
        tiaState,
        workerAlive,
        projectName,
        projectPath,
        plcs,
        lastError,
        connected,
        connecting,
        idle,
        errorState,
        // Comandos.
        startFb,
        disconnectFb,
        fetchAreas,
        loadAreaManifest,
        // Lifecycle.
        init,
    };
    return new Proxy(state, {
        get(target, prop) {
            if (prop in extensions) return extensions[prop];
            return target[prop];
        },
        has(target, prop) {
            return prop in extensions || prop in target;
        },
        ownKeys(target) {
            // Expone las keys de `state` + las de `extensions` para
            // que `Object.keys(plc)` y el devtools de Vue las vean.
            return Array.from(new Set([
                ...Reflect.ownKeys(target),
                ...Reflect.ownKeys(extensions),
            ]));
        },
        getOwnPropertyDescriptor(target, prop) {
            if (prop in extensions) {
                return Reflect.getOwnPropertyDescriptor(extensions, prop);
            }
            return Reflect.getOwnPropertyDescriptor(target, prop);
        },
    });
}
