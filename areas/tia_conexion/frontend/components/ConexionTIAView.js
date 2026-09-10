/**
 * ConexionTIAView — vista principal del area `tia_conexion`.
 *
 * Muestra el estado de la conexion con TIA Portal y permite al operario
 * conectar / desconectar. Es el "Hola Mundo" operativo de Fase 3: valida
 * end-to-end que la arquitectura (Engine + SSE + usePlc + area) esta
 * completa.
 *
 * Capa visual: 4 cards en grid responsive (1 col en movil, 2 en tablet,
 * 4 en desktop). El contenido es reactivo al SSE del Engine: cualquier
 * cambio en `plc.DBs.estado_conexion` o `plc.FBs.ConexionTIA` se
 * refleja sin polling.
 *
 * Tema: Industrial Claro. Solo tokens semanticos del tema
 * (`bg-surface*`, `text-ink*`, `border-line*`, `bg-accent`,
 * `text-accent`).
 *
 * Regla Vue 3 sin build step (AGENTS.md §4.3): el template NO accede
 * a `plc.X` directamente. TODO acceso a `usePlc()` se hace via
 * `computed` retornado del `setup()`. El template solo lee variables
 * planas (`tiaState`, `plcs`, `isConnecting`, etc.).
 */
import { computed, onMounted } from "/js/vendor/vue.esm-browser.prod.js";
import { usePlc } from "/js/composables/usePlc.js";
import EmptyState from "/js/components/EmptyState.js";

export default {
    name: "ConexionTIAView",
    components: { EmptyState },
    setup() {
        const plc = usePlc();

        // ── Estado del Engine (reactivo, viene del SSE) ─────────────
        const tiaState = computed(
            () => plc.DBs.estado_conexion.tia_state || "idle"
        );
        const projectName = computed(
            () => plc.DBs.estado_conexion.project_name || ""
        );
        const projectPath = computed(
            () => plc.DBs.estado_conexion.project_path || ""
        );
        const plcs = computed(() => plc.DBs.estado_conexion.plcs || []);
        const lastError = computed(
            () => plc.DBs.estado_conexion.last_error || ""
        );

        // ── Estado del FB ConexionTIA (reactivo) ────────────────────
        const fb = computed(() => plc.FBs.ConexionTIA || null);
        const fbStep = computed(() => fb.value?.nStep ?? 0);
        const fbProgress = computed(() => fb.value?.progress ?? 0);
        const fbStepName = computed(() => fb.value?.step_name || "");
        const fbError = computed(() => fb.value?.error || "");
        const fbIsError = computed(() => fbStep.value === 99);

        // ── Flags de UI ─────────────────────────────────────────────
        const isIdle = computed(() => tiaState.value === "idle");
        const isConnecting = computed(() => tiaState.value === "connecting");
        const isConnected = computed(() => tiaState.value === "connected");
        const isError = computed(() => tiaState.value === "error");

        // ── Acciones (delegadas al composable) ──────────────────────
        async function onConnect() {
            try {
                await plc.startFb("ConexionTIA");
            } catch (e) {
                // El FB entra en nStep=99 con error_msg; usePlc no
                // propaga la excepcion al SSE (la captura el Engine).
                // El composable solo rechaza si el POST HTTP falla.
                console.error("startFb ConexionTIA fallo:", e);
            }
        }
        async function onDisconnect() {
            try {
                await plc.disconnectFb("ConexionTIA");
            } catch (e) {
                console.error("disconnectFb ConexionTIA fallo:", e);
            }
        }

        // ── Lifecycle ───────────────────────────────────────────────
        // Aseguramos que el catalogo de areas esta cargado al montar
        // (puede que el Welcome ya lo haya hecho, pero es idempotente).
        onMounted(() => {
            if (!plc.areas || plc.areas.length === 0) {
                plc.fetchAreas().catch((e) =>
                    console.warn("fetchAreas fallo:", e)
                );
            }
        });

        return {
            // Estado (computed planos para el template)
            tiaState,
            projectName,
            projectPath,
            plcs,
            lastError,
            fbStep,
            fbProgress,
            fbStepName,
            fbError,
            fbIsError,
            isIdle,
            isConnecting,
            isConnected,
            isError,
            // Acciones
            onConnect,
            onDisconnect,
        };
    },
    template: /* html */ `
        <div class="flex flex-col gap-4" data-testid="conexion-tia-view">
            <!-- Cabecera del area: titulo humano + icono -->
            <header class="flex items-center gap-3 pb-2 border-b border-line">
                <span class="text-3xl" aria-hidden="true">🔌</span>
                <div>
                    <h1 class="text-2xl font-bold text-ink">Conexion TIA Portal</h1>
                    <p class="text-sm text-ink-muted">
                        Estado del worker OT y attach a TIA Portal.
                    </p>
                </div>
            </header>

            <!-- Card 1: Estado de la conexion (circulo + botones) -->
            <section class="bg-surface-raised border border-line rounded-lg p-5 shadow-sm"
                     data-testid="tia-state-card">
                <div class="flex items-center justify-between mb-4">
                    <h2 class="text-sm font-bold uppercase tracking-widest text-ink-muted">
                        Estado de la conexion
                    </h2>
                    <div class="flex items-center gap-2"
                         :aria-label="'Estado TIA: ' + tiaState">
                        <span
                            :class="[
                                'w-4 h-4 rounded-full transition-colors',
                                isConnected ? 'bg-green-500' :
                                isConnecting ? 'bg-amber-500 animate-pulse' :
                                isError ? 'bg-red-500' : 'bg-gray-400'
                            ]"
                            data-testid="tia-state-circle"></span>
                        <span class="text-sm font-mono font-semibold text-ink"
                              data-testid="tia-state-text">
                            {{ tiaState }}
                        </span>
                    </div>
                </div>

                <!-- Botones Conectar / Desconectar -->
                <div class="flex gap-3">
                    <button @click="onConnect"
                            :disabled="isConnecting || isConnected"
                            :class="[
                                'px-5 py-2.5 font-semibold text-sm rounded-md transition-colors duration-150',
                                'focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface-raised',
                                (isConnecting || isConnected)
                                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                                    : 'bg-accent text-white hover:opacity-90 cursor-pointer'
                            ]"
                            data-testid="tia-connect-btn">
                        Conectar
                    </button>
                    <button @click="onDisconnect"
                            :disabled="isIdle || isError"
                            :class="[
                                'px-5 py-2.5 font-semibold text-sm rounded-md transition-colors duration-150',
                                'focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface-raised',
                                (isIdle || isError)
                                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                                    : 'bg-surface text-ink border border-line hover:bg-surface-sunken cursor-pointer'
                            ]"
                            data-testid="tia-disconnect-btn">
                        Desconectar
                    </button>
                </div>

                <!-- Error: solo visible si hay last_error en la DB -->
                <p v-if="lastError"
                   class="mt-4 px-4 py-2.5 bg-red-50 border border-red-200 rounded-md text-sm text-red-700 font-mono"
                   data-testid="tia-last-error">
                    {{ lastError }}
                </p>
            </section>

            <!-- Card 2: Proyecto TIA -->
            <section class="bg-surface-raised border border-line rounded-lg p-5 shadow-sm"
                     data-testid="tia-project-card">
                <h2 class="text-sm font-bold uppercase tracking-widest text-ink-muted mb-3">
                    Proyecto TIA
                </h2>
                <dl class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                    <div>
                        <dt class="text-ink-muted text-xs uppercase tracking-wider">Nombre</dt>
                        <dd class="font-mono text-ink mt-0.5"
                            data-testid="tia-project-name">
                            {{ projectName || '—' }}
                        </dd>
                    </div>
                    <div>
                        <dt class="text-ink-muted text-xs uppercase tracking-wider">Path</dt>
                        <dd class="font-mono text-ink-muted mt-0.5 break-all"
                            data-testid="tia-project-path">
                            {{ projectPath || '—' }}
                        </dd>
                    </div>
                </dl>
            </section>

            <!-- Card 3: PLCs del proyecto (lista o EmptyState) -->
            <section class="bg-surface-raised border border-line rounded-lg p-5 shadow-sm"
                     data-testid="tia-plcs-card">
                <h2 class="text-sm font-bold uppercase tracking-widest text-ink-muted mb-3">
                    PLCs del proyecto
                    <span v-if="plcs.length > 0"
                          class="ml-2 text-accent normal-case"
                          data-testid="tia-plcs-count">
                        ({{ plcs.length }})
                    </span>
                </h2>
                <ul v-if="plcs.length > 0"
                    class="divide-y divide-line"
                    data-testid="tia-plcs-list">
                    <li v-for="(plc, idx) in plcs" :key="idx"
                        class="py-2 font-mono text-sm text-ink">
                        {{ plc.name || plc }}
                    </li>
                </ul>
                <EmptyState v-else
                    icon="📋"
                    title="Sin PLCs listados"
                    description="Conecta con TIA Portal y se listaran los PLCs del proyecto activo." />
            </section>

            <!-- Card 4: FlowProgress del FB activo (nStep + barra) -->
            <section class="bg-surface-raised border border-line rounded-lg p-5 shadow-sm"
                     data-testid="tia-fb-card">
                <h2 class="text-sm font-bold uppercase tracking-widest text-ink-muted mb-3">
                    Progreso del FB ConexionTIA
                </h2>
                <div v-if="fb" class="space-y-3">
                    <!-- Barra de progreso -->
                    <div class="space-y-1">
                        <div class="flex justify-between text-xs">
                            <span class="text-ink-muted font-mono">
                                nStep {{ fbStep }}: {{ fbStepName || '—' }}
                            </span>
                            <span class="text-ink-muted font-mono">
                                {{ fbProgress }}%
                            </span>
                        </div>
                        <div class="h-2 bg-surface-sunken rounded overflow-hidden">
                            <div :class="[
                                    'h-full transition-all duration-300 rounded',
                                    fbIsError ? 'bg-red-500' :
                                    fbStep === 30 ? 'bg-green-500' :
                                    'bg-accent'
                                ]"
                                :style="{ width: fbProgress + '%' }"
                                data-testid="tia-fb-progress-bar">
                            </div>
                        </div>
                    </div>
                    <!-- Error del FB (si lo hay) -->
                    <p v-if="fbError"
                       class="px-4 py-2.5 bg-red-50 border border-red-200 rounded-md text-sm text-red-700 font-mono"
                       data-testid="tia-fb-error">
                        {{ fbError }}
                    </p>
                </div>
                <EmptyState v-else
                    icon="⏳"
                    title="FB inactivo"
                    description="Pulsa Conectar para arrancar el Function Block ConexionTIA." />
            </section>
        </div>
    `,
};
