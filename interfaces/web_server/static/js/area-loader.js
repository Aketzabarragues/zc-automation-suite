/**
 * area-loader.js — Cargador dinámico de áreas para la SPA.
 *
 * La SPA no tiene build step: el navegador carga módulos ESM
 * directamente desde ``/js/``. Para soportar múltiples áreas sin
 * acoplarse a un nombre concreto de área (hoy solo "alimentacion",
 * mañana "envasado", etc.), el shell ``main.js`` pide al backend
 * el MANIFEST del área activa y registra sus componentes
 * dinámicamente.
 *
 * Funciones exportadas:
 *
 *   - ``loadArea(areaId)``
 *       Hace ``fetch("/api/v1/areas/<id>/manifest")`` y devuelve el
 *       JSON parseado (``Promise<AreaManifest>``). Si el endpoint no
 *       existe todavía (404) o responde con error, hace fallback a un
 *       manifest con ``loaders: {}`` para que la SPA pueda mostrar
 *       un mensaje claro en lugar de los componentes.
 *
 *   - ``mountArea(app, areaId)``
 *       Igual que ``loadArea`` + resuelve todos los loaders
 *       (``Promise.all``) + registra los componentes en
 *       ``app.component(name, def)``. NO monta ``<App>``; eso sigue
 *       siendo responsabilidad de ``main.js`` (``createApp(App)`` se
 *       hace una sola vez al arrancar la SPA).
 *
 * Shape esperado del manifest (alineado con
 * ``areas/alimentacion/frontend/manifest.js``):
 *
 *   {
 *     id, label, icon,
 *     components: {
 *       sidebar: "<ComponentName>",
 *       landing: "<ComponentName>",
 *       views: { "<key>": "<ComponentName>", ... },
 *     },
 *     loaders: {
 *       "<ComponentName>": () => import("<url>"),
 *       ...
 *     },
 *   }
 *
 * Los loaders son funciones que devuelven ``Promise<{default}``.
 * Cada entry se resuelve y se pasa a ``app.component(name, def)``.
 *
 * Decisión de degradación: si el endpoint ``/manifest`` no existe
 * (PR 4 del backend aún no lo ha añadido), ``loadArea`` NO lanza
 * excepción. Devuelve un manifest vacío con ``loaders: {}`` y la SPA
 * muestra un mensaje "Área no soportada en el frontend" en lugar de
 * crashear. Esto es importante para que el frontend se pueda desplegar
 * antes que el backend.
 */

/**
 * @typedef {Object} AreaManifest
 * @property {string} id
 * @property {string} label
 * @property {string} icon
 * @property {{ sidebar: string, landing: string, views: Object<string, string> }} components
 * @property {Object<string, () => Promise<any>>} loaders
 */

const _EMPTY_MANIFEST = Object.freeze({
    id: "",
    label: "",
    icon: "📁",
    components: { sidebar: null, landing: null, views: {} },
    loaders: {},
});

/**
 * Devuelve el manifest del área desde el backend.
 *
 * @param {string} areaId - Identificador del área (p. ej. ``"alimentacion"``).
 * @returns {Promise<AreaManifest>}
 */
export async function loadArea(areaId) {
    if (!areaId) return { ..._EMPTY_MANIFEST };
    const url = `/api/v1/areas/${encodeURIComponent(areaId)}/manifest`;
    try {
        const resp = await fetch(url, { method: "GET" });
        // 404 (endpoint no existe aún) o cualquier !ok → fallback.
        if (!resp.ok) {
            console.warn(
                `[area-loader] manifest de "${areaId}" no disponible ` +
                `(HTTP ${resp.status}). Usando manifest vacío.`
            );
            return { ..._EMPTY_MANIFEST, id: areaId };
        }
        const data = await resp.json().catch(() => null);
        if (!data || typeof data !== "object") {
            console.warn(
                `[area-loader] manifest de "${areaId}" malformado. ` +
                `Usando manifest vacío.`
            );
            return { ..._EMPTY_MANIFEST, id: areaId };
        }
        // Si el backend aún no ha implementado el endpoint y devuelve
        // un shape sin ``loaders`` (p. ej. un proxy del catálogo
        // genérico), normalizamos a empty loaders para no romper.
        if (!data.loaders || typeof data.loaders !== "object") {
            data.loaders = {};
        }
        return data;
    } catch (e) {
        console.warn(
            `[area-loader] error de red pidiendo manifest de "${areaId}":`,
            e
        );
        return { ..._EMPTY_MANIFEST, id: areaId };
    }
}

/**
 * Carga el manifest y registra los componentes del área en la app
 * Vue 3. Llamar ANTES de ``createApp(App).mount("#app")`` para que
 * las refs (``app.component(name, def)``) estén disponibles cuando
 * el template raíz renderice.
 *
 * Si el manifest viene vacío (endpoint no existe, red caída), la app
 * arranca igualmente; el shell SPA decide qué mostrar
 * (``store.areaManifest.loaders`` vacío → mensaje de "área no
 * soportada en el frontend" + fallback degradado).
 *
 * @param {{ component: (name: string, def: any) => void }} app
 *        Instancia de la app Vue 3 (``createApp(...)``).
 * @param {string} areaId
 * @returns {Promise<AreaManifest>} El manifest resuelto.
 */
export async function mountArea(app, areaId) {
    const manifest = await loadArea(areaId);
    const loaderEntries = Object.entries(manifest.loaders || {});
    if (loaderEntries.length === 0) {
        // Modo degradado: nada que montar. La SPA seguirá mostrando
        // welcome o el mensaje de "área no soportada" según
        // ``store.topLevelView``.
        return manifest;
    }
    const modules = await Promise.all(
        loaderEntries.map(([, loader]) => {
            try {
                // El backend (``areas/<area>/frontend/manifest.py``)
                // serializa los loaders como **strings** (URLs absolutas)
                // porque las funciones JS no son JSON-serializables. La
                // SPA los convierte aquí en ``() => import(url)``. Si
                // en el futuro algún área aporta loaders ya como
                // funciones (p. ej. vía una build step que inline el
                // manifest), se respeta tal cual.
                if (typeof loader === "string") {
                    return import(/* @vite-ignore */ loader);
                }
                if (typeof loader === "function") {
                    return Promise.resolve(loader());
                }
                console.error(
                    `[area-loader] loader de tipo desconocido (${typeof loader}). ` +
                    `Se esperaba string (URL) o function.`
                );
                return Promise.resolve(null);
            } catch (e) {
                console.error(`[area-loader] loader lanzó error:`, e);
                return Promise.resolve(null);
            }
        })
    );
    loaderEntries.forEach(([name], idx) => {
        const mod = modules[idx];
        if (!mod || !mod.default) {
            console.warn(
                `[area-loader] loader "${name}" no devolvió ` +
                `{default: ...}. Saltando registro.`
            );
            return;
        }
        app.component(name, mod.default);
    });
    return manifest;
}
