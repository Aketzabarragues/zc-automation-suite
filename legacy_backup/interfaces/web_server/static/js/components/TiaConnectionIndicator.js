/**
 * Componente TiaConnectionIndicator.
 *
 * Círculo de estado del worker TIA persistente (PR 5b / §4.2 del
 * design doc) que vive en el ``ShellTopbar``. Muestra el estado
 * de conexión con TIA Portal con un código de colores:
 *
 *   - verde   (bg-green-500)            → ``connected``
 *   - ámbar   (bg-amber-500 animate-pulse) → ``connecting``
 *   - gris    (bg-gray-400)             → ``idle``
 *   - rojo    (bg-red-500)              → ``error``
 *
 * Tras el refactor de state machine (sept-2026) los 4 estados
 * estables son ``idle | connecting | connected | error`` (el
 * antiguo ``disconnected`` desaparece: el worker arranca en
 * ``idle``, subproceso vivo SIN portal attached; el operario
 * decide cuándo pulsar "Conectar" del topbar para transicionar
 * a ``connecting`` -> ``connected``).
 *
 * Tooltip con info del proyecto cuando está conectado (nombre,
 * path, nº PLCs, versión de TIA). Clickable para reconectar
 * cuando el estado es ``idle`` o ``error``: emite el
 * evento ``"connect"`` y el handler del ``ShellTopbar`` se
 * encarga de llamar a ``store.connectTia()``.
 *
 * REGLA CRÍTICA Vue 3 sin build step (ver AGENTS.md §"Vue 3 sin
 * build step"): el template NO tiene acceso directo a ``store``
 * (los ``import`` a nivel de módulo son invisibles para el
 * compilador en runtime). Por eso TODO el acceso a ``store`` se
 * encapsula en ``computed`` y se retorna explícitamente desde
 * ``setup()``. El template solo lee ``state``, ``project``,
 * ``colorClass``, ``tooltip``, ``stateLabel`` y ``handleClick``.
 *
 * Tema: tokens semánticos del tema "Industrial Claro" cuando
 * apliquen. Los colores de estado (green/amber/gray/red) son
 * clases utilitarias de Tailwind v4 que el input.css del repo
 * ya recoge (el glob de @source cubre cualquier .js bajo
 * ``../js/``, incluido este archivo). Tras añadir
 * ``bg-green-500``, ``bg-amber-500``, ``bg-gray-400``,
 * ``bg-red-500`` y ``animate-pulse`` a las clases existentes,
 * basta con recompilar Tailwind (``run_tailwind.bat``).
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

// Mapping de ``state`` a etiqueta en castellano para el
// ``aria-label`` del botón (sept-2026, armonización de textos).
// El operario ve "Estado TIA: Conectado" en vez del state crudo
// en inglés ("connected", "idle", "connecting", "error"). Si el
// state es desconocido, ``stateLabel`` cae al state crudo como
// fallback (defensivo, no rompe la SPA).
const STATE_LABELS = {
    connected: "Conectado",
    connecting: "Conectando",
    idle: "En reposo",
    error: "Error",
};

export default {
    name: "TiaConnectionIndicator",
    emits: ["connect"],
    setup(_, { emit }) {
        // Acceso a store encapsulado en ``computed`` (regla Vue 3
        // sin build step). El template los lee como variables
        // planas; nunca como ``store.tiaConnection.state``.
        // Default: "idle" (estado del worker persistente recien
        // arrancado, sin attach a TIA Portal). Coincide con el
        // estado inicial del ``store.tiaConnection`` declarado
        // en ``store.js`` y con el que el backend expone en
        // ``GET /api/v1/tia/connection`` antes del primer
        // "Conectar" del operario.
        const state = computed(() =>
            (store.tiaConnection && store.tiaConnection.state) || "idle"
        );
        // ``stateLabel`` (sept-2026, armonización textos):
        // versión en castellano de ``state`` para el
        // ``aria-label`` del botón. Lee del mapping
        // ``STATE_LABELS`` y cae al state crudo si el mapping
        // no lo contempla (defensivo, no rompe la SPA si en
        // el futuro se añade un state nuevo al state machine).
        const stateLabel = computed(
            () => STATE_LABELS[state.value] || state.value
        );
        const project = computed(() =>
            (store.tiaConnection && store.tiaConnection.project) || null
        );
        const error = computed(() =>
            (store.tiaConnection && store.tiaConnection.last_error) || null
        );
        const plcs = computed(() =>
            (store.tiaConnection && Array.isArray(store.tiaConnection.plcs)
                ? store.tiaConnection.plcs
                : [])
        );

        /**
         * Clase utilitaria de Tailwind que pinta el círculo según
         * el estado. ``animate-pulse`` se añade solo en
         * ``connecting`` para que el operario perciba que algo
         * está en curso (el cold-attach puede tardar 5-30s).
         *
         * Switch de 4 ramas (state machine sept-2026):
         * ``idle | connecting | connected | error``. ``idle`` y
         * el default comparten ``bg-gray-400`` (gris neutro, sin
         * attach a TIA pero con worker vivo).
         */
        const colorClass = computed(() => {
            switch (state.value) {
                case "connected":
                    return "bg-green-500";
                case "connecting":
                    return "bg-amber-500 animate-pulse";
                case "idle":
                    return "bg-gray-400";
                case "error":
                    return "bg-red-500";
                default:
                    return "bg-gray-400";
            }
        });

        /**
         * Texto del tooltip (``title`` HTML). Multilínea con
         * ``\n``: el navegador lo renderiza como varias líneas
         * nativas. En ``connected`` muestra nombre + path + nº
         * PLCs + versión de TIA. En ``error`` muestra el mensaje.
         * En ``idle`` invita a pulsar "Conectar" del topbar.
         */
        const tooltip = computed(() => {
            if (state.value === "connected" && project.value) {
                const np = plcs.value.length || 0;
                const version = project.value.version
                    ? `TIA ${project.value.version}`
                    : "TIA";
                return [
                    project.value.name || "(sin nombre)",
                    project.value.path || "",
                    `PLCs: ${np}`,
                    version,
                ].join("\n");
            }
            if (state.value === "error") {
                return `Error: ${error.value || "desconocido"}`;
            }
            if (state.value === "idle") {
                return "TIA en reposo. Pulsa 'Conectar' para abrir un portal.";
            }
            if (state.value === "connecting") {
                // Texto armonizado sept-2026: explicito "con TIA
                // Portal" en vez del generico "Conectando...". Da
                // contexto al operario (es uno de los dos
                // indicadores del topbar, y este se refiere al
                // attach, no al worker OT).
                return "Conectando con TIA Portal...";
            }
            return "Estado TIA desconocido";
        });

        /**
         * Handler del click. Solo emite ``"connect"`` cuando el
         * estado es accionable (``idle`` o ``error``);
         * en ``connected`` y ``connecting`` el click es un no-op
         * para evitar reconexiones espurias. (``connecting``
         * esta protegido a nivel de ShellTopbar: el boton
         * "Conectar" no se muestra en ese estado, asi que el
         * operario no puede dispararlo dos veces.)
         */
        function handleClick() {
            if (state.value === "idle" || state.value === "error") {
                emit("connect");
            }
        }

        return { state, project, colorClass, tooltip, stateLabel, handleClick };
    },
    template: /* html */ `
        <button
            type="button"
            @click="handleClick"
            :title="tooltip"
            :class="['w-3 h-3 rounded-full', colorClass, 'transition-colors']"
            :aria-label="'Estado TIA: ' + stateLabel"
            data-testid="tia-connection-indicator">
        </button>
    `,
};
