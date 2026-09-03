/**
 * Componente Welcome (pantalla de selección de área).
 *
 * Se muestra a pantalla completa cuando `store.topLevelView === 'welcome'`.
 * Pinta:
 *   * Logo corporativo gigante encapsulado en blanco.
 *   * Título "ZC Automation Suite" + subtítulo.
 *   * Grid de tarjetas blancas dinámicas (V1), una por cada área devuelta por `GET /api/v1/areas`.
 *   * Estados de carga, error (con reintento) y vacío adaptados al tema oscuro.
 *
 * Tema: Corporativo Zeus Control (Fondo Azul Marino #00205B, Tarjetas Blancas).
 *
 * IMPORTANTE sobre el template: el compilador de templates en runtime
 * de Vue 3 NO acepta string literals multi-línea dentro de arrays de `:class`.
 * Cada literal de clase debe ir en una sola línea.
 */
import { onMounted, ref } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "../store.js";
import { apiFetchAreas } from "../api.js";

export default {
    name: "Welcome",
    emits: ["select"],
    setup(_, { emit }) {
        const loading = ref(false);
        const error = ref(null);
        const fetched = ref(false);

        async function loadAreas() {
            loading.value = true;
            error.value = null;
            try {
                const r = await apiFetchAreas();
                if (r.ok && Array.isArray(r.data)) {
                    store.availableAreas = r.data;
                    fetched.value = true;
                } else if (r.ok && !Array.isArray(r.data)) {
                    store.availableAreas = [];
                    error.value = "Catálogo de áreas vacío o mal formado.";
                } else {
                    error.value = `No se pudo cargar el catálogo de áreas (HTTP ${r.status || "sin respuesta"}).`;
                    store.availableAreas = [];
                }
            } catch (e) {
                error.value = `Error inesperado: ${String(e)}`;
                store.availableAreas = [];
            } finally {
                loading.value = false;
            }
        }

        function handleSelect(area) {
            if (!area || !area.available) return;
            emit("select", area.key);
        }

        onMounted(() => {
            if (!fetched.value || store.availableAreas.length === 0) {
                loadAreas();
            }
        });

        return { store, loading, error, handleSelect, reload: loadAreas };
    },
    template: /* html */ `
        <section class="flex-1 w-full flex flex-col items-center justify-center bg-shell text-white p-6 md:p-12 overflow-y-auto">

            <div class="w-full max-w-6xl mx-auto flex flex-col items-center animate-fade-in-up">

                <!-- Cabecera Corporativa: el logo en card blanco se queda
                     como statement de marca del Welcome (único lugar
                     donde aparece la marca a pantalla completa). El
                     resto del chrome (cards de área, hover) se ha
                     alineado con la sobriedad del shell. -->
                <div class="text-center mb-6">
                    <div class="bg-white inline-block p-7 md:p-9 rounded-xl shadow-sm mb-10">
                        <img src="Logos Zeus Control.png" alt="Zeus Control" class="h-28 md:h-36 object-contain" onerror="this.src='/static/Logos Zeus Control.png'">
                    </div>

                    <h1 class="text-4xl md:text-5xl font-bold mb-4 tracking-tight text-white">ZC Automation Suite</h1>
                    <p class="text-on-shell-muted text-lg max-w-2xl mx-auto mb-2 font-light">Plataforma de Ingeniería, Sincronización y Generación de Código TIA Portal.</p>

                    <div class="flex items-center justify-center gap-4 mt-8 opacity-80">
                        <div class="h-px w-8 bg-white/30"></div>
                        <p class="text-on-shell-muted text-sm font-semibold tracking-widest uppercase">Selecciona un área para comenzar</p>
                        <div class="h-px w-8 bg-white/30"></div>
                    </div>
                </div>

                <!-- Estado: cargando -->
                <div v-if="loading" class="flex flex-col items-center justify-center mt-12" data-testid="welcome-loading">
                    <div class="w-10 h-10 border-4 border-on-shell-muted border-t-transparent rounded-full animate-spin mb-4"></div>
                    <p class="text-on-shell-muted font-medium tracking-widest uppercase text-sm">Sincronizando catálogo...</p>
                </div>

                <!-- Estado: error (rojo se mantiene — es estado de error,
                     no estilo general. Pero el rounded y la sombra
                     se alinean con el resto de la SPA). -->
                <div v-else-if="error" class="mt-12 bg-red-900/40 border border-red-500/50 rounded-lg p-7 max-w-lg w-full text-center shadow-md backdrop-blur-sm" data-testid="welcome-error">
                    <div class="text-5xl mb-4">⚠️</div>
                    <div class="font-bold text-red-200 text-xl mb-2">Error de conexión</div>
                    <div class="text-red-200/80 text-sm mb-8 leading-relaxed">{{ error }}</div>
                    <button @click="reload" class="px-7 py-2.5 bg-red-600 hover:bg-red-500 text-white font-semibold rounded-md transition-colors duration-150">
                        Reintentar conexión
                    </button>
                </div>

                <!-- Estado: catálogo cargado. Cards alineadas con la
                     sobriedad del shell: rounded-lg, shadow-sm,
                     border 1px, hover solo cambia border-color
                     (sin translate-y, sin shadow-2xl, sin scale).
                     Mismo lenguaje visual que AreaLanding. -->
                <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5 w-full mt-10" data-testid="welcome-grid">
                    <button v-for="a in store.availableAreas" :key="a.key"
                        @click="handleSelect(a)"
                        :disabled="!a.available"
                        :aria-label="'Acceder a ' + a.label"
                        :data-area-key="a.key"
                        :class="[
                            'bg-white text-left p-5 rounded-lg border border-line transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-white',
                            a.available ? 'hover:border-accent hover:shadow-lg cursor-pointer' : 'opacity-60 cursor-not-allowed grayscale'
                        ]">
                        <div class="text-3xl mb-3 text-accent">{{ a.icon }}</div>
                        <h3 class="text-shell font-bold text-lg mb-1">{{ a.label }}</h3>
                        <p class="text-ink-muted text-sm leading-relaxed">
                            {{ a.available ? (a.description || 'Acceder al panel de ingeniería.') : 'Módulo en desarrollo.' }}
                        </p>
                    </button>

                    <!-- Estado: catálogo vacío -->
                    <div v-if="store.availableAreas.length === 0" class="col-span-full text-center mt-4 p-8 border-2 border-dashed border-white/20 rounded-lg bg-white/5 backdrop-blur-sm">
                        <p class="text-on-shell-muted text-xl font-semibold mb-2">No hay áreas configuradas</p>
                        <p class="text-on-shell-faint text-sm">Verifica el catálogo del backend para habilitar los módulos.</p>
                    </div>
                </div>

                <!-- Footer -->
                <footer class="mt-16 text-on-shell-faint/60 text-xs font-mono tracking-widest text-center">
                    v1.0.0 • Zeus Control
                </footer>

            </div>
        </section>
    `,
};