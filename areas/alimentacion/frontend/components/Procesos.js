/**
 * Componente Procesos.
 *
 * Sub-vista de primer nivel del área "alimentacion" que se muestra
 * cuando ``store.currentView === 'proc'``. Es el primer paso (UI
 * solamente) de la funcionalidad de "generación de procesos en
 * TIA Portal" anunciada en el plan canónico
 * ``_plan/04_excel_cache_phased_plan.md`` (Fase 6, extensión).
 *
 * Estructura:
 *   1. Cabecera: icono + título + descripción corta.
 *   2. Banner ámbar si NO hay Excel cargado o si
 *      ``store.memoryState.procesos`` está vacío.
 *   3. Selector de proceso (``<select>`` con
 *      ``store.memoryState.procesos``). Cada item muestra
 *      ``codigo`` y ``nombre``. Sub-caption con UID y los 3 nombres
 *      simbólicos de DB (``db_preal_nombre``, ``db_pint_nombre``,
 *      ``db_alm_nombre``) — properties derivadas del DTO
 *      ``ProcesoPLC`` (``areas/alimentacion/domain/models/excel_cache.py``).
 *   4. 2 cards placeholder ("Crear proceso completo" /
 *      "Actualizar comentarios de DB") deshabilitadas hasta que el
 *      operario seleccione un proceso. ``@click`` que hace
 *      ``alert("TODO: …")`` — la lógica real vendrá en una segunda
 *      fase, cuando se decida el diseño UX de cada acción.
 *
 * Decisiones de diseño:
 *   - Estado local: ``selectedProcUid`` como ``ref``. No se mete en
 *     ``store.js`` — se resetea al desmontar el componente (al
 *     navegar a otra sub-vista).
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
import { computed, ref } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
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

        return {
            procesos,
            hasExcel,
            hasProcesos,
            selectedProcUid,
            selectedProc,
            canAct,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col overflow-hidden">

            <!-- Cabecera: icono + título + descripción corta -->
            <header class="mb-4">
                <h2 class="text-lg font-bold text-ink">⚙️ Procesos</h2>
                <p class="text-xs text-ink-muted mt-0.5">
                    Generación y mantenimiento de procesos en TIA Portal.
                </p>
            </header>

            <!-- Banner ámbar: cubre los 2 casos "no operable" del flujo.
                 Aparece cuando NO hay Excel cargado O cuando el
                 Excel existe pero su hoja de procesos está vacía. -->
            <div v-if="!hasExcel || !hasProcesos"
                 class="mb-4 px-3 py-2 bg-amber-100 border border-amber-300 rounded text-xs text-amber-800">
                <span v-if="!hasExcel">
                    ⚠️ No hay Excel cargado. Sube un Excel y pulsa
                    <strong class="text-accent">"Refrescar Memoria"</strong>
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
                        class="w-full bg-surface-sunken border border-line rounded px-2 py-1.5 text-sm text-ink disabled:opacity-50">
                    <option :value="null" disabled>
                        {{ hasProcesos ? "Selecciona un proceso…" : "No hay procesos cargados" }}
                    </option>
                    <option v-for="p in procesos" :key="p.uid" :value="p.uid">
                        {{ p.codigo }} — {{ p.nombre }}
                    </option>
                </select>
                <!-- Sub-caption con UID y los 3 nombres simbólicos de
                     DB del proceso. Usa las properties derivadas del
                     DTO ProcesoPLC (db_preal_nombre, etc.). Si
                     el backend aún no las expone, los nombres
                     aparecen vacíos y la UI no rompe. -->
                <p v-if="selectedProc"
                   class="mt-2 text-xs text-ink-muted">
                    UID <span class="font-mono">{{ selectedProc.uid }}</span>
                    · DBs:
                    <span class="font-mono">{{ selectedProc.db_preal_nombre }}</span>,
                    <span class="font-mono">{{ selectedProc.db_pint_nombre }}</span>,
                    <span class="font-mono">{{ selectedProc.db_alm_nombre }}</span>
                </p>
            </div>

            <!-- 2 cards: ¿Qué quieres hacer?
                 Cards placeholder. El @click muestra un alert
                 informativo. La lógica real (use case + endpoint +
                 progress tracker) vendrá en una segunda fase. -->
            <div class="bg-surface-raised border border-line rounded p-4">
                <h3 class="text-sm font-semibold text-ink mb-3">¿Qué quieres hacer?</h3>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">

                    <button @click="alert('TODO: Crear proceso completo')"
                            :disabled="!canAct"
                            data-testid="procesos-card-create"
                            class="bg-surface border-2 border-line rounded-xl p-4 text-left flex flex-col items-start transition hover:border-accent hover:shadow-md disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-line disabled:hover:shadow-none">
                        <span class="text-3xl mb-2" aria-hidden="true">🏗️</span>
                        <span class="text-sm font-semibold text-ink">Crear proceso completo</span>
                        <span class="text-xs text-ink-muted mt-1">
                            Genera el DB + bloques + UDTs del proceso.
                        </span>
                    </button>

                    <button @click="alert('TODO: Actualizar comentarios de DB')"
                            :disabled="!canAct"
                            data-testid="procesos-card-comments"
                            class="bg-surface border-2 border-line rounded-xl p-4 text-left flex flex-col items-start transition hover:border-accent hover:shadow-md disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-line disabled:hover:shadow-none">
                        <span class="text-3xl mb-2" aria-hidden="true">💬</span>
                        <span class="text-sm font-semibold text-ink">Actualizar comentarios de DB</span>
                        <span class="text-xs text-ink-muted mt-1">
                            Sincroniza los comentarios de los DBs existentes.
                        </span>
                    </button>

                </div>
            </div>

        </section>
    `,
};
