/**
 * Componente WorkerStatusIndicator.
 *
 * Circulo pequeño (verde/gris) en el ``ShellTopbar`` que indica si
 * el subproceso del worker OT persistente esta vivo o no. Es
 * ORTOGONAL al ``TiaConnectionIndicator`` (que muestra el estado
 * de attach a TIA Portal: connected/connecting/disconnected/error).
 *
 * Por que son distintos:
 *   - ``TiaConnectionIndicator`` refleja el attach a TIA: el
 *     subproceso puede estar vivo y tener un attach fallido (3
 *     pings sin respuesta). Eso es "desconectado" para la
 *     conexion, pero el subproceso SIGUE vivo.
 *   - ``WorkerStatusIndicator`` refleja solo el subproceso:
 *     "vivo" = ``_worker_proc is not None and returncode is None``.
 *     "muerto" = el subproceso termino (o nunca se lanzo, en modo
 *     1-shot del MCP).
 *
 * Esto permite al operario ver de un vistazo dos cosas distintas:
 *   - Circulo grande (TiaConnectionIndicator): "estoy conectado a TIA?"
 *   - Circulo pequeño (WorkerStatusIndicator): "el subproceso del
 *     worker esta en marcha?"
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
        // En modo 1-shot (MCP), el gateway expone siempre ``False`` y
        // este indicador se queda gris ("sin worker persistente").
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
            // Textos armonizados sept-2026: tono serio y
            // consistente en castellano. Antes: "en marcha" /
            // "detenido" (coloquial). Ahora: "activo" /
            // "inactivo" (formal, neutro).
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
