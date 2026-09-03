/**
 * Componente AreaLanding — pantalla de aterrizaje del área Alimentación.
 *
 * Se muestra cuando ``store.currentView === 'landing'``. Presenta
 * las sub-vistas del área como una **lista vertical** de filas
 * horizontales (icono | contenido | "Abrir →"), inspirada en el
 * demo de Gemini ``_source/modo_lista.html``. El formato lista
 * escala mejor que el grid anterior cuando el operario trabaja
 * en monitores anchos (más espacio horizontal por item, sin
 * truncamientos de descripción) y la CTA "Abrir →" queda siempre
 * visible a la derecha.
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
 *                (``'def'`` | ``'disp'`` | ``'cache'`` | ``'proc'``).
 *                El componente padre (``main.js``) llama a
 *                ``goToSubview(key)``.
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
// Import absoluto: ver nota en ``Sidebar.js``. Los cross-cutting
// están en ``/js/``, no se mueven.
import { store } from "/js/store.js";

/**
 * Sub-vistas disponibles en el área Alimentación. Si en el futuro
 * llega una segunda área con sub-vistas distintas, este componente
 * será específico de Alimentación o se parametrizará.
 *
 * Las 4 keys (``def``, ``disp``, ``cache``, ``proc``) coinciden
 * con las declaradas en ``manifest.js`` (``views`` del área) y en
 * ``store.areaManifest.components.views`` que el backend publica
 * en ``GET /api/v1/areas/alimentacion/manifest``.
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
    {
        key: "cache",
        icon: "🗃️",
        label: "Cache del PLC",
        description: "Volcado de bloques del PLC (DBs, FCs, UDTs) cacheado en memoria.",
    },
    {
        key: "proc",
        icon: "⚙️",
        label: "Procesos",
        description: "Genera procesos en TIA Portal (crear / actualizar comentarios).",
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
         * emoji genérico de "carpeta" (📁) si el catálogo no trae
         * uno. Se usa en el badge del encabezado para dar identidad
         * visual al área aunque no tenga icono propio (consistente
         * con el demo de ``modo_lista.html``).
         */
        const areaIcon = computed(() => {
            if (!store.selectedArea) return "📁";
            const a = store.availableAreas.find(
                (x) => x.key === store.selectedArea
            );
            return (a && a.icon) || "📁";
        });

        /**
         * Click en una fila. Emite la ``key`` al padre; el padre
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
        <section class="flex-1 flex flex-col items-center bg-surface text-ink pt-10 pb-8 px-8 overflow-y-auto">

            <!-- Encabezado del área: badge de icono + título + subtítulo.
                 El badge usa el icono del catálogo (con fallback a 📁)
                 sobre fondo accent para dar identidad visual al área. -->
            <div class="mb-6 text-center">
                <div class="w-12 h-12 bg-accent rounded-xl mx-auto mb-3 flex items-center justify-center shadow-sm border border-shell-border select-none">
                    <span class="text-xl text-ink-inverse" aria-hidden="true">{{ areaIcon }}</span>
                </div>
                <h1 class="text-2xl font-bold text-ink tracking-tight">{{ areaLabel }}</h1>
                <p class="text-sm text-ink-muted mt-1 font-normal">¿Qué quieres hacer?</p>
            </div>

            <!-- Lista vertical de acciones (modo lista). Cada fila es
                 un botón horizontal: icono (cuadrado sunken) | contenido
                 (título + descripción) | CTA "Abrir →" (pill accent).
                 max-w-3xl (~48rem) limita el ancho para legibilidad en
                 monitores grandes; en móvil ocupa todo el ancho. -->
            <div class="flex flex-col gap-2 w-full max-w-3xl"
                 data-testid="area-landing-list">
                <button v-for="opt in options" :key="opt.key"
                    @click="handleSelect(opt.key)"
                    :data-area-key="opt.key"
                    :aria-label="'Acceder a ' + opt.label"
                    class="bg-surface-raised border border-line rounded-lg p-3 text-left hover:border-accent hover:shadow-lg transition-all duration-200 group flex items-center gap-4 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    <div class="w-10 h-10 bg-surface-sunken rounded-lg flex items-center justify-center text-xl shrink-0 group-hover:bg-accent-subtle group-hover:scale-105 transition-all border border-line shadow-sm">
                        <span aria-hidden="true">{{ opt.icon }}</span>
                    </div>
                    <div class="flex-1 min-w-0">
                        <h3 class="text-base font-semibold text-ink mb-0.5 leading-snug">{{ opt.label }}</h3>
                        <p class="text-xs text-ink-muted leading-snug truncate">{{ opt.description }}</p>
                    </div>
                    <div class="shrink-0 px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken group-hover:bg-accent-subtle rounded-md transition-colors border border-line flex items-center gap-1.5">
                        Abrir <span class="text-base leading-none transition-transform group-hover:translate-x-1" aria-hidden="true">→</span>
                    </div>
                </button>
            </div>

        </section>
    `,
};
