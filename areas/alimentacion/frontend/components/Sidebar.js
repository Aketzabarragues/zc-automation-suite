/**
 * Componente Sidebar (panel lateral) — específico del área Alimentación.
 *
 * Estructura (de arriba a abajo):
 *   1. Cabecera: "← Volver al inicio" + título "ZC Automation Suite" + área activa.
 *   2. Selección PLC: caption con el nombre del proyecto TIA activo (si se
 *      conoce), desplegable de PLCs, y botón "Buscar PLCs" (consulta TIA
 *      Portal vía Openness y rellena el dropdown en una sola acción).
 *   3. Navegación entre vistas: "Inicio del área" / "Definición programación"
 *      / "Cache de bloques" / "Dispositivos" / "Procesos".
 *
 * Ya NO contiene:
 *   - "1. Maestro Excel" (movido al inicio de la vista "Definición programación").
 *   - "3. Conexión TIA Portal" (Hot-Attach / Cold-Start). El usuario lanza
 *     TIA Portal manualmente fuera de la app; el botón "Buscar PLCs" de
 *     "Selección PLC" basta para poblar el dropdown Y leer el nombre del
 *     proyecto, todo en una sola acción.
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (`bg-surface*`, `border-line*`, `text-ink*`, `bg-accent`, `text-accent`).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 */
import { computed } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
// Imports absolutos. Los componentes del área se sirven bajo
// ``/static/areas/alimentacion/frontend/components/`` (path
// servido por el FastAPI shell), pero los cross-cutting
// (``store.js``, ``api.js``, ``ProgressIndicator``) viven en
// ``/js/`` y NO se mueven. Un import relativo ``../../../../js/X.js``
// se resolvería contra la URL del módulo y daría
// ``/static/js/X.js`` (404). Usar absolutos evita el problema.
import { store, pushLog, goToWelcome, goToSubview, loadAndApplyPlcBlocks } from "/js/store.js";
import { apiFetchPlcs, apiFetchProjectInfo } from "/js/api.js";
import ProgressIndicator from "/js/components/ProgressIndicator.js";

export default {
    name: "AlimentacionSidebar",
    components: { ProgressIndicator },
    setup() {
        /**
         * Etiqueta del área actualmente seleccionada, derivada del
         * catálogo. Si no hay área o no se encuentra en el catálogo,
         * se muestra un placeholder neutro.
         */
        const areaLabel = computed(() => {
            if (!store.selectedArea) return "—";
            const a = store.availableAreas.find(
                (x) => x.key === store.selectedArea
            );
            return a ? a.label : store.selectedArea;
        });

        /**
         * Refresca el desplegable de PLCs Y carga el nombre del proyecto
         * TIA conectado. Las dos llamadas se hacen en paralelo (mismo
         * click del operario) para minimizar la latencia visible. Si TIA
         * no está conectado, ambos endpoints devuelven
         * ``{ok: false, error: "..."}`` y el sidebar queda en estado
         * degradado: lista vacía, sin caption de proyecto.
         */
        async function handleRefreshPlcs() {
            store.busy = true;
            try {
                const [plcsResp, infoResp] = await Promise.all([
                    apiFetchPlcs(),
                    apiFetchProjectInfo(),
                ]);

                if (plcsResp.ok && plcsResp.data && plcsResp.data.plcs) {
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
         * operario navegue a ella (no tiene que esperar a su
         * ``onMounted``). La vista, además, recarga reactivamente
         * si el PLC cambia mientras está abierta.
         *
         * La promesa se ignora: el feedback de la operación larga
         * llega por el ``ProgressTracker`` backend, que el
         * ``ProgressIndicator`` (anclado al fondo del sidebar)
         * muestra automáticamente gracias al polling 500 ms de
         * ``main.js``. No añadimos ningún widget nuevo en la SPA.
         */
        async function onPlcSelected() {
            await loadAndApplyPlcBlocks(store.selectedPlc);
        }

        return {
            store,
            areaLabel,
            handleRefreshPlcs,
            onPlcSelected,
            goToWelcome,
            goToSubview,
        };
    },
    template: /* html */ `
        <aside class="w-80 flex-shrink-0 bg-surface-raised border-r border-line flex flex-col p-5 overflow-y-auto">
            <!-- Cabecera: volver + título + área activa -->
            <div class="mb-6">
                <button @click="goToWelcome"
                    class="text-xs text-ink-muted hover:text-accent flex items-center gap-1 mb-2"
                    data-testid="sidebar-back">
                    ← Volver al inicio
                </button>
                <h1 class="text-xl font-bold text-accent leading-tight">ZC Automation Suite</h1>
                <p class="text-xs text-ink-muted mt-0.5">
                    Área activa: <span class="font-semibold text-ink">{{ areaLabel }}</span>
                </p>
            </div>

            <!-- Selección PLC -->
            <section class="mb-6">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Selección PLC</label>
                <!-- Caption del proyecto TIA activo. Solo aparece después de
                     pulsar "Buscar PLCs" y si el backend devolvió un nombre. -->
                <p v-if="store.projectInfo && store.projectInfo.name"
                   class="text-xs text-ink-muted mb-1.5 font-mono truncate"
                   :title="store.projectInfo.name"
                   data-testid="sidebar-project-name">
                    Proyecto: {{ store.projectInfo.name }}
                </p>
                <select v-model="store.selectedPlc" @change="onPlcSelected"
                    :disabled="store.plcs.length === 0 || store.busy"
                    class="w-full bg-surface-sunken border border-line rounded px-2 py-1.5 text-sm text-ink disabled:opacity-50">
                    <option value="">-- Selecciona un PLC --</option>
                    <option v-for="p in store.plcs" :key="p" :value="p">{{ p }}</option>
                </select>
                <button @click="handleRefreshPlcs" :disabled="store.busy"
                    class="mt-2 text-xs px-2 py-1 bg-surface-sunken hover:bg-surface-sunken border border-line rounded text-ink disabled:opacity-50"
                    data-testid="sidebar-refresh-plcs">
                    Buscar PLCs
                </button>
            </section>

            <!-- Navegación entre vistas del área -->
            <section class="mb-6">
                <label class="block text-xs font-semibold text-ink-muted uppercase mb-2">Navegación</label>
                <div class="flex flex-col gap-1.5">
                    <button @click="goToSubview('landing')"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'landing' ? 'bg-accent border-accent text-ink-inverse font-semibold' : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        🏠 Inicio del área
                    </button>
                    <button @click="goToSubview('def')"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'def' ? 'bg-accent border-accent text-ink-inverse font-semibold' : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        📊 Definición programación
                    </button>
                    <button @click="goToSubview('cache')"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'cache' ? 'bg-accent border-accent text-ink-inverse font-semibold' : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        📦 Cache de bloques
                    </button>
                    <button @click="goToSubview('disp')"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'disp' ? 'bg-accent border-accent text-ink-inverse font-semibold' : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        ⚡ Dispositivos
                    </button>
                    <button @click="goToSubview('proc')"
                        :class="['text-left text-xs px-3 py-2 rounded border',
                                 store.currentView === 'proc' ? 'bg-accent border-accent text-ink-inverse font-semibold' : 'bg-surface-sunken border-line hover:bg-surface-sunken text-ink']">
                        ⚙️ Procesos
                    </button>
                </div>
            </section>

            <!-- Indicador de progreso (fijo en la parte inferior del sidebar).
                 Aquí aparece el task de "Cache de bloques de <plc>" cuando
                 el operario selecciona un PLC en el desplegable de arriba. -->
            <ProgressIndicator />
        </aside>
    `,
};
