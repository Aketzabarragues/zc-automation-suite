/**
 * Componente TiaConnectionIndicator.
 *
 * Círculo de estado del worker TIA persistente (PR 5b / §4.2 del
 * design doc) que vive en el ``ShellTopbar``. Muestra el estado
 * de conexión con TIA Portal con un código de colores:
 *
 *   - verde   (bg-green-500)            → ``connected``
 *   - ámbar   (bg-amber-500 animate-pulse) → ``connecting``
 *   - gris    (bg-gray-400)             → ``disconnected``
 *   - rojo    (bg-red-500)              → ``error``
 *
 * Tooltip con info del proyecto cuando está conectado (nombre,
 * path, nº PLCs, versión de TIA). Clickable para reconectar
 * cuando el estado es ``disconnected`` o ``error``: emite el
 * evento ``"connect"`` y el handler del ``ShellTopbar`` se
 * encarga de llamar a ``store.connectTia()``.
 *
 * REGLA CRÍTICA Vue 3 sin build step (ver AGENTS.md §"Vue 3 sin
 * build step"): el template NO tiene acceso directo a ``store``
 * (los ``import`` a nivel de módulo son invisibles para el
 * compilador en runtime). Por eso TODO el acceso a ``store`` se
 * encapsula en ``computed`` y se retorna explícitamente desde
 * ``setup()``. El template solo lee ``state``, ``project``,
 * ``colorClass``, ``tooltip`` y ``handleClick``.
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

export default {
    name: "TiaConnectionIndicator",
    emits: ["connect"],
    setup(_, { emit }) {
        // Acceso a store encapsulado en ``computed`` (regla Vue 3
        // sin build step). El template los lee como variables
        // planas; nunca como ``store.tiaConnection.state``.
        const state = computed(() =>
            (store.tiaConnection && store.tiaConnection.state) || "disconnected"
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
         */
        const colorClass = computed(() => {
            switch (state.value) {
                case "connected":
                    return "bg-green-500";
                case "connecting":
                    return "bg-amber-500 animate-pulse";
                case "disconnected":
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
         * En ``disconnected`` invita a pulsar para reconectar.
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
            if (state.value === "disconnected") {
                return "TIA desconectado. Pulsa para reconectar.";
            }
            if (state.value === "connecting") {
                return "Conectando...";
            }
            return "Estado TIA desconocido";
        });

        /**
         * Handler del click. Solo emite ``"connect"`` cuando el
         * estado es accionable (``disconnected`` o ``error``);
         * en ``connected`` y ``connecting`` el click es un no-op
         * para evitar reconexiones espurias.
         */
        function handleClick() {
            if (state.value === "disconnected" || state.value === "error") {
                emit("connect");
            }
        }

        return { state, project, colorClass, tooltip, handleClick };
    },
    template: /* html */ `
        <button
            @click="handleClick"
            :title="tooltip"
            :class="['w-3 h-3 rounded-full', colorClass, 'transition-colors']"
            :aria-label="'Estado TIA: ' + state"
            data-testid="tia-connection-indicator">
        </button>
    `,
};
