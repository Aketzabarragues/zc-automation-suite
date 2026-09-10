// ============================================================================
// EmptyState.js — Componente de feedback "no hay datos" (NUEVO, no en legacy).
//
//  Patron consistente para los tres casos de "vacio" del HMI:
//    - Welcome: catalogo de areas vacio (endpoint no existe o sin areas).
//    - Shell: manifest de area sin loaders (modo degradado).
//    - Vistas de area: estado vacio (sin PLCs, sin preview, etc.).
//
//  Tema: solo tokens semanticos del "Industrial Claro".
//
//  Props:
//    - icon (String, default ""): emoji o glifo a mostrar arriba.
//    - title (String, required): titulo del empty state.
//    - description (String, default ""): parrafo explicativo.
//    - actionLabel (String, default ""): si no vacio, renderiza un
//      boton con este label.
//    - size (String, default "md"): "sm" | "md" | "lg". Controla
//      el padding y tamano del icono.
//
//  Emits:
//    - action(): emitido al pulsar el boton (solo si actionLabel
//      no esta vacio).
// ============================================================================

export default {
    name: "EmptyState",
    props: {
        icon: { type: String, default: "" },
        title: { type: String, required: true },
        description: { type: String, default: "" },
        actionLabel: { type: String, default: "" },
        size: {
            type: String,
            default: "md",
            validator: (v) => ["sm", "md", "lg"].includes(v),
        },
    },
    emits: ["action"],
    setup(props, { emit }) {
        function onAction() {
            emit("action");
        }
        return { props, onAction };
    },
    template: /* html */ `
        <div
            :class="[
                'flex flex-col items-center justify-center text-center bg-surface-raised border border-dashed border-line rounded',
                props.size === 'sm' ? 'p-4' : props.size === 'lg' ? 'p-10' : 'p-6'
            ]"
            data-testid="empty-state">
            <div
                :class="[
                    'mb-3 opacity-40',
                    props.size === 'sm' ? 'text-2xl' : props.size === 'lg' ? 'text-6xl' : 'text-4xl'
                ]"
                aria-hidden="true">
                {{ props.icon || "✦" }}
            </div>
            <p
                :class="[
                    'font-semibold text-ink mb-1',
                    props.size === 'sm' ? 'text-sm' : props.size === 'lg' ? 'text-xl' : 'text-base'
                ]">
                {{ props.title }}
            </p>
            <p
                v-if="props.description"
                :class="[
                    'text-ink-muted max-w-md',
                    props.size === 'sm' ? 'text-xs' : 'text-sm'
                ]">
                {{ props.description }}
            </p>
            <button
                v-if="props.actionLabel"
                @click="onAction"
                type="button"
                class="mt-4 px-4 py-2 bg-accent text-white font-semibold text-sm rounded hover:bg-accent-hover transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                {{ props.actionLabel }}
            </button>
        </div>
    `,
};
