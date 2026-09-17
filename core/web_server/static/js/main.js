/**
 * main.js — Ensamblador de la SPA Vue 3 con ESM.
 *
 * Responsabilidades:
 *   * Importar ``createApp`` del build ESM de Vue 3.
 *   * Registrar los 6 componentes cross-cutting del shell:
 *     Welcome, ConsolaLogs, ProgressIndicator, ShellTopbar,
 *     ShellSidebar, plcpanelview.
 *   * Enrutar entre welcome y el layout de área según
 *     ``store.topLevelView``.
 *   * Dentro del área, enrutar entre sub-vistas según
 *     ``store.currentView``. Hay DOS familias de vistas:
 *       - "plc" (reservada del shell) → renderiza ``<plcpanelview />``
 *         (panel comun de gestion del PLC, comun a TODAS las areas).
 *       - resto de keys → renderiza ``<component :is="currentViewComponent" />``
 *         resuelto del manifest del area activa.
 *   * Cargar dinámicamente los componentes del área seleccionada vía
 *     ``area-loader.js`` (sin imports hardcoded de las áreas).
 *   * Montar la app en ``#app``.
 *
 * NO hay build step: el navegador carga los módulos directamente desde
 * la red (CDN) o desde ``/js/`` servido por FastAPI.
 */
import { createApp, computed, nextTick } from "/js/vendor/vue.esm-browser.prod.js";
import { store, goToArea, goToSubview, loadCatalog } from "./store.js";
import { apiFetchMemory } from "./api.js";
import { loadArea, mountArea } from "./area-loader.js";
import Welcome from "./components/Welcome.js";
import ConsolaLogs from "./components/ConsolaLogs.js";
import ProgressIndicator from "./components/ProgressIndicator.js";
import ShellTopbar from "./components/ShellTopbar.js";
import ShellSidebar from "./components/ShellSidebar.js";
import plcpanelview from "./components/plcpanelview.js";

/** Componente raíz: enrutador top-level (welcome) + layout de área. */
const App = {
    components: {
        Welcome,
        ConsolaLogs,
        ProgressIndicator,
        ShellTopbar,
        ShellSidebar,
        plcpanelview,
    },
    setup() {
        /**
         * Llamado por Definición programación al pulsar "Refrescar".
         * Mantenemos la lógica de la API en ``main.js`` (no en el
         * componente) para preservar el principio de "componente
         * tonto" y poder mockear la API en tests.
         */
        async function refreshMemory() {
            store.busy = true;
            try {
                const r = await apiFetchMemory();
                if (r.ok && r.data && r.data.ok) {
                    store.memoryState = r.data;
                }
            } finally {
                store.busy = false;
            }
        }
        /**
         * Manejador del ``select`` emitido por ``Welcome``. El
         * ``Welcome`` ya validó que el área está ``available``.
         *
         * Orden crítico para evitar una carrera con Vue 3:
         *   1. Cargar el manifest del área (sin tocar ``topLevelView``).
         *   2. Registrar los componentes del área en la app con
         *      ``mountArea(_app, key)``. Esto es NO-reactivo: Vue no
         *      se entera de que hay componentes nuevos hasta el
         *      próximo re-render.
         *   3. Asignar el manifest a ``store.areaManifest`` y poner
         *      ``topLevelView = "area"``. AHORA Vue re-renderiza el
         *      shell, y los componentes ya están registrados.
         *
         * Si invertimos el orden (transicionar primero, montar
         * después), Vue re-renderiza con ``topLevelView === "area"``
         * PERO los componentes del área aún no están en el registry
         * de la app, así que ``<component :is="sidebarComponent" />``
         * no resuelve nada y la SPA queda en blanco (el bug que
         * rompió la demo al introducir el area-loader).
         *
         * Si el manifest viene vacío (loaders: {}), la SPA
         * transiciona igualmente a la vista de área pero muestra
         * el mensaje de "Área no soportada en el frontend" (modo
         * degradado), gracias al flag ``areaManifestEmpty``.
         */
        async function onAreaSelected(key) {
            if (!key) return;
            // Reset selectivo (sept-2026, pedido operario): solo se
            // limpia la prevision y la info del proyecto TIA. Mantenemos
            // plcs, selectedPlc, uploadSummary y lastExcelFile para que
            // sobrevivan a una salida + re-entrada al area. Coincide con
            // ``store.goToArea`` (la version async del helper).
            store.selectedArea = key;
            store.currentView = "landing";
            store.projectInfo = null;
            store.previewData = null;
            try {
                // ``mountArea`` ya hace ``loadArea`` internamente + registra
                // los componentes del area en la app Vue. Devuelve el manifest
                // para asignarlo a ``store.areaManifest`` sin un segundo fetch.
                const manifest = await mountArea(_app, key);
                // Transicionar a la vista de area (dispara re-render con
                // TODO ya listo: manifest + componentes).
                store.areaManifest = manifest && manifest.id ? manifest : null;
                store.topLevelView = "area";
            } catch (e) {
                console.error("[App] onAreaSelected:", e);
                return;
            }
            // ``nextTick`` no es estrictamente necesario pero es
            // defensivo: garantiza que el re-render ya se hizo
            // antes de que el usuario pueda interactuar.
            await nextTick();
        }
        /**
         * Manejador del ``select`` emitido por ``AreaLanding``.
         * Cambia la sub-vista dentro del área activa.
         */
        function onSubviewSelected(key) {
            goToSubview(key);
        }
        /**
         * Manejador del ``navigate`` emitido por ``ShellSidebar``.
         * Recibe la key del item pulsado (incluido ``"plc"`` del
         * boton comun). Para "plc" y para keys de las views del area
         * hace lo mismo: ``goToSubview(key)``. El main.js enruta
         * "plc" al PlcPanelView comun o al componente del manifest
         * segun el template.
         */
        function onShellNavigate(key) {
            if (!key) return;
            // ``"plc"`` es key reservada del shell (boton comun del
            // ShellSidebar). ``goToSubview`` la rechazaria porque no
            // esta en el manifest del area. La aplicamos directo.
            if (key === "plc") {
                store.currentView = "plc";
                return;
            }
            // Para el resto de keys validamos contra el manifest.
            goToSubview(key);
        }
        /**
         * Manejador del ``back`` emitido por ``ShellSidebar``.
         * Vuelve al Welcome (resetea topLevelView y areaManifest).
         */
        function onShellBack() {
            store.topLevelView = "welcome";
            store.areaManifest = null;
            store.selectedArea = "";
            store.currentView = "landing";
        }
        /**
         * Nombre del componente de la sub-vista activa para keys
         * del area (es decir, todo lo que NO es ``"plc"`` que es del
         * shell). Leído del manifest. Si la key no está, devuelve
         * ``null`` y la vista no se renderiza.
         */
        const currentViewComponent = computed(() => {
            if (store.currentView === "plc") return null;  // del shell
            const m = store.areaManifest;
            if (!m || !m.components || !m.components.views) return null;
            return m.components.views[store.currentView] || null;
        });
        /**
         * True si la sub-vista activa es ``"plc"``, que es del shell
         * (no del area). El template usa este flag para decidir
         * entre ``<plcpanelview />`` y ``<component :is="currentViewComponent" />``.
         */
        const isPlcView = computed(() => store.currentView === "plc");
        /**
         * Flag derivado: estamos en un área cuyo manifest no se pudo
         * cargar (endpoint no existe, loaders vacíos o red caída). Lo
         * usa el template para mostrar un mensaje claro en lugar de
         * un sidebar/main vacío.
         */
        const areaManifestEmpty = computed(() => {
            return (
                store.topLevelView === "area" &&
                !!store.selectedArea &&
                (!store.areaManifest ||
                    !store.areaManifest.loaders ||
                    Object.keys(store.areaManifest.loaders || {}).length === 0)
            );
        });
        /**
         * ``{ key, label, icon }`` del área activa para alimentar
         * el breadcrumb del ``ShellTopbar``. Resuelve primero
         * contra ``store.availableAreas``; si no encuentra
         * coincidencia (catálogo aún no cargado o área
         * desconocida), cae a un objeto degradado con la key
         * cruda y un emoji genérico de carpeta. Garantiza que
         * ``ShellTopbar`` siempre reciba un objeto con la
         * estructura esperada.
         */
        const topbarArea = computed(() => {
            if (!store.selectedArea) return { key: "", label: "—", icon: "📁" };
            const a = store.availableAreas.find((x) => x.key === store.selectedArea);
            if (a) return a;
            return { key: store.selectedArea, label: store.selectedArea, icon: "📁" };
        });
        return {
            store,
            refreshMemory,
            onAreaSelected,
            onSubviewSelected,
            onShellNavigate,
            onShellBack,
            currentViewComponent,
            isPlcView,
            areaManifestEmpty,
            topbarArea,
        };
    },
    template: /* html */ `
        <div class="flex flex-col flex-1 min-h-0">
            <Welcome v-if="store.topLevelView === 'welcome'" @select="onAreaSelected" />
            <div v-else class="flex flex-1 overflow-hidden min-w-0">
                <!-- 1. ShellSidebar: cross-cutting del shell (sept-2026).
                     No recibe props; lee del store. Tiene un boton
                     PLC comun + la nav del area (especifica, del manifest).
                     El padre resuelve 'navigate' y 'back'. -->
                <ShellSidebar @navigate="onShellNavigate" @back="onShellBack" />

                <!-- 2. Columna derecha: topbar + main + consola.
                     La clase ml-72 reserva el ancho del ShellSidebar
                     (que ahora es position: fixed) para que el
                     contenido no se solape con el shell oscuro. -->
                <div class="flex-1 flex flex-col min-w-0 ml-72">
                    <ShellTopbar :area="topbarArea" />

                    <main class="flex-1 min-w-0 flex flex-col p-5 overflow-y-auto">
                        <div v-if="areaManifestEmpty"
                             class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded p-10 text-center text-ink-muted">
                            <div>
                                <div class="text-5xl mb-3 opacity-40">⚠️</div>
                                <p class="mb-2 font-semibold text-ink">Área no soportada en el frontend</p>
                                <p class="text-xs">
                                    El backend no ha publicado el manifest de
                                    <strong class="text-accent">{{ store.selectedArea }}</strong>.
                                    Verifica que el endpoint
                                    <code>GET /api/v1/areas/{{ store.selectedArea }}/manifest</code>
                                    esté disponible y devuelva los
                                    <code>loaders</code> correctos.
                                </p>
                            </div>
                        </div>
                        <plcpanelview v-else-if="isPlcView" data-testid="shell-plc-panel" />
                        <component v-else-if="currentViewComponent"
                            :is="currentViewComponent"
                            @select="onSubviewSelected"
                            @refresh="refreshMemory" />
                    </main>

                    <ConsolaLogs v-if="store.topLevelView === 'area'" />
                </div>
            </div>
        </div>
    `,
};

const _app = createApp(App);
_app.component("Welcome", Welcome);
_app.component("ConsolaLogs", ConsolaLogs);
_app.component("ProgressIndicator", ProgressIndicator);
_app.component("ShellTopbar", ShellTopbar);
_app.component("ShellSidebar", ShellSidebar);
_app.component("plcpanelview", plcpanelview);
_app.mount("#app");

loadCatalog();

// ── SSE: Server-Sent Events ────────────────────────────────────
// Abre un EventSource contra /stream. El SSE es la ÚNICA
// fuente de updates del store desde 1.3.1 (los 3 setInterval de
// logs/progress/tia se eliminaron; antes coexistían como red de
// seguridad durante la migración, ahora ya no son necesarios).
//
//   - onopen: confirma que la conexión está viva.
//   - onerror: avisa si el server se cae. La UI queda "congelada"
//     hasta la reconexión; el EventSource del navegador reintenta
//     solo (comportamiento estándar del spec). El operario ve el
//     warning en F12 console (si lo tiene abierto).
//   - onmessage: parsea el JSON y actualiza el store. Ver el
//     switch de tipos abajo para el mapeo exacto event→slot.
//
// Sin wrapper, sin composables, sin ``sse.js`` nuevo: directo en
// ``main.js`` como pide el plan. La UI no cambia (mismos
// componentes, mismo copy, mismos iconos, mismos colores).
const sse = new EventSource("/stream");
sse.onopen = () => {
    console.log("[SSE] connection opened");
};
sse.onerror = (e) => {
    console.warn("[SSE] connection error", e);
};
sse.onmessage = (e) => {
    let event;
    try {
        event = JSON.parse(e.data);
    } catch (err) {
        console.warn("[SSE] evento no es JSON válido:", e.data, err);
        return;
    }
    switch (event.type) {
        case "log":
            // Append. El polling periódico (1.2.3 lo mantiene activo)
            // resetea al snapshot del LogBuffer (200 entradas); el SSE
            // solo empuja lo nuevo entre polls. Orden cronológico OK
            // porque el LogBuffer emite en orden de llegada.
            store.logs.push({
                timestamp: event.timestamp,
                level: event.level,
                message: event.message,
            });
            break;
        case "progress": {
            // El event YA ES el ProgressSnapshot (más "type"). Quitamos
            // "type" y reemplazamos el slot completo (mismo patrón que
            // el polling hace con ``r.data.progress``).
            const { type, ...snapshot } = event;
            store.progress = snapshot;
            break;
        }
        case "tia_state":
            // Solo cambia el state; el resto de campos de
            // tiaConnection (``project``, ``plcs``, ``last_ping_ok_unix``,
            // ``last_error``) se actualiza cuando llega un evento
            // ``plcs`` o ``project_info`` correspondiente. Antes de
            // 1.3.1 los mantenía ``refreshTiaConnection`` por polling.
            store.tiaConnection.state = event.state;
            break;
        case "plcs":
            // Cache: ``event.data = [{name, short_designation}, ...]``.
            // ``tiaConnection.plcs`` espera ``string[]`` (compat con
            // el shape que ya consume la SPA); ``store.plcs`` recibe
            // la lista completa con metadatos.
            store.tiaConnection.plcs = event.data.map(p => p.name);
            store.plcs = event.data;
            break;
        case "project_info":
            // Cache: ``event.data = {name, path, author, ...}``.
            store.tiaConnection.project = event.data;
            store.projectInfo = event.data;
            break;
        default:
            console.debug("[SSE] tipo de evento desconocido:", event.type);
    }
};
