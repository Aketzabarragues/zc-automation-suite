/**
 * Componente AreaLanding — pantalla de aterrizaje del área Alimentación.
 *
 * Se muestra cuando ``store.currentView === 'landing'``. Ofrece dos
 * tarjetas (una por sub-vista del área) para que el usuario elija
 * dónde quiere entrar. Replica el patrón visual del Welcome global.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``bg-accent``,
 * ``text-accent``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 *
 * @event select  Emite la ``key`` de la sub-vista elegida
 *                (``'def'`` o ``'disp'``). El componente padre
 *                (``main.js``) llama a ``goToSubview(key)``.
 */
import { computed } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
// Import absoluto: ver nota en ``Sidebar.js``. Los cross-cutting
// están en ``/js/``, no se mueven.
import { store } from "/js/store.js";

/**
 * Sub-vistas disponibles en el área Alimentación. Si en el futuro
 * llega una segunda área con sub-vistas distintas, este componente
 * será específico de Alimentación o se parametrizará.
 */
const SUBVIEW_OPTIONS = [
    {
        key: "def",
        icon: "📊",
        label: "Definición programación",
        description: "Carga el maestro Excel y consulta la AppState del PLC.",
    },
    {
        key: "disp",
        icon: "⚡",
        label: "Dispositivos",
        description: "Previsualiza y aplica cambios en TIA Portal.",
    },
];

export default {
    name: "AlimentacionAreaLanding",
    emits: ["select"],
    setup(_, { emit }) {
        /**
         * Etiqueta del área activa, derivada del catálogo. Fallback
         * al ``key`` crudo si no se encuentra en el catálogo.
         */
        const areaLabel = computed(() => {
            if (!store.selectedArea) return "—";
            const a = store.availableAreas.find(
                (x) => x.key === store.selectedArea
            );
            return a ? a.label : store.selectedArea;
        });

        /**
         * Icono del área activa, derivado del catálogo. Fallback al
         * emoji genérico de "carpeta" si no se encuentra.
         */
        const areaIcon = computed(() => {
            if (!store.selectedArea) return "📁";
            const a = store.availableAreas.find(
                (x) => x.key === store.selectedArea
            );
            return (a && a.icon) || "📁";
        });

        /**
         * Click en una tarjeta. Emite la ``key`` al padre; el padre
         * se encarga de llamar a ``goToSubview``.
         */
        function handleSelect(key) {
            if (!key) return;
            emit("select", key);
        }

        return {
            store,
            areaLabel,
            areaIcon,
            options: SUBVIEW_OPTIONS,
            handleSelect,
        };
    },
    template: /* html */ `
        <section class="flex-1 flex flex-col items-center justify-center bg-surface text-ink p-8 overflow-y-auto">

            <!-- Encabezado del área (leído del catálogo) -->
            <div class="mb-10 flex flex-col items-center">
                <div class="w-24 h-24 rounded-2xl bg-accent text-ink-inverse flex items-center justify-center text-4xl font-bold tracking-widest shadow-md select-none">
                    {{ areaIcon }}
                </div>
                <h1 class="mt-4 text-3xl font-bold text-ink">{{ areaLabel }}</h1>
                <p class="mt-1 text-sm text-ink-muted">¿Qué quieres hacer?</p>
            </div>

            <!-- Grid de 2 tarjetas (una por sub-vista) -->
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full max-w-4xl"
                 data-testid="area-landing-grid">
                <button v-for="opt in options" :key="opt.key"
                    @click="handleSelect(opt.key)"
                    :data-area-key="opt.key"
                    :aria-label="'Acceder a ' + opt.label"
                    class="bg-surface-raised border-2 border-line hover:border-accent hover:shadow-md rounded-xl p-6 text-left flex flex-col items-start transition shadow-sm">
                    <span class="text-3xl mb-2" aria-hidden="true">{{ opt.icon }}</span>
                    <span class="text-lg font-semibold text-ink">{{ opt.label }}</span>
                    <span class="text-xs text-ink-muted mt-1">{{ opt.description }}</span>
                    <span class="text-accent text-sm mt-3 font-semibold">Abrir →</span>
                </button>
            </div>

        </section>
    `,
};
