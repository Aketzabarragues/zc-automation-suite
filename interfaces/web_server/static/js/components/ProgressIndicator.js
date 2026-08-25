/**
 * Componente ProgressIndicator.
 *
 * Panel FIJO de progreso, sin overlay ni auto-close. Diseñado para
 * vivir en la parte inferior del ``AlimentacionSidebar``. Se
 * muestra solo cuando hay algo que reportar (stages no vacíos o
 * ``active=true``); cuando termina la operación, los stages
 * quedan visibles hasta que el operario pulsa el botón ✕ para
 * limpiar.
 *
 * Fuente de verdad: ``store.progress`` (espejo reactivo del
 * ``ProgressTracker`` backend, alimentado por el polling 500 ms
 * de ``main.js``). El componente NO hace fetches.
 *
 * Estados visuales:
 *   * ``active=true`` con stages corriendo → barra azul + ⏳.
 *   * ``active=false`` + ``error`` no nulo → barra roja + ✗.
 *   * ``active=false`` + stages no vacíos (sin error) → barra
 *     verde + ✓ "Completado".
 *   * ``stages=[]`` y ``active=false`` y sin error → oculto.
 *
 * Tema: Industrial Claro. Solo tokens semánticos del theme.
 */
import { computed } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store } from "../store.js";
import { apiClearProgress } from "../api.js";

/**
 * Icono por status. Mantenido como objeto simple (no reactividad):
 * los stages vienen de ``store.progress`` ya reactivo.
 */
const STAGE_ICON = {
    pending:  { icon: "○", cls: "text-ink-muted" },
    running:  { icon: "⏳", cls: "text-accent" },
    done:     { icon: "✓", cls: "text-green-600" },
    error:    { icon: "✗", cls: "text-red-600" },
};

export default {
    name: "ProgressIndicator",
    setup() {
        /**
         * ¿Hay algo que mostrar?
         *  * ``active=true`` → sí (en curso).
         *  * ``stages.length > 0`` → sí (resultado reciente).
         *  * En otro caso → no.
         */
        const hasContent = computed(() => {
            const p = store.progress;
            if (p.active) return true;
            if (p.error) return true;
            if (Array.isArray(p.stages) && p.stages.length > 0) return true;
            return false;
        });

        /** Modo visual del panel. */
        const mode = computed(() => {
            const p = store.progress;
            if (p.active) return "running";
            if (p.error) return "error";
            if (Array.isArray(p.stages) && p.stages.length > 0) return "success";
            return "idle";
        });

        /** Color de la barra según modo. */
        const barCls = computed(() => {
            switch (mode.value) {
                case "running": return "bg-accent";
                case "error":   return "bg-red-600";
                case "success": return "bg-green-600";
                default:        return "bg-surface-sunken";
            }
        });

        /** Título del panel. */
        const title = computed(() => {
            const p = store.progress;
            if (mode.value === "error") return "✗ Error";
            if (mode.value === "success") return "✓ Completado";
            if (mode.value === "running") return "⏳ En curso";
            return "";
        });

        /** Subtítulo: nombre de la operación o mensaje de error. */
        const subtitle = computed(() => {
            const p = store.progress;
            if (mode.value === "error") return p.error || "Operación fallida";
            if (mode.value === "success") {
                return `${p.current}/${p.total} completados`;
            }
            if (mode.value === "running") {
                return p.label
                    ? `${p.label} — ${p.current}/${p.total}`
                    : `Paso ${p.current}/${p.total}`;
            }
            return "";
        });

        /** Botón ✕: limpia el tracker (backend + frontend). */
        async function clear() {
            try {
                await apiClearProgress();
            } catch (e) {
                // Si el backend falla, limpiamos el store local igualmente.
            }
            // Reset local explícito (el polling siguiente lo reflejará
            // pero limpiamos ya para feedback inmediato).
            store.progress = {
                active: false,
                operation: null,
                label: null,
                current: 0,
                total: 0,
                percent: 0,
                stages: [],
                started_at: null,
                finished_at: null,
                error: null,
            };
        }

        return {
            hasContent,
            mode,
            barCls,
            title,
            subtitle,
            store,
            stageMeta: STAGE_ICON,
            clear,
        };
    },
    template: /* html */ `
        <section v-if="hasContent"
            data-testid="progress-indicator"
            :data-mode="mode"
            class="mt-auto border-t border-line bg-surface-sunken p-3">
            <header class="flex justify-between items-center mb-2">
                <div class="min-w-0 flex-1">
                    <div class="text-xs font-bold text-ink">{{ title }}</div>
                    <div class="text-[10px] text-ink-muted truncate">{{ subtitle }}</div>
                </div>
                <button @click="clear"
                    class="ml-2 text-xs px-1.5 py-0.5 bg-surface-raised border border-line rounded hover:bg-surface-sunken text-ink"
                    title="Cerrar (limpiar tracker)"
                    data-testid="progress-clear">
                    ✕
                </button>
            </header>

            <!-- Barra de progreso global -->
            <div class="h-1.5 bg-surface mb-2 rounded">
                <div class="h-full transition-all duration-300 rounded"
                    :class="barCls"
                    :style="{ width: store.progress.percent + '%' }">
                </div>
            </div>

            <!-- Lista de stages: TODOS visibles, sin truncar -->
            <ol class="text-[10px] font-mono leading-snug"
                data-testid="progress-stages">
                <li v-for="(stage, idx) in store.progress.stages"
                    :key="stage.id"
                    :class="['flex justify-between items-baseline py-0.5',
                             stage.status === 'running' ? 'bg-accent-subtle rounded px-1 -mx-1' : '']">
                    <span class="flex items-baseline gap-1 min-w-0 flex-1">
                        <span :class="['w-3 text-center', stageMeta[stage.status]?.cls || 'text-ink-muted']">
                            {{ stageMeta[stage.status]?.icon || "?" }}
                        </span>
                        <span class="text-ink-muted w-4 text-right">{{ idx + 1 }}.</span>
                        <span class="truncate"
                            :class="stage.status === 'pending' ? 'text-ink-muted' : 'text-ink'">
                            {{ stage.label }}
                        </span>
                        <span v-if="stage.detail" class="text-ink-muted italic text-[9px] truncate ml-1">
                            — {{ stage.detail }}
                        </span>
                    </span>
                </li>
            </ol>
        </section>
    `,
};
