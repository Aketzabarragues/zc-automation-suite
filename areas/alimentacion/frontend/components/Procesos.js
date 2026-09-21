/**
 * Componente Procesos.
 *
 * Sub-vista de primer nivel del área "alimentacion" que se muestra
 * cuando ``store.currentView === 'proc'``.
 *
 * Estructura:
 *   1. Cabecera: icono + título + descripción corta.
 *   2. Banner ámbar si NO hay Excel cargado o si
 *      ``store.memoryState.procesos`` está vacío.
 *   3. Selector de proceso (``<select>`` con
 *      ``store.memoryState.procesos``). Cada item muestra
 *      ``codigo`` y ``nombre``. (Antes se mostraba también un
 *      sub-caption con UID + nombres simbólicos de DB; eliminado
 *      por ser legacy — el UID ya viene en el selector y los
 *      nombres de DB los computa el use case internamente).
 *   4. 2 cards de acción:
 *        - "Crear proceso completo" (expande la vista
 *          ``<procesos-crear-view>`` INLINE debajo de las cards,
 *          sin cambiar ``store.currentView``).
 *        - "Actualizar comentarios de DB" (expande la vista
 *          ``<procesos-sync-view>`` INLINE debajo de las cards,
 *          sin cambiar ``store.currentView``).
 *
 * Decisiones de diseño:
 *   - Estado local: ``selectedProcUid`` y ``showSyncView`` como
 *     ``ref``. No se meten en ``store.js`` — se resetean al
 *     desmontar el componente.
 *   - El sync view se renderiza inline (no como sub-vista separada)
 *     para que el operario mantenga el contexto del selector de
 *     proceso visible mientras revisa el diff / aplica cambios. Si
 *     quiere cambiar de proceso, puede hacerlo desde el mismo
 *     selector sin perder la vista de sync (que se re-renderiza
 *     reactivamente con el nuevo proc_uid).
 *   - El sync view se comunica con Procesos.js por eventos Vue:
 *     ``@close="showSyncView = false"`` cuando el operario pulsa
 *     el botón "Cerrar" de la cabecera del sync view (que emite
 *   - No llama a ``api.js`` ni a ningún endpoint: la UI es
 *     completamente pasiva, se alimenta de ``store.memoryState``.
 *   - Reactividad in-view: si el operario sube un Excel y refresca
 *     la memoria mientras está aquí, el computed ``procesos`` se
 *     actualiza y el selector se repobla automáticamente.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``bg-amber-*``,
 * ``text-amber-*``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 * (Los ``class="..."`` estáticos partidos en varias líneas SÍ se
 * permiten — es CSS normal, no class binding dinámico.)
 */
import { computed, ref } from "/js/vendor/vue.esm-browser.prod.js";
// Imports absolutos: ver nota en ``Sidebar.js``. Los cross-cutting
// (``store.js``) viven en ``/js/``, no se mueven.
import { store } from "/js/store.js";

export default {
    name: "Procesos",
    setup() {
        /**
         * UID del proceso seleccionado en el ``<select>``. ``null``
         * significa "ninguno". Es estado local: se resetea al
         * desmontar el componente (al navegar a otra sub-vista).
         * Usar el ``uid`` (int) en lugar del objeto entero simplifica
         * el ``v-model`` y permite que Vue resuelva el ``<option>``
         * activo por valor sin comparaciones profundas.
         */
        const selectedProcUid = ref(null);

        /**
         * Flag que controla si la vista de sync (``<procesos-sync-view>``)
         * se renderiza inline debajo de las cards. ``false`` por
         * defecto — se pone a ``true`` al pulsar la card
         * "Actualizar comentarios de DB". El operario la cierra con
         * el botón "Cerrar" de la cabecera del propio sync view
         * (que emite ``close`` y nosotros ponemos el flag a ``false``).
         *
         * Razón del cambio desde el diseño original: tener el sync
         * view como sub-vista separada (``store.currentView =
         * "proc_sync"``) hacía perder el contexto del selector de
         * proceso. Renderizarlo inline mantiene la coherencia
         * visual y permite cambiar de proceso sin "volver atrás".
         */
        const showSyncView = ref(false);

        /**
         * Flag paralelo a ``showSyncView`` pero para la sub-vista
         * inline ``<procesos-crear-view>``. Mismo patron: el
         * componente hijo emite ``close`` y nosotros lo apagamos.
         * Mantenerlo independiente de ``showSyncView`` permite que
         * ambas vistas convivan (no deberia ser habitual, pero no
         * queremos acoplar su lifecycle).
         */
        const showCrearView = ref(false);

        /**
         * Lista de procesos del Excel cacheado. Defensivo: si el
         * operario aún no ha subido Excel o el backend aún no expone
         * el campo, devuelve ``[]``. Mismo patrón que
         * ``ProcesosPanel.js:45-47``.
         */
        const procesos = computed(
            () => (store.memoryState && store.memoryState.procesos) || []
        );

        /**
         * ``true`` solo cuando hay ``memoryState`` cargado (no
         * ``null`` ni ``undefined``). Mismo patrón que
         * ``ProcesosPanel.js:79-81``. Distingue 2 estados:
         *   1. ``store.memoryState === null``: estado virgen
         *      pre-upload. Banner ámbar + selector deshabilitado.
         *   2. ``store.memoryState`` es un objeto (incluso con
         *      ``procesos: []``): ya hay cache; si la lista está
         *      vacía, banner ámbar explica que el Excel no tiene
         *      procesos definidos.
         */
        const hasExcel = computed(
            () => store.memoryState !== null && store.memoryState !== undefined
        );

        /** ``true`` cuando hay al menos un proceso en el cache. */
        const hasProcesos = computed(() => procesos.value.length > 0);

        /**
         * Objeto del proceso actualmente seleccionado, o ``null``
         * si el operario aún no ha elegido ninguno (o el UID ya no
         * existe tras un refresh del Excel que dejó un uid
         * huérfano). Recalculado reactivamente.
         */
        const selectedProc = computed(
            () => procesos.value.find((p) => p.uid === selectedProcUid.value) || null
        );

        /**
         * Habilita las 2 cards de acción. ``true`` solo si hay un
         * proceso seleccionado. Cuando es ``false`` los botones
         * reciben ``:disabled="!canAct"`` y se pintan en gris con
         * ``cursor-not-allowed``.
         */
        const canAct = computed(() => selectedProc.value !== null);

        /**
         * Habilita SOLO la card "Actualizar comentarios de DB".
         * Necesita, además del proceso seleccionado, que el Excel
         * esté cargado Y que la cache de bloques del PLC activo
         * tenga al menos un bloque (es decir, que el operario haya
         * seleccionado un PLC en el sidebar y se haya completado
         * el escaneo).
         */
        const plcBlocksCache = computed(
            () => store.plcBlocksCache || null
        );
        const canOpenSync = computed(() => {
            if (!canAct.value) return false;
            if (!hasExcel.value) return false;
            const cache = plcBlocksCache.value;
            if (!cache) return false;
            if (!Array.isArray(cache.blocks)) return false;
            return cache.blocks.length > 0;
        });

        /**
         * Habilita SOLO la card "Crear proceso completo".
         * Necesita SOLO el proceso seleccionado del Excel: no
         * requiere cache de bloques del PLC (el FB detecta las
         * colisiones internamente leyendo excel_cache + bloques_cache
         * del FB, no del client).
         */
        const canOpenCrear = computed(() => {
            if (!canAct.value) return false;
            if (!hasExcel.value) return false;
            return true;
        });

        /**
         * Tooltip HTML estándar que explica por qué la card está
         * deshabilitada. Mensaje accionable según el motivo.
         */
        const syncCardTooltip = computed(() => {
            if (!hasExcel.value) {
                return "Carga primero el Excel y pulsa 'Actualizar' en 'Definición programación'.";
            }
            if (!canAct.value) {
                return "Selecciona un proceso de la lista.";
            }
            const cache = plcBlocksCache.value;
            if (!cache || !Array.isArray(cache.blocks) || cache.blocks.length === 0) {
                return "Selecciona un PLC en el sidebar y espera al escaneo de bloques.";
            }
            return "";
        });

        /**
         * Tooltip para la card "Crear proceso completo". Misma
         * estructura que ``syncCardTooltip`` pero sin chequeo de
         * ``plcBlocksCache`` (no aplica a esta card).
         */
        const crearCardTooltip = computed(() => {
            if (!hasExcel.value) {
                return "Carga primero el Excel y pulsa 'Actualizar' en 'Definición programación'.";
            }
            if (!canAct.value) {
                return "Selecciona un proceso de la lista.";
            }
            return "";
        });

        /**
         * Handler de la card "Actualizar comentarios de DB". Activa el
         * flag local ``showSyncView`` para que se renderice inline
         * la vista ``<procesos-sync-view>`` debajo de las cards.
         *
         * Apaga ``showCrearView`` para que el card comun muestre
         * solo una vista a la vez (sync XOR crear). El operario
         * puede cambiar de accion cerrando la actual y pulsando la
         * otra.
         *
         * NO cambiamos ``store.currentView`` — seguimos en la misma
         * vista "proc", solo expandimos un panel hijo. Esto es
         * intencional: queremos que el selector de proceso siga
         * visible mientras el operario revisa el diff.
         */
        function openSyncView() {
            showCrearView.value = false;
            showSyncView.value = true;
        }

        /**
         * Handler del evento ``close`` que emite
         * ``<procesos-sync-view>`` cuando el operario pulsa
         * "Cerrar". Colapsa la vista inline.
         */
        function closeSyncView() {
            showSyncView.value = false;
        }

        /**
         * Handler de la card "Crear proceso completo". Activa el
         * flag ``showCrearView`` para que se monte inline
         * ``<procesos-crear-view>`` debajo de las cards. Análogo a
         * ``openSyncView``: NO cambia ``store.currentView``.
         *
         * Apaga ``showSyncView`` (mutuamente excluyente: solo una
         * vista visible a la vez en el card comun).
         */
        function openCrearView() {
            showSyncView.value = false;
            showCrearView.value = true;
        }

        /**
         * Handler del evento ``close`` que emite
         * ``<procesos-crear-view>`` cuando el operario pulsa
         * "Cerrar". Colapsa la vista inline de crear.
         */
        function closeCrearView() {
            showCrearView.value = false;
        }

        return {
            procesos,
            hasExcel,
            hasProcesos,
            selectedProcUid,
            selectedProc,
            showSyncView,
            showCrearView,
            canAct,
            canOpenSync,
            canOpenCrear,
            syncCardTooltip,
            crearCardTooltip,
            openSyncView,
            closeSyncView,
            openCrearView,
            closeCrearView,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- Cabecera eliminada tras el rediseño "Modern Corporate":
                 el topbar ya muestra la sub-vista activa y no hace
                 falta repetir el icono + título + descripción dentro
                 del contenido. -->

            <!-- Banner ámbar: cubre los 2 casos "no operable" del flujo.
                 Aparece cuando NO hay Excel cargado O cuando el
                 Excel existe pero su hoja de procesos está vacía. -->
            <div v-if="!hasExcel || !hasProcesos"
                 class="mb-4 px-3 py-2 bg-amber-100 border border-amber-300 rounded text-xs text-amber-800">
                <span v-if="!hasExcel">
                    ⚠️ No hay Excel cargado. Sube un Excel y pulsa
                    <strong class="text-accent">"Actualizar"</strong>
                    en "Definición programación".
                </span>
                <span v-else>
                    ⚠️ El Excel cargado no tiene procesos definidos.
                </span>
            </div>

            <!-- Selector de proceso -->
            <div class="mb-4 bg-surface-raised border border-line rounded p-4">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">
                    Proceso
                </label>
                <select v-model="selectedProcUid"
                        :disabled="!hasProcesos"
                        data-testid="procesos-select"
                        class="w-full bg-white border border-line text-accent font-bold text-sm rounded focus:border-accent-bright focus:outline-none px-3 py-1.5 font-mono disabled:opacity-50 cursor-pointer">
                    <option :value="null" disabled>
                        {{ hasProcesos ? "Selecciona un proceso…" : "No hay procesos cargados" }}
                    </option>
                    <option v-for="p in procesos" :key="p.uid" :value="p.uid">
                        {{ p.codigo }} — {{ p.nombre }}
                    </option>
                </select>
                <!-- Bloque legacy "UID X · DBs: DB3100_CPR_PARAM, DB5100_CPR_ALM"
                     eliminado: la información ya la muestra el selector de
                     procesos (uid + codigo) y los nombres de DB los computa
                     el use case internamente. No aportan valor al operario. -->

            </div>

            <!-- 2 cards: ¿Qué quieres hacer? -->
            <div class="bg-surface-raised border border-line rounded p-4">
                <h3 class="text-sm font-semibold text-ink mb-3">¿Qué quieres hacer?</h3>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">

                    <button @click="openCrearView"
                            :disabled="!canOpenCrear"
                            :title="crearCardTooltip"
                            data-testid="procesos-card-create"
                            class="bg-surface-raised border border-line rounded-lg p-3 text-left flex flex-col items-start transition hover:border-accent hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-line disabled:hover:shadow-none focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                        <span class="text-2xl mb-1" aria-hidden="true">🏗️</span>
                        <span class="text-sm font-semibold text-ink leading-snug">Crear proceso completo</span>
                        <span class="text-xs text-ink-muted mt-0.5 leading-snug">
                            Genera el DB + bloques + UDTs del proceso.
                        </span>
                    </button>

                    <button @click="openSyncView"
                            :disabled="!canOpenSync"
                            :title="syncCardTooltip"
                            data-testid="procesos-card-comments"
                            class="bg-surface-raised border border-line rounded-lg p-3 text-left flex flex-col items-start transition hover:border-accent hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-line disabled:hover:shadow-none focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                        <span class="text-2xl mb-1" aria-hidden="true">💬</span>
                        <span class="text-sm font-semibold text-ink leading-snug">Actualizar comentarios de DB</span>
                        <span class="text-xs text-ink-muted mt-0.5 leading-snug">
                            Sincroniza los comentarios de los DBs existentes.
                        </span>
                    </button>

                </div>
            </div>

            <!-- Card comun: una vista visible a la vez (sync XOR crear).
                 Los handlers openSyncView y openCrearView apagan
                 el flag de la otra antes de activar el propio,
                 asi que aqui solo necesitamos un v-if/v-else-if
                 por prioridad. -->
            <div v-if="showSyncView && selectedProc"
                 class="mt-4 bg-surface-raised border border-line rounded p-4"
                 data-testid="procesos-sync-inline-host">
                <procesos-sync-view
                    :proc-uid="selectedProcUid"
                    @close="closeSyncView">
                </procesos-sync-view>
            </div>

            <div v-else-if="showCrearView"
                 class="mt-4 bg-surface-raised border border-line rounded p-4"
                 data-testid="procesos-crear-inline-host">
                <procesos-crear-view
                    :proc-uid="selectedProcUid"
                    @close="closeCrearView">
                </procesos-crear-view>
            </div>

        </section>
    `,
};

