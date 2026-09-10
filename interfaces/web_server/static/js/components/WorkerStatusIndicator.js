// ============================================================================
// WorkerStatusIndicator.js — Circulo de estado del subproceso worker OT.
//
//  Clonado del legacy y adaptado:
//    - `store.tiaConnection.worker_alive` → `plc.workerAlive` (computed).
//
//  Source of truth: el `DB_EstadoConexion.worker_alive` que el backend
//  actualiza tras cada ping exitoso. Llega al SPA via SSE.
//
//  Estados:
//    - alive=true   (verde): subproceso vivo.
//    - alive=false  (gris) : subproceso terminado o modo 1-shot.
//
//  Es ORTOGONAL al TiaConnectionIndicator: el worker puede estar
//  vivo y sin portal attached (idle), o vivo y conectado. El
//  operario ve los dos circulos y entiende la diferencia de un vistazo.
// ============================================================================

import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { usePlc } from "/js/composables/usePlc.js";

export default {
    name: "WorkerStatusIndicator",
    setup() {
        const plc = usePlc();

        // `worker_alive` lo escribe el backend tras un ping exitoso.
        // En modo 1-shot (MCP), el gateway expone siempre False y
        // este indicador se queda gris ("sin worker persistente").
        const alive = computed(() => plc.workerAlive);

        // Verde si vivo, gris si muerto. Sin animacion: estado discreto.
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
