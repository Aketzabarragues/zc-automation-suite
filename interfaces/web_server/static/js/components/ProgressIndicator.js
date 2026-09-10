// ============================================================================
// ProgressIndicator.js — Panel de progreso del FB activo (HMI pasivo).
//
//  ADAPTADO del legacy:
//
//  En el legacy, `store.progress` era un espejo reactivo del
//  `ProgressTracker` backend, alimentado por polling 500 ms desde
//  `main.js`. En el greenfield NO existe el `ProgressTracker`
//  (legacy) y NO hay polling (regla ineludible AGENTS.md §4).
//
//  Aqui la fuente de verdad es **el FB activo**:
//    - `plc.FBs.ConexionTIA.progress` (0..100, el HMI lo pinta como
//      barra de progreso).
//    - `plc.FBs.ConexionTIA.nStep` (etapa del state machine, lo
//      traducimos a una "etiqueta humana" via `step_name`).
//    - `plc.FBs.ConexionTIA.step_name` (descripcion humana del paso).
//    - `plc.FBs.ConexionTIA.error` (mensaje si el FB esta en error).
//
//  Modos visuales:
//    - "idle"     → oculto.
//    - "running"  → barra azul + flecha rotando + "En curso".
//    - "error"    → barra roja + "Error".
//    - "done"     → barra verde + "Completado" + boton ✕ para limpiar.
//
//  Variantes:
//    - dark=false (default): tokens del Industrial Claro.
//    - dark=true: tokens `bg-shell*` para vivir en el ShellSidebar.
//
//  Tema: solo tokens semanticos.
// ============================================================================

import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { usePlc } from "/js/composables/usePlc.js";

/**
 * Estado del FB ConexionTIA. Mapeo a partir de `nStep`:
 *   - 0            → idle
 *   - 10, 20       → running (en curso entre etapas)
 *   - 30 (n_done)  → done
 *   - 99 (n_error) → error
 *
 * Como en el greenfield el unico FB registrado en Fase 1 es
 * `ConexionTIA`, el indicador refleja su estado. Si en fases
 * futuras hay multiples FBs en curso, este componente se hace
 * "selector del FB activo" o se replica uno por FB.
 */
const FB_NAME = "ConexionTIA";

const STAGE_ICON_LIGHT = {
    pending: { icon: "○", cls: "text-ink-muted" },
    running: { icon: "↻", cls: "text-accent" },
    done: { icon: "✓", cls: "text-green-600" },
    error: { icon: "✗", cls: "text-red-600" },
};

const STAGE_ICON_DARK = {
    pending: { icon: "○", cls: "text-on-shell-faint" },
    running: { icon: "↻", cls: "text-accent-bright" },
    done: { icon: "✓", cls: "text-green-600" },
    error: { icon: "✗", cls: "text-red-600" },
};

export default {
    name: "ProgressIndicator",
    props: {
        /**
         * Variante visual. `true` = sobre fondo navy del shell
         * corporativo; `false` = sobre fondo claro.
         */
        dark: { type: Boolean, default: false },
    },
    setup(props) {
        const plc = usePlc();

        /**
         * Estado del FB activo (computed reactivo). El backend
         * publica el `fb_changed` por SSE; el composable hace
         * merge defensivo en `plc.FBs[name]`. Aqui lo derivamos
         * a un `computed` para que el template lo lea reactivamente.
         *
         * Devuelve un objeto con shape `{nStep, progress, step_name,
         * error, type, ...}` o un objeto vacio si el FB aun no ha
         * sido registrado (initial state).
         */
        const fb = computed(() => plc.FBs[FB_NAME] || {});

        /**
         * Modo visual del panel. Mapeo del `nStep`/`type` del FB:
         *   - nStep === 0 y sin error → idle (oculto).
         *   - nStep === 99 (n_error)  → error.
         *   - nStep === 30 (n_done)   → done.
         *   - resto                    → running.
         */
        const mode = computed(() => {
            const f = fb.value;
            if (!f || !f.nStep) return "idle";
            if (f.nStep === 99 || f.nError > 0 || (f.error && f.error.length)) {
                return "error";
            }
            if (f.nStep === 30) return "done";
            if (f.nStep > 0) return "running";
            return "idle";
        });

        /**
         * Porcentaje de progreso derivado del FB. `fb.progress` ya
         * es 0..100. Fallback 0 si el FB no expone el campo.
         */
        const percent = computed(() => {
            const f = fb.value;
            const p = (f && typeof f.progress === "number") ? f.progress : 0;
            return Math.max(0, Math.min(100, p));
        });

        /**
         * Texto de la etapa actual. Prioridad:
         *   1. `step_name` (humano, lo escribe el FB).
         *   2. "Conectando con TIA" como fallback.
         */
        const stepName = computed(() => {
            const f = fb.value;
            return (f && f.step_name) || "Conectando con TIA";
        });

        /**
         * Color de la barra segun modo. En variant dark, el
         * `running` usa `bg-accent-bright` para mantener contraste
         * contra el navy; el resto se mantiene igual (red/green
         * son lo bastante brillantes sobre ambos fondos).
         */
        const barCls = computed(() => {
            if (mode.value === "running") {
                return props.dark ? "bg-accent-bright" : "bg-accent";
            }
            switch (mode.value) {
                case "error": return "bg-red-600";
                case "done": return "bg-green-600";
                default: return props.dark ? "bg-shell-border" : "bg-surface-sunken";
            }
        });

        /**
         * Icono del titulo del panel, separado del texto para poder
         * aplicar `animate-spin inline-block` SOLO al icono cuando
         * esta en `running`.
         */
        const titleIcon = computed(() => {
            if (mode.value === "error") return "✗";
            if (mode.value === "done") return "✓";
            if (mode.value === "running") return "↻";
            return "";
        });

        /**
         * Texto del titulo (sin el icono, que se pinta aparte).
         */
        const titleText = computed(() => {
            if (mode.value === "error") return "Error";
            if (mode.value === "done") return "Completado";
            if (mode.value === "running") return "En curso";
            return "";
        });

        /**
         * Subtitulo: nombre del paso o mensaje de error.
         */
        const subtitle = computed(() => {
            const f = fb.value;
            if (mode.value === "error") {
                return (f && f.error) || "Operacion fallida";
            }
            if (mode.value === "done") {
                return stepName.value;
            }
            if (mode.value === "running") {
                return stepName.value;
            }
            return "";
        });

        /**
         * Iconos de stage segun la variant. `props.dark` es
         * reactivo en setup, asi que cambiar la prop en runtime
         * re-evalua este computed.
         */
        const stageMeta = computed(() =>
            props.dark ? STAGE_ICON_DARK : STAGE_ICON_LIGHT
        );

        /**
         * Highlight del stage en estado running.
         */
        const runningHighlightCls = computed(() =>
            props.dark
                ? "bg-shell-hover rounded px-1 -mx-1"
                : "bg-accent-subtle rounded px-1 -mx-1"
        );

        /**
         * Hay algo que mostrar? Solo si el modo no es idle.
         */
        const hasContent = computed(() => mode.value !== "idle");

        /**
         * Boton ✕: limpia el FB reseteando su estado local. En el
         * greenfield, el FB no expone un endpoint de "clear"; pero
         * podemos pedir un nuevo `startFb` (que es idempotente y
         * resetea el state machine) o un `disconnectFb`. En esta
         * primera version, simplemente pedimos un disconnect si esta
         * en done, y un nuevo start si esta en error (para reintentar).
         */
        async function clear() {
            try {
                const f = fb.value;
                if (mode.value === "done" || mode.value === "error") {
                    // Reset pidiendo un nuevo start (idempotente).
                    await plc.startFb(FB_NAME);
                }
            } catch (e) {
                console.warn("[ProgressIndicator] no se pudo limpiar:", e);
            }
        }

        return {
            hasContent,
            mode,
            barCls,
            titleIcon,
            titleText,
            subtitle,
            percent,
            stageMeta,
            runningHighlightCls,
            clear,
            dark: computed(() => props.dark),
        };
    },
    template: /* html */ `
        <section
            v-if="hasContent"
            data-testid="progress-indicator"
            :data-mode="mode"
            :class="dark
                ? 'mt-auto border-t border-shell-border bg-shell-deep p-3'
                : 'mt-auto border-t border-line bg-surface-sunken p-3'">
            <header class="flex justify-between items-center mb-2">
                <div class="min-w-0 flex-1">
                    <div :class="dark
                        ? 'text-xs font-bold text-on-shell'
                        : 'text-xs font-bold text-ink'">
                        <span
                            v-if="titleIcon"
                            :class="mode === 'running'
                                ? 'inline-block animate-spin mr-1'
                                : 'mr-1'"
                            data-testid="progress-title-icon">
                            {{ titleIcon }}
                        </span>
                        {{ titleText }}
                    </div>
                    <div
                        :class="dark
                            ? 'text-[10px] text-on-shell-muted truncate'
                            : 'text-[10px] text-ink-muted truncate'">
                        {{ subtitle }}
                    </div>
                </div>
                <button
                    @click="clear"
                    :class="dark
                        ? 'ml-2 text-xs px-1.5 py-0.5 bg-shell-hover border border-shell-border rounded hover:bg-shell-active text-on-shell-muted hover:text-on-shell'
                        : 'ml-2 text-xs px-1.5 py-0.5 bg-surface-raised border border-line rounded hover:bg-surface-sunken text-ink'"
                    title="Cerrar (limpiar)"
                    data-testid="progress-clear">
                    ✕
                </button>
            </header>

            <!-- Barra de progreso global -->
            <div :class="dark ? 'h-1.5 bg-shell-border mb-2 rounded' : 'h-1.5 bg-surface mb-2 rounded'">
                <div
                    class="h-full transition-all duration-300 rounded"
                    :class="barCls"
                    :style="{ width: percent + '%' }">
                </div>
            </div>
        </section>
    `,
};
