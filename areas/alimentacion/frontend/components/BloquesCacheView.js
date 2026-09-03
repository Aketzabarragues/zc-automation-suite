/**
 * Componente BloquesCacheView.
 *
 * Vista que muestra el snapshot cacheado de la estructura del PLC
 * activo (bloques, tag tables y UDTs). El snapshot lo emite el
 * endpoint ``GET /api/v1/plcs/<plc>/blocks`` y se guarda en
 * ``store.plcBlocksCache``. Esta vista es **solo lectura**: no
 * modifica el PLC, no hace diff, no propone cambios. Es la forma
 * que tiene el operario de inspeccionar el proyecto TIA sin abrir
 * el portal.
 *
 * Estructura:
 *   1. Cabecera con título, PLC activo y ``scanned_at``.
 *   2. Botón "↻ Refrescar" (POST /blocks/refresh) arriba a la derecha.
 *      Muestra un spinner textual mientras la operación está en
 *      vuelo. El progreso "real" (etapas del scan) lo sigue
 *      pintando el ``ProgressIndicator`` del sidebar (la
 *      ``refrescar`` reusa la misma task que el ``@change`` del
 *      desplegable PLC).
 *   3. Strip de 3 pestañas con contador:
 *        - Bloques   (DB/FB/FC/OB/...) desde ``snapshot.blocks``.
 *        - Variables (tag tables) desde ``snapshot.tag_tables``.
 *        - UDT       desde ``snapshot.udts`` (puede venir vacío
 *                    si el backend aún no expone este campo; ver
 *                    PR paralelo de tia-ot-worker).
 *   4. Tabla con las filas de la pestaña activa.
 *   5. Aviso ámbar si el snapshot tiene > 5 minutos.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``bg-accent``,
 * ``text-amber-*``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 */
import {
    computed,
    ref,
    onMounted,
    watch,
} from "/js/vendor/vue.esm-browser.prod.js";
// Imports absolutos: ver nota en ``Sidebar.js``. Los cross-cutting
// (``store.js``, ``api.js``) viven en ``/js/``, no se mueven.
import {
    store,
    pushLog,
    loadAndApplyPlcBlocks,
} from "/js/store.js";

/** Umbral de "stale" del cache local (5 min, mismo TTL que el backend). */
const STALE_AFTER_MS = 5 * 60 * 1000;

export default {
    name: "BloquesCacheView",
    setup() {
        /** Pestaña activa. Una de ``"bloques" | "variables" | "udt"``. */
        const activeTab = ref("bloques");

        /** True mientras el botón "Refrescar" está esperando respuesta. */
        const isRefreshing = ref(false);

        /** Snapshot cacheado del PLC activo (o ``null`` si aún no hay). */
        const cache = computed(() => store.plcBlocksCache);

        /** Listas normalizadas del snapshot (arrays vacíos si falta el campo). */
        const blocks = computed(() =>
            cache.value && Array.isArray(cache.value.blocks)
                ? cache.value.blocks
                : []
        );
        const variables = computed(() =>
            cache.value && Array.isArray(cache.value.tag_tables)
                ? cache.value.tag_tables
                : []
        );
        const udts = computed(() =>
            cache.value && Array.isArray(cache.value.udts)
                ? cache.value.udts
                : []
        );

        /** Conteos para los badges de las pestañas. */
        const blocksCount = computed(() => blocks.value.length);
        const variablesCount = computed(() => variables.value.length);
        const udtsCount = computed(() => udts.value.length);

        /** Timestamp del último scan (string ISO) o ``null``. */
        const scannedAt = computed(() =>
            cache.value && cache.value.scanned_at
                ? cache.value.scanned_at
                : null
        );

        /**
         * Nombre del PLC del snapshot. Si el cache no lo trae
         * explícitamente, cae al PLC activo del store (que es el
         * argumento del último fetch).
         */
        const plcName = computed(() => {
            if (cache.value && cache.value.plc_name) return cache.value.plc_name;
            return store.selectedPlc || "";
        });

        /** True si hay un snapshot cargado (no null). */
        const hasCache = computed(() => !!cache.value);

        /**
         * "Stale" = el snapshot tiene más de 5 minutos. El backend
         * tiene su propio TTL; aquí avisamos al operario para que
         * sepa que lo que ve es antiguo.
         */
        const isStale = computed(() => {
            if (!scannedAt.value) return false;
            const t = Date.parse(scannedAt.value);
            if (Number.isNaN(t)) return false;
            return Date.now() - t > STALE_AFTER_MS;
        });

        /** Filas a pintar en la pestaña activa. */
        const activeRows = computed(() => {
            if (activeTab.value === "bloques") return blocks.value;
            if (activeTab.value === "variables") return variables.value;
            if (activeTab.value === "udt") return udts.value;
            return [];
        });

        /**
         * Bloques agrupados por tipo (OB / DB / FC / FB / OTHER)
         * y, dentro de cada grupo, ordenados por nombre (case- y
         * espacio-insensitive, locale-aware). Se usa solo en la
         * pestaña "Bloques" para que el operario vea primero todos
         * los OBs, luego todos los DBs, etc. — mucho más fácil de
         * navegar que una tabla plana con 200 filas mezcladas.
         *
         * Orden de los grupos: convención Siemens de mayor a menor
         * relevancia operativa (OB = main routines, DB = datos,
         * FB = bloques con estado, FC = funciones puras, UDT =
         * tipos, OTHER = fallback). Si en el futuro aparece un tipo
         * nuevo, cae al final en ``OTHER``.
         */
        const _TIPO_ORDER = ["OB", "DB", "FB", "FC", "UDT", "OTHER"];

        const groupedBlocks = computed(() => {
            const list = Array.isArray(blocks.value) ? blocks.value : [];
            const buckets = new Map();
            for (const b of list) {
                if (!b) continue;
                const tipo = String(
                    b.tipo || b.type || "OTHER"
                ).toUpperCase() || "OTHER";
                if (!buckets.has(tipo)) buckets.set(tipo, []);
                buckets.get(tipo).push(b);
            }
            // Orden estable dentro de cada grupo: por nombre, con
            // fallback al path para que el orden sea 100% determinista
            // cuando dos bloques comparten nombre.
            for (const arr of buckets.values()) {
                arr.sort((a, b) => {
                    const an = String(
                        a && (a.nombre || a.name) || ""
                    );
                    const bn = String(
                        b && (b.nombre || b.name) || ""
                    );
                    const cmp = an.localeCompare(bn, undefined, {
                        sensitivity: "base",
                        numeric: true,
                    });
                    if (cmp !== 0) return cmp;
                    // Desempate determinista por path.
                    return String(a && a.path || "").localeCompare(
                        String(b && b.path || "")
                    );
                });
            }
            // Proyectar a la lista final con el orden predefinido
            // de tipos, y al final cualquier tipo inesperado.
            const out = [];
            for (const tipo of _TIPO_ORDER) {
                const arr = buckets.get(tipo);
                if (arr && arr.length > 0) out.push({ tipo, bloques: arr });
            }
            for (const [tipo, arr] of buckets) {
                if (_TIPO_ORDER.includes(tipo)) continue;
                if (arr && arr.length > 0) out.push({ tipo, bloques: arr });
            }
            return out;
        });

        /**
         * Helper: muestra el número de bloque. Soporta tanto la
         * clave del backend (``number``) como el alias español
         * (``numero``) por si llegan campos renombrados en
         * snapshots parciales.
         */
        function displayNumber(value) {
            if (value === null || value === undefined || value === "") return "—";
            return String(value);
        }

        /**
         * Helper: nombre del bloque / variable / UDT. Acepta
         * ``name`` o ``nombre``.
         */
        function displayName(item) {
            if (!item) return "—";
            return item.name || item.nombre || "—";
        }

        /**
         * Helper: tipo del bloque (DB / FB / FC / OB / UDT / ...).
         * Acepta ``type``, ``tipo`` o ``block_type``.
         */
        function displayType(item) {
            if (!item) return "—";
            return item.type || item.tipo || item.block_type || "—";
        }

        /**
         * Helper: ruta jerárquica dentro del proyecto TIA
         * (p.ej. ``"PLC_1/Program blocks/DBs"``). Acepta
         * ``path``, ``ruta`` o ``container_path``.
         */
        function displayPath(item) {
            if (!item) return "—";
            return item.path || item.ruta || item.container_path || "—";
        }

        /**
         * Click en "↻ Refrescar". Dispara el re-scan contra TIA
         * Portal y, cuando vuelve, actualiza ``store.plcBlocksCache``
         * con la snapshot nueva. El feedback visual de "la operación
         * está corriendo" lo da el ``ProgressIndicator`` del
         * sidebar (la task "Cache de bloques de <plc>" es la misma
         * que dispara el ``@change`` del desplegable PLC).
         *
         * El flag local ``isRefreshing`` solo deshabilita el botón
         * para evitar doble-click; NO es la fuente de verdad del
         * progreso (eso es el ProgressTracker backend).
         */
        async function handleRefresh() {
            if (!store.selectedPlc || isRefreshing.value) return;
            isRefreshing.value = true;
            try {
                await loadAndApplyPlcBlocks(store.selectedPlc, { force: true });
                pushLog(
                    `Cache de ${store.selectedPlc} refrescado`,
                    "success"
                );
            } catch (e) {
                pushLog(
                    `Error refrescando cache: ${
                        e && e.message ? e.message : String(e)
                    }`,
                    "warning"
                );
            } finally {
                isRefreshing.value = false;
            }
        }

        /**
         * Al montar: si hay un PLC seleccionado y el cache no
         * coincide con él (o está vacío), dispara el fetch. La
         * carga también la hace el Sidebar en el ``@change`` del
         * desplegable PLC; esto es la red de seguridad para el
         * caso "el usuario abre esta vista directamente" o "el
         * cache se quedó con un PLC anterior".
         */
        onMounted(() => {
            const current = store.selectedPlc;
            const cached = store.plcBlocksCache;
            if (current && (!cached || cached.plc_name !== current)) {
                loadAndApplyPlcBlocks(current);
            }
        });

        /**
         * Reactividad in-view: si el operario cambia el PLC del
         * desplegable mientras está viendo esta vista, recargamos
         * el cache para el PLC nuevo (sin esperar al próximo
         * mount).
         */
        watch(
            () => store.selectedPlc,
            (newPlc) => {
                if (newPlc) {
                    loadAndApplyPlcBlocks(newPlc);
                }
            }
        );

        return {
            store,
            activeTab,
            isRefreshing,
            hasCache,
            blocks,
            variables,
            udts,
            blocksCount,
            variablesCount,
            udtsCount,
            scannedAt,
            plcName,
            isStale,
            activeRows,
            groupedBlocks,
            displayNumber,
            displayName,
            displayType,
            displayPath,
            handleRefresh,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- Cabecera mínima: solo info contextual del PLC activo
                 (scanned_at) y botón de refresh renombrado a
                 "Actualizar". El título "Cache de bloques" y el hint
                 "Selecciona un PLC..." se eliminaron tras el
                 rediseño "Modern Corporate" — el topbar ya muestra
                 la sub-vista activa y la selección de PLC vive
                 también en el topbar. -->
            <div v-if="store.selectedPlc" class="mb-4 bg-surface-raised border border-line rounded p-4 flex justify-between items-center" data-testid="bloques-cache-card-info">
                <p class="text-xs text-ink-muted">
                    PLC activo:
                    <span class="font-semibold text-ink">{{ plcName }}</span>
                    <template v-if="scannedAt">
                        · Escaneado:
                        <span class="font-mono">{{ scannedAt }}</span>
                    </template>
                </p>
                <button @click="handleRefresh"
                    :disabled="!store.selectedPlc || isRefreshing"
                    data-testid="bloques-cache-actualizar"
                    class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    <span v-if="isRefreshing" class="animate-spin">↻</span>
                    <span v-else>↻</span>
                    Actualizar
                </button>
            </div>
            <div v-else class="mb-4 bg-surface-raised border border-line rounded p-4 flex justify-end" data-testid="bloques-cache-card-info">
                <button @click="handleRefresh"
                    :disabled="!store.selectedPlc || isRefreshing"
                    data-testid="bloques-cache-actualizar"
                    class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    <span v-if="isRefreshing" class="animate-spin">↻</span>
                    <span v-else>↻</span>
                    Actualizar
                </button>
            </div>

            <!-- Aviso ámbar: cache "stale" (> 5 min) -->
            <div v-if="isStale" class="mb-4 px-3 py-2 bg-amber-100 border border-amber-300 rounded text-xs text-amber-800">
                ⚠️ El cache tiene más de 5 minutos. Pulsa <strong>"↻ Actualizar"</strong> para re-escanear el PLC.
            </div>

            <!-- Segundo card: engloba el strip de pestañas + la tabla
                 de la pestaña activa. El operario pidió que TODA la
                 información de la tabla viviera dentro de un único
                 card, así que el strip sube al card. Se renderiza
                 siempre: si no hay cache, el empty-state "Selecciona
                 un PLC" actúa de placeholder (mismo patrón que
                 Dispositivos con su "Sin prevision generada"). -->
            <div class="flex-1 bg-surface-raised border border-line rounded p-4 mb-4 flex flex-col overflow-hidden"
                 data-testid="bloques-cache-card-tabla">

                <!-- Strip de pestañas con contador -->
                <div class="flex border-b border-line bg-surface-sunken overflow-x-auto mb-3">
                    <button @click="activeTab = 'bloques'"
                        :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                                 activeTab === 'bloques' ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                        Bloques
                        <span class="ml-1 text-[10px] opacity-70">({{ blocksCount }})</span>
                    </button>
                    <button @click="activeTab = 'variables'"
                        :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                                 activeTab === 'variables' ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                        Variables
                        <span class="ml-1 text-[10px] opacity-70">({{ variablesCount }})</span>
                    </button>
                    <button @click="activeTab = 'udt'"
                        :class="['tab-btn px-4 py-2 text-xs font-medium border-r border-line whitespace-nowrap',
                                 activeTab === 'udt' ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                        UDT
                        <span class="ml-1 text-[10px] opacity-70">({{ udtsCount }})</span>
                    </button>
                </div>

                <!-- Área de scroll: contiene las 3 tablas y el empty-state -->
                <div class="flex-1 overflow-auto table-scroll-x">

                <!-- Bloques (agrupados por tipo, ordenados por nombre dentro del grupo) -->
                <table v-if="hasCache && activeTab === 'bloques'" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted">Nombre</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Tipo</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Número</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Ruta</th>
                        </tr>
                    </thead>
                    <tbody>
                        <!-- Cabecera de grupo: "DB (5)", "FB (3)", etc. -->
                        <template v-for="group in groupedBlocks" :key="group.tipo">
                            <tr class="bg-surface-sunken border-y border-line">
                                <td colspan="4"
                                    class="px-3 py-1 text-[11px] font-semibold text-ink-muted uppercase tracking-wide">
                                    <span class="inline-block min-w-[3rem] font-mono">{{ group.tipo }}</span>
                                    <span class="ml-2 text-ink-muted normal-case font-normal">
                                        {{ group.bloques.length }}
                                        {{ group.bloques.length === 1 ? "bloque" : "bloques" }}
                                    </span>
                                </td>
                            </tr>
                            <tr v-for="b in group.bloques"
                                :key="(b.path || '') + '/' + (b.name || b.nombre || '') + '/' + (b.number ?? b.numero ?? '')"
                                class="border-b border-line bg-surface-raised">
                                <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap pl-6">
                                    {{ displayName(b) }}
                                </td>
                                <td class="px-3 py-1.5 text-ink-muted whitespace-nowrap font-mono">
                                    {{ displayType(b) }}
                                </td>
                                <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">
                                    {{ displayNumber(b.number ?? b.numero) }}
                                </td>
                                <td class="px-3 py-1.5 font-mono text-ink-muted">
                                    {{ displayPath(b) }}
                                </td>
                            </tr>
                        </template>
                        <!-- Empty state: ni un solo bloque cacheado -->
                        <tr v-if="groupedBlocks.length === 0">
                            <td colspan="4" class="px-3 py-6 text-center text-ink-muted italic">
                                ⚠️ No hay bloques cacheados. Pulsa "↻ Actualizar" para escanear.
                            </td>
                        </tr>
                    </tbody>
                </table>

                <!-- Variables (tag tables) -->
                <table v-else-if="hasCache && activeTab === 'variables'" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted">Nombre</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Ruta</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="v in variables"
                            :key="(v.path || '') + '/' + (v.name || '')"
                            class="border-b border-line">
                            <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">
                                {{ displayName(v) }}
                            </td>
                            <td class="px-3 py-1.5 font-mono text-ink-muted">
                                {{ displayPath(v) }}
                            </td>
                        </tr>
                        <tr v-if="variables.length === 0">
                            <td colspan="2" class="px-3 py-6 text-center text-ink-muted italic">
                                ⚠️ No hay variables (tag tables) cacheadas. Pulsa "↻ Actualizar".
                            </td>
                        </tr>
                    </tbody>
                </table>

                <!-- UDT (puede venir vacío si el backend aún no expone este campo) -->
                <table v-else-if="hasCache && activeTab === 'udt'" class="w-full text-xs">
                    <thead class="sticky top-0 bg-surface-sunken text-[10px] uppercase">
                        <tr>
                            <th class="px-3 py-2 text-left text-ink-muted">Nombre</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Tipo</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Número</th>
                            <th class="px-3 py-2 text-left text-ink-muted">Ruta</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="u in udts"
                            :key="(u.path || '') + '/' + (u.name || '') + '/' + (u.number ?? u.numero ?? '')"
                            class="border-b border-line">
                            <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">
                                {{ displayName(u) }}
                            </td>
                            <td class="px-3 py-1.5 text-ink-muted whitespace-nowrap">
                                {{ displayType(u) }}
                            </td>
                            <td class="px-3 py-1.5 font-mono text-ink whitespace-nowrap">
                                {{ displayNumber(u.number ?? u.numero) }}
                            </td>
                            <td class="px-3 py-1.5 font-mono text-ink-muted">
                                {{ displayPath(u) }}
                            </td>
                        </tr>
                        <tr v-if="udts.length === 0">
                            <td colspan="4" class="px-3 py-6 text-center text-ink-muted italic">
                                ⚠️ No hay UDTs cacheados. Si el backend ya expone este campo, pulsa "↻ Actualizar".
                            </td>
                        </tr>
                    </tbody>
                </table>

                <!-- Empty state global: no hay PLC seleccionado o el cache está vacío -->
                <div v-else class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded p-10 text-center text-ink-muted">
                    <div>
                        <div class="text-5xl mb-3 opacity-40">📦</div>
                        <p v-if="!store.selectedPlc" class="mb-2">
                            Selecciona un PLC en el topbar.
                        </p>
                        <p v-else class="mb-2">
                            El cache de bloques está vacío.
                        </p>
                        <p class="text-xs">
                            Pulsa <strong class="text-accent">"↻ Actualizar"</strong> para escanear el PLC.
                        </p>
                    </div>
                </div>

                </div><!-- /Área de scroll (cierre del wrapper interior de la card 2) -->

            </div><!-- /card 2 (strip + tabla) -->

        </section>
    `,
};
