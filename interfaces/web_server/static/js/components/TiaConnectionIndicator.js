// ============================================================================
// TiaConnectionIndicator.js — Circulo de estado del worker TIA.
//
//  Clonado del legacy y adaptado:
//    - `store.tiaConnection.state` → `plc.tiaState` (computed).
//    - `store.tiaConnection.project` → `plc.projectName` / `plc.projectPath`.
//    - `store.tiaConnection.last_error` → `plc.lastError`.
//
//  Source of truth: el `DB_EstadoConexion` trasversal
//  (`core/plc/plc.py`) que el backend publica por SSE en el snapshot
//  inicial y en cada `fb_changed` de `ConexionTIA`. La SPA NO hace
//  polling: el composable actualiza `plc.tiaState` reactivamente
//  cuando llega un push.
//
//  Estados (state machine sept-2026, 4 valores estables):
//    - connected   (verde)             → attach a TIA Portal OK.
//    - connecting  (ambar + pulse)     → attach en curso.
//    - idle        (gris)              → worker vivo, sin portal.
//    - error       (rojo)              → fallo de attach.
//
//  Emits:
//    - "connect": cuando el operario hace click en idle/error.
//      El handler (ShellTopbar) llama a `plc.startFb("ConexionTIA")`.
// ============================================================================

import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { usePlc } from "/js/composables/usePlc.js";

// Mapping de state a etiqueta en castellano para el `aria-label`.
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
        const plc = usePlc();

        // Acceso al store via computed (regla Vue 3 sin build step).
        const state = computed(() => plc.tiaState);
        const projectName = computed(() => plc.projectName);
        const projectPath = computed(() => plc.projectPath);
        const error = computed(() => plc.lastError);
        const plcs = computed(() => plc.plcs);

        const stateLabel = computed(() => STATE_LABELS[state.value] || state.value);

        /**
         * Clase utilitaria de Tailwind para el color del circulo.
         * 4 ramas (state machine sept-2026).
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
         * Tooltip con info del proyecto cuando esta conectado.
         * En error muestra el mensaje; en idle invita a conectar.
         */
        const tooltip = computed(() => {
            if (state.value === "connected" && projectName.value) {
                const np = plcs.value.length || 0;
                return [
                    projectName.value || "(sin nombre)",
                    projectPath.value || "",
                    `PLCs: ${np}`,
                ].join("\n");
            }
            if (state.value === "error") {
                return `Error: ${error.value || "desconocido"}`;
            }
            if (state.value === "idle") {
                return "TIA en reposo. Pulsa el circulo para abrir un portal.";
            }
            if (state.value === "connecting") {
                return "Conectando con TIA Portal...";
            }
            return "Estado TIA desconocido";
        });

        /**
         * Click: solo emite "connect" en idle/error. En connecting
         * o connected, el click es no-op (evita reconexiones espurias).
         */
        function handleClick() {
            if (state.value === "idle" || state.value === "error") {
                emit("connect");
            }
        }

        return {
            state,
            stateLabel,
            colorClass,
            tooltip,
            handleClick,
        };
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
