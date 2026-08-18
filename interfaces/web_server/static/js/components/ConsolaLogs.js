/**
 * Componente ConsolaLogs.
 *
 * Footer persistente con scroll vertical e iteración reactiva
 * sobre ``store.logs``. Se mantiene FUERA del bloque ``v-if`` de
 * la vista principal para que los logs sigan visibles al cambiar
 * entre Memory / Sync.
 */
import { store } from "../store.js";
import { apiClearLogs } from "../api.js";

export default {
    name: "ConsolaLogs",
    setup() {
        async function clearLogs() {
            await apiClearLogs();
            store.logs = [];
        }
        return { store, clearLogs };
    },
    template: /* html */ `
        <footer class="h-44 bg-black border-t border-slate-700 flex flex-col">
            <header class="flex justify-between items-center px-4 py-1 bg-slate-900 border-b border-slate-700">
                <h3 class="text-xs font-bold text-slate-400 uppercase">Consola de Trazabilidad</h3>
                <div class="flex gap-2 items-center">
                    <span class="text-xs text-slate-500">({{ store.logs.length }} msgs)</span>
                    <button @click="clearLogs"
                        class="text-xs px-2 py-0.5 bg-slate-700 hover:bg-slate-600 rounded">
                        🧹 Limpiar
                    </button>
                </div>
            </header>
            <div class="flex-1 overflow-y-auto px-4 py-2 text-xs font-mono leading-snug">
                <div v-if="store.logs.length === 0" class="text-slate-600 italic">
                    Esperando eventos...
                </div>
                <div v-for="msg in store.logs" :key="msg.timestamp"
                    :class="{
                        'text-slate-200': msg.level === 'info' || !msg.level,
                        'text-green-400 font-medium': msg.level === 'success',
                        'text-yellow-300': msg.level === 'warning',
                        'text-red-400 font-medium': msg.level === 'error',
                    }"
                    class="py-0.5">
                    <span class="text-slate-600">[{{ msg.timestamp }}]</span>
                    <span class="ml-2">{{ msg.message }}</span>
                </div>
            </div>
        </footer>
    `,
};
