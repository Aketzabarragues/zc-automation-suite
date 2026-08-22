/**
 * Componente Welcome (pantalla de selección de área).
 *
 * Se muestra a pantalla completa cuando ``store.topLevelView ===
 * 'welcome'``. Pinta:
 *   * Logo placeholder monograma "ZC" (acento) en grande.
 *   * Título "ZC Automation Suite" + subtítulo.
 *   * Grid de tarjetas, una por cada área devuelta por
 *     ``GET /api/v1/areas``.
 *   * Estados de carga, error (con reintento) y vacío.
 *
 * Tema: Industrial Claro. Solo tokens semánticos del tema
 * (``bg-surface``, ``bg-surface-raised``, ``text-ink``, ``border-line``,
 * ``bg-accent``, ``text-accent``). Excepción: ``text-red-600`` para
 * el error, convención ya aceptada en ``ConsolaLogs.js``.
 *
 * El componente NO muta ``store.topLevelView`` directamente: emite
 * el evento ``select`` con la ``key`` del área y deja que el
 * componente raíz (``main.js``) decida cómo enrutar. Esto mantiene
 * ``Welcome`` como componente "tonto" y testeable de forma aislada.
 *
 * IMPORTANTE sobre el template: el compilador de templates en runtime
 * de Vue 3 (``vue.esm-browser.prod.js``) NO acepta string literals
 * multi-línea dentro de arrays de ``:class``. Cada literal de clase
 * debe ir en una sola línea; los saltos de línea entre clases
 * consecutivas son válidos, pero NO dentro de un mismo literal.
 */
import { onMounted, ref } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store } from "../store.js";
import { apiFetchAreas } from "../api.js";

export default {
    name: "Welcome",
    emits: ["select"],
    setup(_, { emit }) {
        /** Flag local de carga. NO se eleva al store (estado de UI puro). */
        const loading = ref(false);
        /** Mensaje de error a mostrar o ``null``. */
        const error = ref(null);
        /** Catálogo en estado de carga (por si el usuario hace "Volver" antes del primer fetch). */
        const fetched = ref(false);

        /**
         * Carga el catálogo desde el backend. Defensivo: si el
         * endpoint falla, deja ``error`` con un mensaje y un botón
         * "Reintentar" lo vuelve a llamar.
         */
        async function loadAreas() {
            loading.value = true;
            error.value = null;
            try {
                const r = await apiFetchAreas();
                if (r.ok && Array.isArray(r.data)) {
                    store.availableAreas = r.data;
                    fetched.value = true;
                } else if (r.ok && !Array.isArray(r.data)) {
                    // 200 con body no-array: defensivo, no es contrato.
                    store.availableAreas = [];
                    error.value =
                        "Catálogo de áreas vacío o mal formado.";
                } else {
                    error.value = `No se pudo cargar el catálogo de áreas (HTTP ${r.status || "sin respuesta"}).`;
                    store.availableAreas = [];
                }
            } catch (e) {
                // _request ya traga la excepción y retorna {ok:false},
                // pero cubrimos el caso improbable de un throw externo.
                error.value = `Error inesperado: ${String(e)}`;
                store.availableAreas = [];
            } finally {
                loading.value = false;
            }
        }

        /**
         * Manejador del clic en una tarjeta. Si el área está
         * ``available``, emite ``select`` con la ``key``. Si no, es
         * no-op (el botón está ``disabled`` en el template, pero
         * revalidamos por seguridad).
         */
        function handleSelect(area) {
            if (!area || !area.available) return;
            emit("select", area.key);
        }

        onMounted(() => {
            // Solo pedimos al backend si aún no tenemos datos cacheados
            // (caso: el usuario hace "Volver" y vuelve a entrar).
            if (!fetched.value || store.availableAreas.length === 0) {
                loadAreas();
            }
        });

        return { store, loading, error, handleSelect, reload: loadAreas };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col items-center justify-center bg-surface text-ink p-8 overflow-y-auto">
            <!-- Logo placeholder + título -->
            <div class="mb-10 flex flex-col items-center">
                <div class="w-24 h-24 rounded-2xl bg-accent text-ink-inverse flex items-center justify-center text-4xl font-bold tracking-widest shadow-md select-none">
                    ZC
                </div>
                <h1 class="mt-4 text-3xl font-bold text-ink">ZC Automation Suite</h1>
                <p class="mt-1 text-sm text-ink-muted">Selecciona un área para comenzar</p>
            </div>

            <!-- Estado: cargando -->
            <div v-if="loading" class="text-ink-muted text-sm" data-testid="welcome-loading">
                Cargando áreas…
            </div>

            <!-- Estado: error -->
            <div v-else-if="error"
                 class="bg-surface-raised border border-line rounded-md p-4 max-w-md w-full text-sm text-red-600"
                 data-testid="welcome-error">
                <div class="font-semibold mb-1">No se pudo cargar el catálogo</div>
                <div class="text-ink-muted mb-3">{{ error }}</div>
                <button @click="reload" class="text-xs px-3 py-1.5 bg-accent hover:bg-accent-hover rounded text-ink-inverse">
                    Reintentar
                </button>
            </div>

            <!-- Estado: catálogo cargado -->
            <div v-else
                 class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 w-full max-w-4xl"
                 data-testid="welcome-grid">
                <button v-for="a in store.availableAreas" :key="a.key"
                    @click="handleSelect(a)"
                    :disabled="!a.available"
                    :aria-label="'Acceder a ' + a.label"
                    :data-area-key="a.key"
                    :class="['flex flex-col items-start p-6 rounded-xl border-2 text-left transition shadow-sm',
                             a.available ? 'bg-surface-raised border-line hover:border-accent hover:shadow-md cursor-pointer' : 'bg-surface-sunken border-line opacity-50 cursor-not-allowed']">
                    <span class="text-3xl mb-2" aria-hidden="true">{{ a.icon }}</span>
                    <span class="text-lg font-semibold text-ink">{{ a.label }}</span>
                    <span class="text-xs text-ink-muted mt-1">
                        {{ a.available ? (a.description || 'Acceder') : 'Próximamente' }}
                    </span>
                </button>

                <!-- Estado: catálogo vacío (sin áreas configuradas) -->
                <div v-if="store.availableAreas.length === 0"
                     class="col-span-full text-center text-ink-muted text-sm py-8">
                    No hay áreas configuradas.
                    <br/>Añade un bloque <code>departments</code> en
                    <code>infrastructure/config.json</code>.
                </div>
            </div>

            <footer class="mt-12 text-xs text-ink-muted">
                v1.0 · ZC Automation
            </footer>
        </section>
    `,
};
