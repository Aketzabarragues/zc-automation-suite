// ============================================================================
// ShellTopbar.js — Barra superior cross-cutting del shell (HMI pasivo).
//
//  Clonado del legacy y adaptado:
//    - `import { store } from "/js/store.js"` → `usePlc()`
//    - `store.currentView`                    → `plc.currentView` (computed)
//    - Lecturas del TIA / Worker via `plc.tiaState`, `plc.workerAlive`.
//
//  El ShellTopbar expone:
//    * Breadcrumb del area (label del prop `area`).
//    * Sub-vista activa (mapping `currentView` → label humano).
//    * WorkerStatusIndicator (circulo ortogonal al TIA: vivo/muerto).
//    * TiaConnectionIndicator (circulo del attach a TIA).
//    * Texto del PLC activo (placeholder hasta que el area
//      seleccionada lo exponga via otra fuente).
//
//  Tema: capa "Industrial Claro". Solo tokens semanticos.
// ============================================================================

import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { usePlc } from "/js/composables/usePlc.js";
import TiaConnectionIndicator from "/js/components/TiaConnectionIndicator.js";
import WorkerStatusIndicator from "/js/components/WorkerStatusIndicator.js";

/**
 * Mapping de sub-vistas a etiquetas humano-legibles para el breadcrumb.
 * Las keys coinciden con las declaradas en el `manifest.js` del area
 * (tipicamente `landing` y los ids de sub-vista). Si llega un area
 * con sub-vistas distintas, se anade como caso particular aqui
 * (preferible a meter logica extra en el componente).
 */
const VIEW_LABELS = {
    landing: "Inicio",
    def: "Definicion programacion",
    cache: "Cache del PLC",
    disp: "Dispositivos",
    proc: "Procesos",
};

export default {
    name: "ShellTopbar",
    components: { TiaConnectionIndicator, WorkerStatusIndicator },
    props: {
        /**
         * `{ key, label, icon }` del area activa. Requerido para
         * construir el breadcrumb (etiqueta del area). Si el padre
         * no lo pasa, se cae al fallback degradado.
         */
        area: { type: Object, required: true },
    },
    setup(props) {
        const plc = usePlc();

        /**
         * Etiqueta del area activa derivada del prop. Fallback
         * degradado si el prop viene vacio o sin label.
         */
        const areaLabel = computed(() => {
            if (!props.area) return "—";
            return props.area.label || props.area.key || "—";
        });

        /**
         * Etiqueta de la sub-vista activa derivada de
         * `plc.currentView`. Si la key no esta en `VIEW_LABELS`
         * (area nueva con una sub-vista que aun no hemos catalogado),
         * cae a "—" para que la barra no rompa el layout.
         */
        const currentViewLabel = computed(() => {
            return VIEW_LABELS[plc.currentView] || "—";
        });

        /**
         * Handler del click en el indicador TIA. Delega en el
         * composable: el FB de ConexionTIA se arranca con
         * `startFb("ConexionTIA")`. La actualizacion del estado
         * llega por SSE (no necesitamos hacer nada mas aqui).
         */
        async function onTiaConnect() {
            try {
                await plc.startFb("ConexionTIA");
            } catch (e) {
                // Silencioso: el SSE publicara el error en `plc.lastError`.
                console.warn("[ShellTopbar] no se pudo arrancar ConexionTIA:", e);
            }
        }

        return {
            areaLabel,
            currentViewLabel,
            onTiaConnect,
        };
    },
    template: /* html */ `
        <header
            class="h-14 bg-white border-b border-line flex items-center justify-between px-6 shrink-0 shadow-sm"
            data-testid="shell-topbar">

            <!-- Izquierda: breadcrumb "Area · Sub-vista" + indicators -->
            <div class="flex items-center gap-4">
                <nav class="flex items-center gap-2 text-xs font-medium" aria-label="Breadcrumb">
                    <span class="text-ink-muted uppercase tracking-widest">{{ areaLabel }}</span>
                    <span class="text-line-strong" aria-hidden="true">•</span>
                    <span class="text-accent font-bold uppercase tracking-widest">
                        {{ currentViewLabel }}
                    </span>
                </nav>

                <!-- Indicadores ortogonales: worker (subproceso) + TIA (attach).
                     Se mantienen a la izquierda para que el operario vea
                     de un vistazo el estado del backend. -->
                <div class="flex items-center gap-2 pl-4 border-l border-line">
                    <WorkerStatusIndicator />
                    <TiaConnectionIndicator @connect="onTiaConnect" />
                </div>
            </div>

            <!-- Derecha: el PLC activo y proyecto TIA (placeholder por
                 ahora; las areas los rellenaran via DBs especificas). -->
            <div class="flex items-center gap-3">
                <div
                    class="inline-flex items-center gap-2 bg-surface-sunken border border-line rounded-md px-3 py-1.5 text-xs"
                    data-testid="topbar-plc-text">
                    <span class="text-ink-muted">PLC:</span>
                    <span class="font-mono font-semibold text-accent">—</span>
                </div>
                <div
                    class="inline-flex items-center gap-2 bg-surface-sunken border border-line rounded-md px-3 py-1.5 text-xs max-w-xs"
                    data-testid="topbar-project-text">
                    <span class="text-ink-muted">TIA:</span>
                    <span class="font-mono font-semibold text-accent truncate">
                        {{ areaLabel }}
                    </span>
                </div>
            </div>
        </header>
    `,
};
