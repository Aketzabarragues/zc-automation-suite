// ============================================================================
// ConsolaLogs.js — Footer de trazabilidad (HMI pasivo).
//
//  Clonado del legacy y adaptado:
//    - `store.logs` → `plc.logs` (computed).
//    - `apiClearLogs()` → endpoint directo via fetch (el legacy lo
//      tenia; aqui lo conservamos para que el operario pueda
//      vaciar la consola. El backend NO expone el endpoint de
//      "clear" en Fase 1, asi que la accion solo limpia la vista).
//
//  Source of truth: el buffer reactivo `plc.logs` que el composable
//  `usePlc` rellena con cada evento `type: log` del SSE. Sin
//  polling: el backend envia los mensajes y el composable los
//  acumula (cap 500, FIFO en almacenamiento).
//
//  LIFO en presentacion: `plc.logs` se rellena con `unshift` (el
//  mas reciente primero), asi que pintamos el array directamente
//  sin invertir (ya esta en orden LIFO).
//
//  Tema: capa "Industrial Claro". Solo tokens semanticos.
// ============================================================================

import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { usePlc } from "/js/composables/usePlc.js";

export default {
    name: "ConsolaLogs",
    setup() {
        const plc = usePlc();

        /**
         * Logs ordenados LIFO (mas reciente arriba). Como el
         * composable usa `unshift` al insertar, el array ya esta
         * en orden LIFO. Devolvemos una copia para que el template
         * no mute el array del composable.
         */
        const logs = computed(() => Array.from(plc.logs));

        /**
         * Accion "Limpiar": vacia la vista. En Fase 1 el backend
         * no expone el endpoint de clear; si en el futuro se
         * monta, esta funcion debera hacer un POST a
         * `/api/v1/logs/clear` antes de vaciar el cliente.
         */
        function clearLogs() {
            plc.logs.splice(0, plc.logs.length);
        }

        return { logs, clearLogs };
    },
    template: /* html */ `
        <footer
            class="h-36 bg-surface-raised border-t border-line flex flex-col"
            data-testid="consola-logs">
            <header class="flex justify-between items-center px-4 py-1 bg-surface-sunken border-b border-line">
                <h3 class="text-xs font-bold text-accent uppercase tracking-wider">
                    Consola de Trazabilidad
                </h3>
                <div class="flex gap-2 items-center">
                    <span class="text-xs text-ink-muted">({{ logs.length }} msgs)</span>
                    <button
                        @click="clearLogs"
                        data-testid="consola-limpiar"
                        class="px-3 py-1.5 text-ink-muted font-semibold text-xs bg-surface-sunken hover:bg-surface rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                        🧹 Limpiar
                    </button>
                </div>
            </header>
            <div class="flex-1 overflow-y-auto px-4 py-2 text-xs font-mono leading-snug">
                <div
                    v-if="logs.length === 0"
                    class="text-ink-muted italic">
                    Esperando eventos...
                </div>
                <div
                    v-for="msg in logs"
                    :key="msg.timestamp + ':' + msg.message"
                    :class="{
                        'text-ink': msg.level === 'info' || !msg.level,
                        'text-green-600 font-bold': msg.level === 'success',
                        'text-amber-600 font-bold': msg.level === 'warning',
                        'text-red-600 font-bold': msg.level === 'error',
                    }"
                    class="py-0.5">
                    <span class="text-ink-muted">[{{ msg.timestamp }}]</span>
                    <span class="ml-2">{{ msg.message }}</span>
                </div>
            </div>
        </footer>
    `,
};
