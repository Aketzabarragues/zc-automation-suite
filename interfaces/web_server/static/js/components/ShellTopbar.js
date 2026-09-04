/**
 * Componente ShellTopbar — barra superior cross-cutting del shell
 * corporativo (v2.1).
 *
 * Tras la v2 del rediseño "Modern Corporate", la selección de PLC
 * y el indicador de proyecto migran del sidebar a una barra
 * superior pegada al borde de la columna derecha (entre la
 * cabecera del shell y el área de contenido). En la v2.1 se ha
 * aligerado el visual:
 *
 *   * Altura reducida de ``h-16`` (64 px) a ``h-14`` (56 px).
 *   * Eliminado el círculo animado de status (busy/ok/idle)
 *     que tenía la v2 — feedback explícito del operario: "no
 *     hace falta ver los colores en azul, verde, etc."
 *   * Eliminado el marco ``bg-surface-sunken border rounded-lg``
 *     que envolvía el bloque PLC. Ahora es un layout inline
 *     con solo ``flex items-center gap-2``; el espaciado se
 *     controla con ``gap`` y cada elemento lleva su propio
 *     styling.
 *   * Botón "Buscar PLCs" rediseñado como CTA más prominente
 *     (texto más grande, padding horizontal mayor, ``shadow-md``
 *     para dar peso visual).
 *
 * Funcionalidad intacta respecto a v2:
 *
 *   * Pinta el breadcrumb del área (`<Área> · <Sub-vista>`) con
 *     tokens claros (`text-ink-muted` para el área, `text-accent`
 *     bold para la sub-vista).
 *   * Concentra el bloque PLC: caption con el nombre del proyecto
 *     TIA, desplegable y botón "Buscar PLCs".
 *   * Sigue leyendo de `store.selectedPlc`, `store.plcs`,
 *     `store.busy`, `store.projectInfo` y `store.currentView`,
 *     para no introducir nuevos slots en el store.
 *
 * Es cross-cutting: vive en `/js/components/` y se monta en
 * `main.js` (el shell raíz) una sola vez. Las áreas NO lo
 * importan — es parte del chrome, no de la navegación.
 *
 * Tema: capa clara. `bg-white` para el header, `bg-accent` para
 * el botón CTA, `border-line` para el separador inferior y los
 * bordes del select. Sin hex hardcoded. El feedback largo
 * (ProgressIndicator) sigue viviendo en el ShellSidebar; este
 * componente es SOLO datos/breadcrumb/selección PLC.
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola
 * línea. Salto de línea entre elementos del array OK.
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store, pushLog, loadAndApplyPlcBlocks, resetPlcState } from "/js/store.js";
import { apiFetchPlcs, apiFetchProjectInfo } from "/js/api.js";

/**
 * Mapping de ``store.currentView`` → etiqueta humano-legible para
 * el breadcrumb. Las keys coinciden con las declaradas en el
 * ``manifest.js`` del área (típicamente ``landing`` y los 4 ids
 * de sub-vista). Si llega un área con sub-vistas distintas, se
 * añade aquí como caso particular (preferible a meter lógica
 * extra en el componente).
 */
const VIEW_LABELS = {
    landing: "Inicio",
    def:     "Definición programación",
    cache:   "Cache del PLC",
    disp:    "Dispositivos",
    proc:    "Procesos",
};

export default {
    name: "ShellTopbar",
    props: {
        /** ``{ key, label, icon }`` del área activa. Requerido
         *  para construir el breadcrumb (etiqueta del área). Si
         *  el padre no lo pasa, se cae al fallback degradado. */
        area: { type: Object, required: true },
    },
    setup(props) {
        /**
         * Etiqueta del área activa derivada del prop. Fallback
         * degradado si el prop viene vacío o sin label (modo
         * "área desconocida" mientras el catálogo no carga).
         */
        const areaLabel = computed(() => {
            if (!props.area) return "—";
            return props.area.label || props.area.key || "—";
        });

        /**
         * Etiqueta de la sub-vista activa derivada de
         * ``store.currentView``. Si la key no está en
         * ``VIEW_LABELS`` (área nueva con una sub-vista que aún
         * no hemos catalogado), cae a ``"—"`` para que la barra
         * no rompa el layout.
         */
        const currentViewLabel = computed(() => {
            return VIEW_LABELS[store.currentView] || "—";
        });

        /**
         * Refresca el desplegable de PLCs Y carga el nombre del
         * proyecto TIA conectado. Las dos llamadas se hacen en
         * paralelo (mismo click del operario) para minimizar la
         * latencia visible. Si TIA no está conectado, ambos
         * endpoints devuelven ``{ok: false, error: "..."}`` y la
         * barra queda en estado degradado: lista vacía, sin
         * caption de proyecto.
         *
         * Este handler vivía en el ShellSidebar en la v1; al
         * mover la selección PLC a la topbar, se reubica aquí
         * sin cambiar la semántica (mismo cuerpo, mismos
         * side-effects en el store).
         */
        async function handleRefreshPlcs() {
            store.busy = true;
            try {
                const [plcsResp, infoResp] = await Promise.all([
                    apiFetchPlcs(),
                    apiFetchProjectInfo(),
                ]);

                // Deteccion centralizada de TIA no responde: si
                // CUALQUIERA de los dos endpoints del shell reporta
                // ``X-Error-Type: TIAConnectionError``, reseteamos el
                // state del PLC y dejamos la barra en estado
                // degradado. Asi el operario ve el mensaje claro
                // "Reconecta el portal" sin tener que tirar de cada
                // sub-flujo (preview, commit, scan de bloques) para
                // descubrir que TIA cerro.
                const tiaDown =
                    (plcsResp && plcsResp.errorType === "TIAConnectionError") ||
                    (infoResp && infoResp.errorType === "TIAConnectionError");

                if (tiaDown) {
                    pushLog(
                        "TIA Portal no responde. Reconecta y vuelve a seleccionar el PLC.",
                        "error"
                    );
                    resetPlcState();
                } else if (plcsResp.ok && plcsResp.data && plcsResp.data.plcs) {
                    store.plcs = plcsResp.data.plcs;
                } else if (plcsResp.data && plcsResp.data.ok === false) {
                    pushLog(plcsResp.data.error || "TIA Portal no conectado", "warning");
                    store.plcs = [];
                }

                if (infoResp.ok && infoResp.data && infoResp.data.project_info) {
                    store.projectInfo = infoResp.data.project_info;
                } else if (infoResp.data && infoResp.data.ok === false) {
                    store.projectInfo = null;
                }
            } finally {
                store.busy = false;
            }
        }

        /**
         * Handler del ``@change`` del ``<select>`` de PLC. Una
         * sola llamada a ``loadAndApplyPlcBlocks`` dispara el
         * scan de bloques+tag_tables del PLC recién elegido
         * (``GET /api/v1/plcs/<plc>/blocks``) y deja el snapshot
         * en ``store.plcBlocksCache`` para que la vista
         * ``BloquesCacheView`` lo tenga listo en cuanto el
         * operario navegue a ella. La promesa se ignora: el
         * feedback de la operación larga llega por el
         * ``ProgressTracker`` backend, que el
         * ``ProgressIndicator`` (anclado al fondo del
         * ShellSidebar) muestra automáticamente.
         */
        async function onPlcSelected() {
            await loadAndApplyPlcBlocks(store.selectedPlc);
        }

        return {
            store,
            areaLabel,
            currentViewLabel,
            handleRefreshPlcs,
            onPlcSelected,
        };
    },
    template: /* html */ `
        <header class="h-14 bg-white border-b border-line flex items-center justify-between px-6 shrink-0 shadow-sm">

            <!-- Izquierda: breadcrumb "Área · Sub-vista".
                 Mismo tipo pequeño uppercase que el resto de
                 captions de la SPA; el área en muted, la
                 sub-vista en accent bold para que sea el ancla
                 visual. -->
            <nav class="flex items-center gap-2 text-xs font-medium" aria-label="Breadcrumb">
                <span class="text-ink-muted uppercase tracking-widest">{{ areaLabel }}</span>
                <span class="text-line-strong" aria-hidden="true">•</span>
                <span class="text-accent font-bold uppercase tracking-widest">{{ currentViewLabel }}</span>
            </nav>

            <!-- Derecha: bloque PLC inline (sin marco sunken,
                 v2.1). Solo el label "PLC:" + caption del
                 proyecto + select + botón. El espaciado se
                 controla con gap, no con un contenedor con
                 background y border.

                 v2.1: el círculo animado de status (busy/ok/
                 idle) que tenía v2 se ha eliminado por
                 feedback del operario ("no hace falta ver los
                 colores en azul, verde, etc."). Si en una
                 iteración posterior quiere recuperar una pista
                 visual mínima, se puede añadir un text-[10px]
                 al lado del label que diga "Conectado" /
                 "Buscando…". -->
            <div class="flex items-center gap-2">
                <label class="text-[10px] font-bold text-ink-muted uppercase tracking-widest">PLC:</label>
                <p v-if="store.projectInfo && store.projectInfo.name"
                   class="text-[11px] font-mono text-ink-muted truncate max-w-[200px]"
                   :title="store.projectInfo.name"
                   data-testid="topbar-project-name">
                    {{ store.projectInfo.name }}
                </p>
                <select v-model="store.selectedPlc" @change="onPlcSelected"
                        :disabled="store.plcs.length === 0 || store.busy"
                        data-testid="topbar-plc-select"
                        class="bg-white border border-line text-accent font-bold text-sm rounded focus:border-accent-bright focus:outline-none px-3 py-1.5 font-mono disabled:opacity-50 cursor-pointer">
                    <option value="">-- Selecciona un PLC --</option>
                    <option v-for="p in store.plcs" :key="p" :value="p">{{ p }}</option>
                </select>
                <button @click="handleRefreshPlcs" :disabled="store.busy"
                        data-testid="topbar-refresh-plcs"
                        class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    <span v-if="store.busy" class="animate-spin">↻</span>
                    <span v-else>🔍</span>
                    {{ store.busy ? 'Buscando...' : 'Buscar PLCs' }}
                </button>
            </div>
        </header>
    `,
};
