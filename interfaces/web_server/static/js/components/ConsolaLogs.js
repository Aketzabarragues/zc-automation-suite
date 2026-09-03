/**
 * Componente ConsolaLogs.
 *
 * Footer persistente con scroll vertical e iteración reactiva
 * sobre ``store.logs``. Se mantiene FUERA del bloque ``v-if`` de
 * la vista principal para que los logs sigan visibles al cambiar
 * entre Memory / Sync.
 *
 * Tema: Industrial Claro. Sustituye las clases absolutas oscuras
 * por tokens semánticos (`bg-surface-raised`, `bg-surface-sunken`,
 * `border-line`, `text-ink`, `text-ink-muted`) y eleva los tonos
 * de los niveles de log para garantizar contraste sobre fondo
 * claro:
 *
 *     info     → text-ink
 *     success  → text-green-600 font-bold
 *     warning  → text-amber-600 font-bold
 *     error    → text-red-600   font-bold
 *
 * LIFO puro en la capa de presentación: ``store.logs`` sigue
 * siendo append-only (FIFO) para conservar el contrato con
 * ``store.js``; aquí lo invertimos con ``[...store.logs].reverse()``
 * para que el mensaje más reciente aparezca ARRIBA sin tocar el
 * almacén original.
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "../store.js";
import { apiClearLogs } from "../api.js";

export default {
    name: "ConsolaLogs",
    setup() {
        async function clearLogs() {
            await apiClearLogs();
            store.logs = [];
        }

        /**
         * Vista invertida (LIFO) sin mutar ``store.logs``. Cada
         * dep reactiva (cambio de ``store.logs``) recomputa
         * automáticamente el array.
         */
        const reversedLogs = computed(() => [...store.logs].reverse());

        return { store, clearLogs, reversedLogs };
    },
    template: /* html */ `
        <footer class="h-36 bg-surface-raised border-t border-line flex flex-col">
            <header class="flex justify-between items-center px-4 py-1 bg-surface-sunken border-b border-line">
                <h3 class="text-xs font-bold text-accent uppercase tracking-wider">Consola de Trazabilidad</h3>
                <div class="flex gap-2 items-center">
                    <span class="text-xs text-ink-muted">({{ store.logs.length }} msgs)</span>
                    <button @click="clearLogs"
                        data-testid="consola-limpiar"
                        class="px-3 py-1.5 text-ink-muted font-semibold text-xs bg-surface-sunken hover:bg-surface rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface">
                        🧹 Limpiar
                    </button>
                </div>
            </header>
            <div class="flex-1 overflow-y-auto px-4 py-2 text-xs font-mono leading-snug">
                <div v-if="reversedLogs.length === 0" class="text-ink-muted italic">
                    Esperando eventos...
                </div>
                <div v-for="msg in reversedLogs" :key="msg.timestamp"
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
