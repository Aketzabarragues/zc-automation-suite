/**
 * Componente MainTabs.
 *
 * Strip horizontal con los 2 tabs principales de la vista
 * "Definición programación":
 *   - ``dispositivos`` → sub-tabs ED|EA|SA|V|M|MVF + tabla
 *     (renderizadas por ``DispositivosPanel``).
 *   - ``software``     → sub-tabs Procesos|PInt|PReal|Alarmas +
 *     4 tablas (renderizadas por ``SoftwarePanel``).
 *
 * La selección activa se guarda en ``store.activeMainTab`` (campo
 * global, mutable desde aquí). El componente raíz ``DefinicionProgramacion``
 * decide qué panel pintar en función de ese mismo flag.
 *
 * Diferencia respecto a las sub-pestañas de los paneles
 * (mismo patrón CSS, otra jerarquía): estas son los "tabs
 * principales" que dan entrada a los dos dominios del
 * "Definición programación". El operario los usa para alternar
 * entre el dump de dispositivos y el dump de software sin
 * perder contexto de la cabecera (N_MAX cards siempre visibles).
 *
 * Props:
 *   - ``tabs``: ``Array<{ key, label, icon, badge }>``.
 *     ``key``   → valor que se guarda en ``store.activeMainTab``.
 *     ``label`` → texto visible (p. ej. "Dispositivos").
 *     ``icon``  → emoji opcional (p. ej. "📟").
 *     ``badge`` → número que se muestra entre paréntesis (p. ej.
 *                 suma de dispositivos o suma de filas de software).
 *
 * Tema: Industrial Claro. Solo tokens semánticos
 * (``bg-surface*``, ``border-line*``, ``text-ink*``, ``text-accent``).
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * `vue.esm-browser.prod.js` NO acepta string literals multi-línea
 * dentro de arrays de `:class`. Cada literal va en una sola línea.
 */
import { computed } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { store, goToMainTab } from "/js/store.js";

export default {
    name: "MainTabs",
    props: {
        tabs: { type: Array, required: true },
    },
    setup(props) {
        /**
         * Tab principal actualmente seleccionado. Fallback al
         * primero del prop si el store está vacío (modo degradado
         * o primer render antes de que ``DefinicionProgramacion``
         * haya fijado el default).
         */
        const activeTab = computed(
            () => store.activeMainTab || (props.tabs[0] && props.tabs[0].key) || ""
        );

        /**
         * Cambia el tab principal vía ``goToMainTab`` (mismo
         * patrón que ``goToSubview`` para ``store.currentView``):
         * helper centraliza la mutación y valida que la key sea
         * ``'dispositivos'`` o ``'software'``. No hay @emit porque
         * ``DefinicionProgramacion`` lee ``store.activeMainTab``
         * reactivamente.
         */
        function setActive(key) {
            goToMainTab(key);
        }

        return { activeTab, setActive };
    },
    template: /* html */ `
        <div class="flex border-b-2 border-line bg-surface-sunken overflow-x-auto">
            <button v-for="t in tabs" :key="t.key"
                @click="setActive(t.key)"
                :class="['main-tab-btn px-6 py-3 text-sm font-semibold border-r border-line whitespace-nowrap',
                         activeTab === t.key ? 'active' : 'bg-surface-raised text-ink-muted hover:bg-surface-sunken']">
                <span class="mr-1">{{ t.icon }}</span>
                {{ t.label }}
                <span class="ml-2 text-[11px] opacity-70">({{ t.badge }})</span>
            </button>
        </div>
    `,
};
