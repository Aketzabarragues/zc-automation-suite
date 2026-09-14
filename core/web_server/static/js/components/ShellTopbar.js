/**
 * Componente ShellTopbar — barra superior cross-cutting del shell.
 *
 * Tras el refactor de areas (v3.0+ del base, sept-2026), la topbar
 * queda reducida a breadcrumb (Área · Sub-vista) + texto del PLC
 * activo. Todo lo demás (indicators, conectar/desconectar, select
 * PLC) migró al ``plcpanelview`` del shell comun, que es donde el
 * operario realmente interactúa con el state machine del worker
 * persistente.
 *
 * v3.1 (sept-2026 round, refactor areas): el ``VIEW_LABELS``
 * hardcoded que mappeaba ``currentView`` -> label humano se va.
 * El label se resuelve dinámicamente desde
 * ``store.areaManifest.components.viewLabels`` (que el area
 * aporta en su manifest), con fallback a la key capitalizada.
 * Esto permite que cualquier area nueva se conecte al shell sin
 * tocar este archivo.
 *
 * Tema: capa clara. Sin hex hardcoded.
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

/** Capitaliza primera letra (fallback de label cuando no hay
 *  ``viewLabels`` en el manifest ni key "plc" conocida). */
function capitalize(s) {
    if (!s) return "";
    return String(s).charAt(0).toUpperCase() + String(s).slice(1);
}

export default {
    name: "ShellTopbar",
    props: {
        /** ``{ key, label }`` del area activa. Solo se usa para el
         *  label de la izquierda del breadcrumb. Si el padre no lo
         *  pasa, se cae al fallback degradado. */
        area: { type: Object, required: true },
    },
    setup(props) {
        /** Label del area activa del prop. */
        const areaLabel = computed(() => {
            if (!props.area) return "—";
            return props.area.label || props.area.subtitle || props.area.key || "—";
        });

        /**
         * Label de la sub-vista activa, derivado del manifest del
         * area. Orden de resolucion:
         *   1. Si currentView es "plc", label fijo "PLC".
         *   2. Si el manifest tiene components.viewLabels[currentView],
         *      usa ese.
         *   3. Fallback: key capitalizada.
         *
         * Esto elimina el VIEW_LABELS hardcoded anterior; cada area
         * aporta sus labels a su propio manifest.
         */
        const currentViewLabel = computed(() => {
            const key = store.currentView;
            if (!key) return "—";
            if (key === "plc") return "PLC";
            const m = store.areaManifest;
            if (m && m.components && m.components.viewLabels) {
                const lbl = m.components.viewLabels[key];
                if (lbl) return lbl;
            }
            return capitalize(key);
        });

        return {
            store,
            areaLabel,
            currentViewLabel,
        };
    },
    template: /* html */ `
        <header class="h-14 bg-white border-b border-line flex items-center justify-between px-6 shrink-0 shadow-sm">
            <nav class="flex items-center gap-2 text-xs font-medium" aria-label="Breadcrumb">
                <span class="text-ink-muted uppercase tracking-widest">{{ areaLabel }}</span>
                <span class="text-line-strong" aria-hidden="true">•</span>
                <span class="text-accent font-bold uppercase tracking-widest">{{ currentViewLabel }}</span>
            </nav>
            <div class="inline-flex items-center gap-2 bg-surface-sunken border border-line rounded-md px-3 py-1.5 text-xs"
                 data-testid="topbar-plc-text">
                <span class="text-ink-muted">PLC:</span>
                <span class="font-mono font-semibold text-accent">{{ store.selectedPlc || '—' }}</span>
            </div>
        </header>
    `,
};
