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
    loadAndApplyPlcBlocks,
    resetPlcState,
    connectTia,
    disconnectTia,
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
         *
         * Guard: NO recargar si la cache ya está sincronizada con
         * el PLC nuevo. Sin este guard, ``loadAndApplyPlcBlocks``
         * setea ``store.selectedPlc = plcName`` (store.js:585, fix
         * del bug "Cache no disponible sin tocar dropdown" en
         * ``ce9f892``) y este watch se vuelve a disparar, causando
         * un bucle garantizado de doble ``scan_blocks`` por cada
         * selección de PLC. El doble scan mantiene TIA ocupado
         * ~40s y provocaba rollback silencioso en el primer commit
         * (smoke test sept-2026).
         */
        watch(
            () => store.selectedPlc,
            (newPlc) => {
                if (!newPlc) return;
                const cached = store.plcBlocksCache;
                if (cached && cached.plc_name === newPlc) return;
                loadAndApplyPlcBlocks(newPlc);
            }
        );

        // ────────────────────────────────────────────────────────────
        //  v3.0 (sept-2026): controles del worker persistente y del
        //  PLC que antes vivían en la ShellTopbar migran a este
        //  componente. La topbar ahora solo pinta el PLC activo en
        //  texto. Aquí se gestiona toda la acción: Conectar /
        //  Desconectar, refrescar PLCs, cambiar de PLC, y el
        //  status textual del worker y del attach a TIA.
        //
        //  Los botones se muestran SIEMPRE; la habilitacion
        //  (``canConnect`` / ``canDisconnect`` / ``canSelectPlc``
        //  / ``canSearchPlcs``) refleja el state machine
        //  (``idle | connecting | connected | error``) y
        //  ``store.busy``. El operario siempre ve el mismo
        //  conjunto de controles, lo que cambia es cuales
        //  están activos.
        // ────────────────────────────────────────────────────────────

        /**
         * State del worker TIA persistente (``idle | connecting |
         * connected | error``), leído de ``store.tiaConnection``.
         * Exposición plana (regla Vue 3 sin build step) para que
         * el template no acceda a ``store.tiaConnection`` directo.
         */
        const tiaState = computed(() => {
            return (store.tiaConnection && store.tiaConnection.state) || "idle";
        });

        /** True si el subproceso del worker está vivo. */
        const workerAlive = computed(() => {
            return Boolean(store.tiaConnection && store.tiaConnection.worker_alive);
        });

        /** Texto humano del state. */
        const tiaStateText = computed(() => {
            switch (tiaState.value) {
                case "connected":  return "connected";
                case "connecting": return "connecting…";
                case "error":      return "error";
                case "idle":
                default:           return "idle";
            }
        });

        /** Color del texto del state (misma paleta que el antiguo
         *  ``TiaConnectionIndicator``: green/amber/red/gray). */
        const tiaStateClass = computed(() => {
            switch (tiaState.value) {
                case "connected":  return "text-green-600 font-semibold";
                case "connecting": return "text-amber-600 font-semibold";
                case "error":      return "text-red-700 font-semibold";
                case "idle":
                default:           return "text-ink-muted font-semibold";
            }
        });

        /** True si TIA está connected (lista de PLCs operativa). */
        const isTiaConnected = computed(() => tiaState.value === "connected");

        /** Caption del proyecto TIA (vía tiaConnection.project.name
         *  o, en fallback, store.projectInfo.name — segunda fuente
         *  por si la peticion /project-info corrió antes que el
         *  state machine publicara el project). */
        const tiaProjectName = computed(() => {
            const p = store.tiaConnection && store.tiaConnection.project;
            if (p && p.name) return p.name;
            const pi = store.projectInfo;
            if (pi && pi.name) return pi.name;
            return null;
        });

        /**
         * Path del proyecto TIA (vía tiaConnection.project.path
         * o, en fallback, store.projectInfo.path). Se pinta en la
         * card 1 debajo del nombre del proyecto, en una segunda
         * linea, para que el operario confirme que está conectado
         * al proyecto correcto (no solo por nombre) antes de
         * buscar PLCs.
         *
         * Sept-2026 (pedido operario): antes el path no se mostraba
         * en ningún sitio. Ahora va en la card 1, en la lista de
         * "Estado del sistema" debajo de "Proyecto:".
         */
        const tiaProjectPath = computed(() => {
            const p = store.tiaConnection && store.tiaConnection.project;
            if (p && p.path) return p.path;
            const pi = store.projectInfo;
            if (pi && pi.path) return pi.path;
            return null;
        });

        /**
         * Habilitacion de los 2 controles del card 1 (Conectar /
         * Desconectar). Se muestran siempre; lo que cambia es si
         * aceptan click. El antiguo "select PLC" + "Buscar PLCs"
         * desaparecen en v3.1 (la seleccion de PLC se hace
         * picando en uno de los cards de la grid de "PLC
         * DISPONIBLES", y la lista se rellena automaticamente al
         * pulsar Conectar via ``connectTia()`` en el store).
         */
        const canConnect = computed(() => {
            return !store.busy
                && (tiaState.value === "idle" || tiaState.value === "error");
        });
        const canDisconnect = computed(() => {
            return !store.busy
                && (tiaState.value === "connecting" || tiaState.value === "connected");
        });

        /** Handler del botón "🔌 Conectar". Delega en
         *  ``connectTia()`` (helper del store) que pone
         *  ``state="connecting"``, dispara el POST, y tras el
         *  attach OK hace el fetch de project info Y de la lista
         *  de PLCs automaticamente (sept-2026 round 3, pedido
         *  operario). */
        async function handleConnect() {
            await connectTia();
        }

        /** Handler del botón "⏏ Desconectar". ``disconnectTia``
         *  limpia los slots del PLC tras el detach OK. */
        async function handleDisconnect() {
            await disconnectTia();
        }

        /**
         * Click en un card de la grid "PLC DISPONIBLES" (v3.1).
         * Setea ``store.selectedPlc`` y el ``watch`` existente (en
         * ``onMounted``) dispara ``loadAndApplyPlcBlocks`` que carga
         * el snapshot de bloques+tag_tables+UDTs del PLC nuevo.
         */
        function selectPlc(plc) {
            if (!plc || !plc.name) return;
            store.selectedPlc = plc.name;
        }

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
            // v3.0: controles migrados de ShellTopbar
            tiaState,
            tiaStateText,
            tiaStateClass,
            workerAlive,
            isTiaConnected,
            tiaProjectName,
            tiaProjectPath,
            canConnect,
            canDisconnect,
            handleConnect,
            handleDisconnect,
            selectPlc,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- ★ Card 1 (v3.0 sept-2026, layout dashboard v3.1):
                 estado del sistema + controles de PLC. Migrado
                 desde la ShellTopbar. Layout en 2 zonas
                 estructuradas con headers (mas "profesional"
                 que el flex column plano de v3.0):

                   Zona A (grid 2 cols, md+):
                     - Estado del sistema (header + lista con
                       bullet de color por estado).
                     - Controles (header + grid 2x2: Conectar |
                       Desconectar | select PLC full-width |
                       Buscar PLCs full-width).
                   ───────  border-t divider  ───────
                   Zona B (full width):
                     - PLC activo (header + caption + boton
                       "↻ Actualizar" a la derecha).

                 Los botones se muestran SIEMPRE; la habilitacion
                 (canConnect / canDisconnect / canSelectPlc /
                 canSearchPlcs) refleja el state machine y
                 store.busy. ★ -->
            <div class="mb-4 bg-surface-raised border border-line rounded p-4 space-y-5"
                 data-testid="bloques-cache-card-info">

                <!-- Zona A: grid 2 columnas (estado | controles) -->
                <div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">

                    <!-- Col 1: Estado del sistema -->
                    <div>
                        <h4 class="text-[10px] font-bold text-ink-muted uppercase tracking-widest mb-2">
                            Estado del sistema
                        </h4>
                        <ul class="space-y-1 text-xs">
                            <li class="flex items-center gap-2">
                                <span :class="workerAlive ? 'text-green-600' : 'text-red-700'">●</span>
                                <span class="text-ink-muted">Worker:</span>
                                <span :class="workerAlive ? 'text-green-600 font-semibold' : 'text-red-700 font-semibold'">
                                    {{ workerAlive ? 'activo' : 'inactivo' }}
                                </span>
                            </li>
                            <li class="flex items-center gap-2">
                                <span :class="tiaStateClass">●</span>
                                <span class="text-ink-muted">TIA:</span>
                                <span :class="tiaStateClass">{{ tiaStateText }}</span>
                            </li>
                            <li v-if="tiaProjectName" class="flex items-center gap-2">
                                <span class="text-ink-muted">●</span>
                                <span class="text-ink-muted">Proyecto:</span>
                                <span class="font-mono text-ink">{{ tiaProjectName }}</span>
                            </li>
                            <li v-if="tiaProjectPath" class="flex items-center gap-2">
                                <span class="text-ink-muted">●</span>
                                <span class="text-ink-muted">Ruta:</span>
                                <span class="font-mono text-ink-muted break-all" data-testid="bloques-cache-project-path">{{ tiaProjectPath }}</span>
                            </li>
                        </ul>
                    </div>

                    <!-- Col 2: Controles. v3.1 (sept-2026 round 3):
                         se elimina el <select> de PLCs y el boton
                         "🔍 Buscar PLCs". La seleccion del PLC se
                         hace ahora picando en uno de los cards de
                         la grid "PLC DISPONIBLES" de la zona B, y
                         la lista se rellena automaticamente al pulsar
                         Conectar (lo hace connectTia en el store,
                         que dispara apiFetchPlcs tras el attach). -->
                    <div>
                        <h4 class="text-[10px] font-bold text-ink-muted uppercase tracking-widest mb-2">
                            Controles
                        </h4>
                        <div class="grid grid-cols-2 gap-2">
                            <button @click="handleConnect"
                                :disabled="!canConnect"
                                data-testid="bloques-cache-connect-tia"
                                class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                                <span>🔌</span>
                                Conectar
                            </button>

                            <button @click="handleDisconnect"
                                :disabled="!canDisconnect"
                                data-testid="bloques-cache-disconnect-tia"
                                class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                                <span>⏏</span>
                                Desconectar
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Divisor entre zonas A y B. El border-t se
                     posiciona arriba del div, asi que usamos my-4
                     (margin-top y margin-bottom de 16px) en vez de
                     py-4 para que el espacio visual arriba y
                     abajo del border sea SIMETRICO. Con py-4 el
                     padding se acumula solo abajo del border,
                     dando la sensacion de "mas aire" en la parte
                     de abajo. -->
                <div class="my-4 border-t border-line"></div>

                <!-- Zona B: PLC DISPONIBLES (v3.1, sept-2026 round 3).
                     Grid responsive de cards (uno por PLC) con
                     nombre + modelo (ShortDesignation de TIA).
                     Click en un card -> store.selectedPlc = p.name
                     (el watch existente dispara loadAndApplyPlcBlocks
                     que carga el snapshot de bloques del PLC nuevo).
                     El card del PLC activo se marca con border +
                     bg verde (estilo "seleccionado" sutil). El
                     boton "↻ Actualizar" vive en la cabecera a la
                     derecha del titulo (mismo patron que el card 1
                     de otras vistas). -->
                <div>
                    <div class="flex justify-between items-center mb-2">
                        <h4 class="text-[10px] font-bold text-ink-muted uppercase tracking-widest">
                            PLC disponibles
                        </h4>
                        <button @click="handleRefresh"
                            :disabled="!store.selectedPlc || isRefreshing"
                            data-testid="bloques-cache-actualizar"
                            class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                            <span v-if="isRefreshing" class="animate-spin">↻</span>
                            <span v-else>↻</span>
                            Actualizar
                        </button>
                    </div>

                    <!-- Grid de cards: uno por PLC. Columnas fijas
                         (no auto-fit) para que la pinta sea estable
                         independientemente del numero de PLCs.
                         Formato vertical (mas alto que ancho) con
                         min-h-[120px] + p-4: las cards siempre quedan
                         en proporcion portrait (alto > ancho) en todos
                         los breakpoints. Card no seleccionado usa
                         bg-surface-sunken (gris hundido del tema) para
                         destacar como "card" frente al fondo del card
                         padre (bg-surface-raised). Card seleccionado:
                         border-green-500 + bg-green-50 + text-green-800
                         (opcion A del analisis previo, "seleccionado
                         sutil"). Hover: border-accent + bg-accent-subtle. -->
                    <div v-if="Array.isArray(store.plcs) && store.plcs.length > 0"
                         class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3"
                         data-testid="bloques-cache-plc-grid">
                        <button v-for="p in store.plcs" :key="p && p.name ? p.name : p"
                            type="button"
                            @click="selectPlc(p)"
                            :data-testid="'bloques-cache-plc-card-' + (p && p.name ? p.name : p)"
                            :data-active="(p && p.name) === store.selectedPlc"
                            :class="['text-left p-4 rounded border transition-colors duration-200 flex flex-col gap-1 min-h-[120px] justify-center',
                                     (p && p.name) === store.selectedPlc
                                         ? 'border-green-500 bg-green-50 text-green-800'
                                         : 'border-line bg-surface-sunken text-ink hover:border-accent hover:bg-accent-subtle']">
                            <span class="font-mono font-semibold text-xs truncate"
                                  :data-testid="'bloques-cache-plc-card-name-' + (p && p.name ? p.name : p)">
                                {{ p && p.name ? p.name : p }}
                            </span>
                            <span v-if="p && p.short_designation"
                                  class="text-[10px] truncate"
                                  :class="(p && p.name) === store.selectedPlc ? 'text-green-700' : 'text-ink-muted'">
                                {{ p.short_designation }}
                            </span>
                            <span v-else class="text-[10px] italic text-ink-muted">
                                modelo no disponible
                            </span>
                        </button>
                    </div>

                    <!-- Empty state: store.plcs vacio o no es array. -->
                    <div v-else
                         class="flex items-center justify-center p-6 text-center text-ink-muted text-xs italic border border-dashed border-line rounded"
                         data-testid="bloques-cache-plc-grid-empty">
                        No se han encontrado PLCs disponibles.
                    </div>
                </div>
            </div>
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

                <!-- Strip de pestañas con contador. Se oculta cuando no
                     hay cache para que el empty-state "El cache de bloques
                     está vacío" ocupe todo el card 2 sin tabs sueltos
                     sin sentido. Cuando hay cache, los tabs aparecen
                     arriba de la tabla. -->
                <div v-if="hasCache" class="flex border-b border-line bg-surface-sunken overflow-x-auto mb-3">
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

                <!-- Área de scroll: contiene las 3 tablas y el empty-state.
                     Mismo lenguaje de card que DispositivosPanel/ProcesosPanel:
                     la clase "bg-surface-raised border border-line rounded"
                     define el área scrollable de la tabla (sub-card dentro
                     de la card 2). -->
                <div class="flex-1 overflow-auto table-scroll-x mt-2 bg-surface-raised border border-line rounded">

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
                                class="border-b border-line">
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
