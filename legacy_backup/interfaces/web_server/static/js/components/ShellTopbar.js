/**
 * Componente ShellTopbar — barra superior cross-cutting del shell
 * corporativo (v3.0, sept-2026).
 *
 * Tras la v3, la topbar se reduce a un rol pasivo: solo pinta el
 * breadcrumb (Área · Sub-vista) a la izquierda y el PLC activo en
 * texto a la derecha. Todo lo que antes vivia aqui (indicators
 * de worker y TIA, botones Conectar/Desconectar, select de PLC,
 * boton "Buscar PLCs") migra al primer card de
 * ``BloquesCacheView.js``, que es donde el operario realmente
 * decide la conexion y la seleccion del PLC.
 *
 * El split es deliberado: la topbar es chrome (lee estado, no
 * propone acciones); la vista de Cache del PLC es donde el
 * operario interactua con el state machine del worker persistente.
 * Asi la topbar queda minimalista y la accion vive junto al
 * contenido que la consume.
 *
 * Funcionalidad que se queda en la topbar:
 *   * Breadcrumb del área (`<Área> · <Sub-vista>`).
 *   * Texto del PLC activo (``PLC: <nombre>`` o ``PLC: —`` si
 *     no hay seleccion).
 *
 * Funcionalidad que se movio al card 1 de BloquesCacheView:
 *   * WorkerStatusIndicator + TiaConnectionIndicator (ahora como
 *     texto "Worker: vivo/muerto" y "TIA: <state>", con la
 *     misma paleta de colores).
 *   * Botones Conectar / Desconectar (siempre visibles,
 *     :disabled segun state machine).
 *   * Select de PLC + boton Buscar PLCs (siempre visibles,
 *     :disabled segun estado de conexion).
 *   * Caption del proyecto TIA.
 *
 * Es cross-cutting: vive en `/js/components/` y se monta en
 * `main.js` (el shell raíz) una sola vez. Las áreas NO lo
 * importan — es parte del chrome, no de la navegación.
 *
 * Tema: capa clara. `bg-white` para el header, `border-line` para
 * el separador inferior. Sin hex hardcoded. El feedback largo
 * (ProgressIndicator) sigue viviendo en el ShellSidebar; este
 * componente es SOLO breadcrumb + texto PLC.
 *
 * Tras la v2 del rediseño "Modern Corporate", la selección de PLC
 * y el indicador de proyecto migran del sidebar a una barra
 * superior pegada al borde de la columna derecha (entre la
 * cabecera del shell y el área de contenido). En la v2.1 se ha
 * aligerado el visual y en la v2.2 (sept-2026) se reorganiza el
 * bloque derecho para acomodar el state machine del worker
 * persistente:
 *
 *   * Altura reducida de ``h-16`` (64 px) a ``h-14`` (56 px) (v2.1).
 *   * Eliminado el círculo animado de status (busy/ok/idle)
 *     que tenía la v2 (v2.1).
 *   * Eliminado el marco ``bg-surface-sunken border rounded-lg``
 *     que envolvía el bloque PLC. Layout inline con solo
 *     ``flex items-center gap-2`` (v2.1).
 *   * **v2.2:** el bloque derecho ahora se organiza como
 *     ``[Worker indicator] [TIA Portal indicator]
 *      [Conectar|Desconectar] [PLC: list] [Buscar PLCs]``.
 *     Antes de sept-2026, el operario solo podia "reconectar"
 *     haciendo click en el circulo de TIA. Ahora el worker
 *     arranca en estado ``idle`` (subproceso vivo sin portal
 *     attached) y hace falta un botón explícito "Conectar" para
 *     pedir el attach. La barra refleja el estado actual con:
 *       - "Conectar" visible si ``state in {idle, error}``.
 *       - "Desconectar" visible si ``state in {connecting, connected}``.
 *       - Lista de PLCs visible SOLO si ``state == "connected"``
 *         y hay PLCs en ``store.plcs``.
 *       - "Buscar PLCs" visible SOLO si ``state == "connected"``
 *         (sin attach no hay PLCs que listar).
 *
 * Funcionalidad intacta respecto a v2.1:
 *   * Pinta el breadcrumb del área (`<Área> · <Sub-vista>`).
 *   * Sigue leyendo de `store.selectedPlc`, `store.plcs`,
 *     `store.busy`, `store.projectInfo` y `store.currentView`.
 *
 * Es cross-cutting: vive en `/js/components/` y se monta en
 * `main.js` (el shell raíz) una sola vez. Las áreas NO lo
 * importan — es parte del chrome, no de la navegación.
 *
 * Tema: capa clara. `bg-white` para el header, `bg-accent` para
 * el botón CTA, `border-line` para el separador inferior y los
 * bordes del select. Sin hex hardcoded. El feedback largo
 * (ProgressIndicator) sigue viviendo en el ShellSidebar; este
 * componente es SOLO datos/breadcrumb/selección PLC/connect.
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola
 * línea. Salto de línea entre elementos del array OK.
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import {
    store,
    pushLog,
    loadAndApplyPlcBlocks,
    resetPlcState,
    connectTia,
    disconnectTia,
} from "/js/store.js";
import { apiFetchPlcs, apiFetchProjectInfo } from "/js/api.js";
import TiaConnectionIndicator from "./TiaConnectionIndicator.js";
import WorkerStatusIndicator from "./WorkerStatusIndicator.js";

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

        return {
            store,
            areaLabel,
            currentViewLabel,
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

            <!-- Derecha (v3.0): mini-card con el PLC activo.
                 Toda la accion (indicators, Conectar/Desconectar,
                 select PLC, Buscar PLCs) migro al primer card de
                 BloquesCacheView. Aqui queda un mini-card tipo
                 "badge" con el PLC: el label "PLC:" en muted y
                 el nombre del PLC en accent monospace, separados
                 por gap-2 para que se lean claramente. Asi la
                 topbar sigue siendo el sitio donde el operario
                 ve de un vistazo que PLC esta cargado, sin
                 tener que ir a la vista de Cache del PLC. -->
            <div class="inline-flex items-center gap-2 bg-surface-sunken border border-line rounded-md px-3 py-1.5 text-xs"
                 data-testid="topbar-plc-text">
                <span class="text-ink-muted">PLC:</span>
                <span class="font-mono font-semibold text-accent">{{ store.selectedPlc || '—' }}</span>
            </div>
        </header>
    `,
};
