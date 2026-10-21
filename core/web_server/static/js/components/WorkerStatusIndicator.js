/**
 * Componente WorkerStatusIndicator.
 *
 * Circulo pequeño (verde/gris) en el ``ShellTopbar`` que indica si el
 * hilo dedicado del subsistema TIA (``tia-loop``) esta vivo o no. Ese
 * hilo es un ``threading.Thread`` daemon en el MISMO proceso que
 * Flask: no hay subproceso ni IPC.
 *
 * ``worker_alive`` lo emite ``GET /api/v1/tia/connection`` a partir de
 * ``SyncTIAClient.loop_running``, que el cliente mantiene en True al
 * arrancar el hilo y en False al pararlo o al morir por crash.
 *
 * Es ORTOGONAL al ``TiaConnectionIndicator`` (que muestra el estado de
 * attach a TIA Portal: connected/connecting/disconnected/error):
 *   - ``TiaConnectionIndicator`` refleja el attach a TIA: el hilo puede
 *     estar vivo y tener un attach fallido. Eso es "desconectado" para
 *     la conexion, pero el hilo SIGUE vivo.
 *   - ``WorkerStatusIndicator`` refleja solo el hilo:
 *     "vivo" = ``loop_running``; "muerto" = nunca arranco o ya termino.
 *
 * REGLA Vue 3 sin build step: el template NO tiene acceso directo
 * a ``store`` (los ``import`` a nivel de modulo son invisibles para
 * el compilador en runtime). Por eso TODO el acceso a ``store`` se
 * encapsula en ``computed`` y se retorna explicitamente desde
 * ``setup()``. El template solo lee ``alive``, ``colorClass`` y
 * ``tooltip``.
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";

export default {
    name: "WorkerStatusIndicator",
    setup() {
        // ``worker_alive`` lo escribe el backend en
        // ``GET /api/v1/tia/connection`` (campo ``worker_alive``)
        // y el store lo expone como ``store.tiaConnection.worker_alive``.
        // False significa que el hilo dedicado no arranco (o termino).
        const alive = computed(() => {
            const tc = store.tiaConnection;
            return Boolean(tc && tc.worker_alive);
        });

        // Verde si vivo, gris si muerto. Sin animacion: este
        // indicador refleja un estado discreto (vivo/muerto), no
        // un estado transitorio como el ``TiaConnectionIndicator``
        // (que usa ``animate-pulse`` en "connecting").
        const colorClass = computed(() => {
            return alive.value ? "bg-green-500" : "bg-gray-400";
        });

        const tooltip = computed(() => {
            return alive.value
                ? "Worker OT: activo"
                : "Worker OT: inactivo";
        });

        return { alive, colorClass, tooltip };
    },
    template: /* html */ `
        <span
            :title="tooltip"
            :class="['w-3 h-3 rounded-full inline-block', colorClass, 'transition-colors']"
            :aria-label="alive ? 'Worker OT activo' : 'Worker OT inactivo'"
            data-testid="worker-status-indicator">
        </span>
    `,
};
