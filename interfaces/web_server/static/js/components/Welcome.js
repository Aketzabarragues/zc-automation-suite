// ============================================================================
// Welcome.js — Pantalla de seleccion de area (HMI pasivo, Fase 3).
//
//  Clonado del legacy (`legacy_backup/interfaces/web_server/static/js/
//  components/Welcome.js`) y adaptado al composable `usePlc()`:
//    - `import { store } from "/js/store.js"`  → `usePlc()`
//    - `store.availableAreas`                  → `plc.areas`
//    - `apiFetchAreas()`                       → `plc.fetchAreas()`
//    - `loadAreas()` interno: ya no toca el store; rellena
//      `plc.areas` (que el composable actualiza via `fetchAreas`).
//
//  Comportamiento: muestra el grid de areas cargadas por
//  `GET /api/v1/areas`. Si el catalogo esta vacio o el endpoint
//  no existe, muestra el empty state (`EmptyState`) con accion
//  "Reintentar".
//
//  Regla Vue 3 sin build step: el template solo lee variables
//  planas del `setup()`. Acceso a `plc.areas` se hace via
//  `computed`.
//
//  Tema: capa "Industrial Claro". Solo tokens semanticos.
// ============================================================================

import { computed, onMounted, ref } from "/js/vendor/vue.esm-browser.prod.js";
import { usePlc } from "/js/composables/usePlc.js";
import EmptyState from "/js/components/EmptyState.js";

export default {
    name: "Welcome",
    components: { EmptyState },
    emits: ["select"],
    setup(_, { emit }) {
        const plc = usePlc();

        const loading = ref(false);
        const error = ref(null);
        const fetched = ref(false);

        /**
         * Catalogo reactivo derivado del composable. Como `plc.areas`
         * es un `reactive` de Vue 3, leerlo en un `computed` basta
         * para que el template se re-renderice cuando llegue el
         * resultado de `fetchAreas()`.
         */
        const areas = computed(() => plc.areas);

        async function loadAreas() {
            loading.value = true;
            error.value = null;
            try {
                const r = await plc.fetchAreas();
                if (r.ok && Array.isArray(r.data)) {
                    fetched.value = true;
                    error.value = null;
                } else if (r.ok && !Array.isArray(r.data)) {
                    // Respuesta 200 OK pero sin array: malformado.
                    error.value = "Catalogo de areas vacio o mal formado.";
                } else {
                    error.value = `No se pudo cargar el catalogo de areas (HTTP ${r.status || "sin respuesta"}).`;
                }
            } catch (e) {
                error.value = `Error inesperado: ${String(e)}`;
            } finally {
                loading.value = false;
            }
        }

        function handleSelect(area) {
            if (!area || !area.available) return;
            emit("select", area.key);
        }

        function reload() {
            return loadAreas();
        }

        onMounted(() => {
            if (!fetched.value || areas.value.length === 0) {
                loadAreas();
            }
        });

        return {
            areas,
            loading,
            error,
            handleSelect,
            reload,
        };
    },
    template: /* html */ `
        <section
            class="flex-1 w-full flex flex-col items-center justify-center bg-surface text-ink p-6 md:p-12 overflow-y-auto"
            data-testid="welcome">

            <div class="w-full max-w-6xl mx-auto flex flex-col items-center">

                <!-- Cabecera -->
                <div class="text-center mb-6">
                    <div class="bg-white inline-block p-7 md:p-9 rounded-xl shadow-sm mb-10">
                        <img
                            src="Logos Zeus Control.png"
                            alt="Zeus Control"
                            class="h-28 md:h-36 object-contain"
                            onerror="this.src='/static/Logos Zeus Control.png'">
                    </div>
                    <h1 class="text-4xl md:text-5xl font-bold mb-4 tracking-tight text-ink">
                        Zeus Control
                    </h1>
                    <p class="text-ink-muted text-lg max-w-2xl mx-auto mb-2 font-light">
                        Plataforma de Ingenieria, Sincronizacion y Generacion de Codigo TIA Portal.
                    </p>
                    <div class="flex items-center justify-center gap-4 mt-8 opacity-80">
                        <div class="h-px w-8 bg-line"></div>
                        <p class="text-ink-muted text-sm font-semibold tracking-widest uppercase">
                            Selecciona un area para comenzar
                        </p>
                        <div class="h-px w-8 bg-line"></div>
                    </div>
                </div>

                <!-- Estado: cargando -->
                <div
                    v-if="loading"
                    class="flex flex-col items-center justify-center mt-12"
                    data-testid="welcome-loading">
                    <div class="w-10 h-10 border-4 border-ink-muted border-t-transparent rounded-full animate-spin mb-4"></div>
                    <p class="text-ink-muted font-medium tracking-widest uppercase text-sm">
                        Sincronizando catalogo...
                    </p>
                </div>

                <!-- Estado: error (reintento) -->
                <div
                    v-else-if="error"
                    class="mt-12 w-full max-w-lg"
                    data-testid="welcome-error">
                    <EmptyState
                        icon="⚠️"
                        title="Error de conexion"
                        :description="error"
                        action-label="Reintentar conexion"
                        size="md"
                        @action="reload" />
                </div>

                <!-- Estado: catalogo cargado (o vacio) -->
                <div
                    v-else
                    class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5 w-full mt-10"
                    data-testid="welcome-grid">
                    <button
                        v-for="a in areas"
                        :key="a.key"
                        @click="handleSelect(a)"
                        :disabled="!a.available"
                        :aria-label="'Acceder a ' + a.label"
                        :data-area-key="a.key"
                        :class="[
                            'bg-white text-left p-5 rounded-lg border border-line transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-white',
                            a.available ? 'hover:border-accent hover:shadow-lg cursor-pointer' : 'opacity-60 cursor-not-allowed grayscale'
                        ]">
                        <div class="text-3xl mb-3 text-accent">{{ a.icon }}</div>
                        <h3 class="text-ink font-bold text-lg mb-1">{{ a.label }}</h3>
                        <p class="text-ink-muted text-sm leading-relaxed">
                            {{
                                a.available
                                    ? (a.description || "Acceder al panel de ingenieria.")
                                    : "Modulo en desarrollo."
                            }}
                        </p>
                    </button>

                    <!-- Empty state: sin areas configuradas -->
                    <div
                        v-if="areas.length === 0"
                        class="col-span-full w-full mt-4">
                        <EmptyState
                            icon="📂"
                            title="No hay areas configuradas"
                            description="Verifica el catalogo del backend para habilitar los modulos."
                            size="md" />
                    </div>
                </div>

                <footer class="mt-16 text-ink-muted text-xs font-mono tracking-widest text-center">
                    v1.0.0 • Zeus Control
                </footer>
            </div>
        </section>
    `,
};
