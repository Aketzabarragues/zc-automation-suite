/**
 * Componente ShellTopbar — barra superior cross-cutting del shell
 * corporativo (v2.2).
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
    components: {
        TiaConnectionIndicator,
        WorkerStatusIndicator,
    },
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
         * State reactivo del worker TIA persistente, derivado de
         * ``store.tiaConnection.state``. Refleja el state
         * machine sept-2026 (``idle | connecting | connected |
         * error``). Lo exponemos al template como variable plana
         * (regla Vue 3 sin build step) para no acceder a
         * ``store.tiaConnection`` directamente en el template.
         */
        const tiaState = computed(() => {
            return (store.tiaConnection && store.tiaConnection.state) || "idle";
        });

        /**
         * Flag derivado: el worker está conectado a TIA Portal
         * (``state === "connected"``). Es la condición para
         * mostrar la lista de PLCs y el botón "Buscar PLCs".
         * ``false`` en cualquier otro estado (idle / connecting /
         * error) para evitar que el operario vea PLCs stale o
         * intente refrescar sin tener portal attached.
         */
        const isTiaConnected = computed(() => tiaState.value === "connected");

        /**
         * Flag derivado: el botón "Conectar" debe mostrarse.
         * Visible cuando ``state in {idle, error}`` (operario
         * puede pedir un attach a TIA). Oculto en ``connecting``
         * (ya hay un attach en curso, el botón seria no-op
         * visualmente y podria confundir) y en ``connected``
         * (ahi mostramos "Desconectar" en su lugar).
         */
        const showConnectButton = computed(() => {
            return tiaState.value === "idle" || tiaState.value === "error";
        });

        /**
         * Flag derivado: el botón "Desconectar" debe mostrarse.
         * Visible cuando ``state in {connecting, connected}``.
         * En ``connecting`` permite al operario abortar un attach
         * si tarda demasiado (el backend maneja el detach
         * idempotente). En ``connected`` es el camino normal
         * para "soltar" TIA sin matar el worker persistente.
         */
        const showDisconnectButton = computed(() => {
            return tiaState.value === "connecting" || tiaState.value === "connected";
        });

        /**
         * Flag derivado: la lista de PLCs (``<select>`` +
         * caption del proyecto) debe ser visible. SOLO si el
         * worker está conectado a TIA y hay PLCs detectados.
         * Antes de sept-2026, el ``<select>`` se mostraba
         * siempre (con lista vacía si TIA no estaba conectado);
         * ahora lo ocultamos para no confundir al operario con
         * una lista de PLCs que ya no aplica tras un detach.
         */
        const showPlcList = computed(() => {
            return isTiaConnected.value && Array.isArray(store.plcs)
                && store.plcs.length > 0;
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

        /**
         * Handler del botón "Conectar" del topbar (v2.2). El
         * operario lo pulsa cuando el worker está en estado
         * ``idle`` (recien arrancado o tras un "Desconectar"
         * previo) o ``error`` (attach anterior falló). Delega
         * en ``connectTia()`` (helper del store) que setea
         * ``state="connecting"`` y dispara
         * ``POST /api/v1/tia/connect``. La promesa se ignora
         * porque el feedback de la operación larga llega por
         * el propio indicador (color pulsante → verde) y por
         * los logs que ``connectTia`` empuja a ``ConsolaLogs``.
         */
        async function handleConnect() {
            await connectTia();
        }

        /**
         * Handler del botón "Desconectar" del topbar (v2.2).
         * Complementario a ``handleConnect``: pide al worker
         * persistente que haga ``detach_portal`` (NO destructivo:
         * el subproceso worker sigue vivo, solo pierde la
         * referencia al portal TIA). El helper ``disconnectTia``
         * del store se encarga del POST y, tras exito, limpia
         * los slots del PLC (``plcs``, ``selectedPlc``,
         * ``plcBlocksCache``, ``projectInfo``) para que el
         * topbar no muestre datos stale.
         */
        async function handleDisconnect() {
            await disconnectTia();
        }

        return {
            store,
            areaLabel,
            currentViewLabel,
            tiaState,
            isTiaConnected,
            showConnectButton,
            showDisconnectButton,
            showPlcList,
            handleRefreshPlcs,
            onPlcSelected,
            handleConnect,
            handleDisconnect,
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

            <!-- Derecha (v2.2): bloque reorganizado para el state
                 machine del worker persistente.

                 Orden de izquierda a derecha:
                   1. WorkerStatusIndicator (verde=worker vivo,
                      gris=muerto). Ortogonal al estado de attach.
                   2. TiaConnectionIndicator (verde=connected,
                      ambar pulsante=connecting, gris=idle,
                      rojo=error). Clickable para pedir "Conectar"
                      cuando esta en idle/error.
                   3. Boton "Conectar" (v2.2) — visible SOLO si
                      state in {idle, error}. Dispara handleConnect.
                   4. Boton "Desconectar" (v2.2) — visible SOLO si
                      state in {connecting, connected}. Dispara
                      handleDisconnect, que limpia los slots del
                      PLC tras el detach OK.
                   5. Lista de PLCs (label + caption del proyecto
                      + select) — visible SOLO si state == "connected"
                      y store.plcs.length > 0.
                   6. Boton "Buscar PLCs" — visible SOLO si
                      state == "connected".

                 Layout inline con 'flex items-center gap-2';
                 el espaciado lo controla 'gap'. -->
            <div class="flex items-center gap-2">
                <WorkerStatusIndicator />
                <TiaConnectionIndicator @connect="handleConnect" />

                <button v-if="showConnectButton"
                        type="button"
                        @click="handleConnect"
                        :disabled="store.busy"
                        data-testid="topbar-connect-tia"
                        class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    <span>🔌</span>
                    Conectar
                </button>

                <button v-if="showDisconnectButton"
                        type="button"
                        @click="handleDisconnect"
                        :disabled="store.busy"
                        data-testid="topbar-disconnect-tia"
                        class="px-3 py-1.5 text-accent font-semibold text-xs bg-surface-sunken hover:bg-accent-subtle rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                    <span v-if="store.busy" class="animate-spin">↻</span>
                    <span v-else>⏏</span>
                    {{ store.busy ? 'Desconectando...' : 'Desconectar' }}
                </button>

                <template v-if="showPlcList">
                    <label class="text-[10px] font-bold text-ink-muted uppercase tracking-widest">PLC:</label>
                    <p v-if="store.projectInfo && store.projectInfo.name"
                       class="text-[11px] font-mono text-ink-muted truncate max-w-[200px]"
                       :title="store.projectInfo.name"
                       data-testid="topbar-project-name">
                        {{ store.projectInfo.name }}
                    </p>
                    <select v-model="store.selectedPlc" @change="onPlcSelected"
                            :disabled="store.busy"
                            data-testid="topbar-plc-select"
                            class="bg-white border border-line text-accent font-bold text-sm rounded focus:border-accent-bright focus:outline-none px-3 py-1.5 font-mono disabled:opacity-50 cursor-pointer">
                        <option value="">-- Selecciona un PLC --</option>
                        <option v-for="p in store.plcs" :key="p" :value="p">{{ p }}</option>
                    </select>
                </template>

                <button v-if="isTiaConnected"
                        type="button"
                        @click="handleRefreshPlcs"
                        :disabled="store.busy"
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
