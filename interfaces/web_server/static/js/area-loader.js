// ============================================================================
// area-loader.js — Cargador dinamico de areas para la SPA.
//
//  Puerto del legacy (`legacy_backup/interfaces/web_server/static/js/
//  area-loader.js`) adaptado al greenfield. En el legacy, el
//  manifest lo leia el modulo directamente; aqui lo expone
//  `usePlc.loadAreaManifest()` (que ya rellena `state.areaManifest`)
//  y este modulo solo se encarga de resolver los loaders y
//  registrar los componentes en la app Vue 3.
//
//  Funciones exportadas:
//    - `loadArea(app, areaId)`:
//        1. Pide el manifest a `usePlc.loadAreaManifest(areaId)`.
//        2. Resuelve todos los loaders con `import()` en paralelo.
//        3. Registra los componentes en la app via `app.component`.
//        4. Devuelve el manifest.
//
//  Modo degradado:
//    Si el manifest viene vacio (loaders: {}), `loadArea` no hace
//    nada. La SPA muestra el "area no soportada en el frontend"
//    via `state.areaManifestEmpty`.
//
//  Sin build step: el navegador carga modulos ESM directamente
//  desde /js/ o /areas/... (URLs que el manifest serializa).
// ============================================================================

/**
 * Manifest shape (alineado con el backend `core/web/routers/areas.py`):
 *
 *   {
 *     id, label, icon,
 *     components: {
 *       sidebar: "<ComponentName>",
 *       landing: "<ComponentName>",
 *       views:    { "<key>": "<ComponentName>", ... },
 *     },
 *     loaders: {
 *       "<ComponentName>": "<url_absoluta.js>" | () => Promise<any>,
 *     },
 *   }
 *
 * @typedef {Object} AreaManifest
 * @property {string} id
 * @property {string} label
 * @property {string} icon
 * @property {{ sidebar: ?string, landing: ?string, views: Object<string, string> }} components
 * @property {Object<string, (string|function)>} loaders
 */

/**
 * Carga el manifest del area y registra sus componentes en la app.
 *
 * Orden critico (ver `AGENTS.md` §"Nueva vista en la SPA"):
 *   1. Cargar el manifest (sin tocar `topLevelView`).
 *   2. Resolver loaders y registrar componentes en la app.
 *   3. Transicionar a la vista de area (dispara re-render con TODO
 *      ya listo: manifest + componentes). Esto lo hace el caller.
 *
 * @param {{ component: (name: string, def: any) => void }} app
 *        Instancia de la app Vue 3 (`createApp(...)`).
 * @param {string} areaId
 * @returns {Promise<AreaManifest>}
 */
export async function loadArea(app, areaId) {
    // Late import: evita ciclo con usePlc si en el futuro se llama
    // desde dentro de un componente.
    const { usePlc } = await import("/js/composables/usePlc.js");
    const plc = usePlc();

    // 1) Manifest: lo leemos de state.areaManifest (que el padre ya
    //    relleno via plc.loadAreaManifest antes de llamarnos). NO
    //    hacemos un segundo fetch aqui: el manifest es grande y el
    //    doble fetch causaba 2x latencia + riesgo de loop si la SPA
    //    re-entraba en onAreaSelected por reactividad.
    const manifest = plc.areaManifest || {};
    const loaders = (manifest && manifest.loaders) || {};

    if (Object.keys(loaders).length === 0) {
        // Modo degradado: nada que montar.
        return manifest;
    }

    // 2) Resolver loaders en paralelo. Cada loader puede ser:
    //    - string (URL absoluta): `import(url)`.
    //    - function: `loader()` (modo legacy con build step).
    const entries = Object.entries(loaders);
    const modules = await Promise.all(
        entries.map(([, loader]) => {
            try {
                if (typeof loader === "string") {
                    return import(/* @vite-ignore */ loader);
                }
                if (typeof loader === "function") {
                    return Promise.resolve(loader());
                }
                console.error(
                    `[area-loader] loader de tipo desconocido ` +
                    `(${typeof loader}). Se esperaba string o function.`
                );
                return Promise.resolve(null);
            } catch (e) {
                console.error(`[area-loader] loader lanzo error:`, e);
                return Promise.resolve(null);
            }
        })
    );

    // 3) Registrar componentes en la app. Trackear cuantos se
    //    registran OK para decidir si el area es "usable" o si
    //    hay que caer al modo degradado (manifest vacio).
    let registeredCount = 0;
    entries.forEach(([name], idx) => {
        const mod = modules[idx];
        if (!mod || !mod.default) {
            console.warn(
                `[area-loader] loader "${name}" no devolvio ` +
                `{default: ...}. Saltando registro.`
            );
            return;
        }
        app.component(name, mod.default);
        registeredCount += 1;
    });

    // 4) Si NINGUN loader se registro OK (p.ej. los .js todavia
    //    no existen), vaciar los loaders del manifest para que la
    //    SPA caiga en "area no soportada en el frontend" en vez
    //    de intentar renderizar componentes desconocidos.
    if (registeredCount === 0) {
        console.warn(
            `[area-loader] Ningun loader de "${areaId}" se registro. ` +
            `Cayendo a modo degradado (area no soportada en el frontend).`
        );
        manifest.loaders = {};
    }
    return manifest;
}
