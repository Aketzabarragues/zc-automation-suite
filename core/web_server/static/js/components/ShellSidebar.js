/**
 * Componente ShellSidebar — chrome corporativo reusable (v3.0).
 *
 * Sidebar genérico cross-cutting sobre fondo navy. Tras el refactor
 * de areas (sept-2026), este componente ya no recibe ``navItems``
 * por prop ni depende de un wrapper por area. Lee directamente
 * del ``store``:
 *   * Cabecera: ``store.availableAreas`` para el label del area.
 *   * Sub-vistas: ``store.areaManifest.components.views`` +
 *     ``viewLabels`` (opcional, fallback a la key capitalizada).
 *   * Boton PLC: siempre visible en la zona media, encima de la
 *     nav del area. Común a TODAS las areas (todas tienen PLCs).
 *
 * Estructura (de arriba a abajo):
 *   1. Cabecera (shrink-0): bloque navy con "Módulo" + label del
 *      area activa.
 *   2. Zona media (flex-1 min-h-0):
 *        a. Boton "PLC" (comun, navega a currentView="plc").
 *        b. Navegacion del area (especifica, viene del manifest).
 *        c. ProgressIndicator (variant dark).
 *   3. Footer (shrink-0): boton "← Volver al inicio".
 *
 * Emits:
 *   * ``navigate(key: string)`` — el operario pulso un item de la
 *     nav (incluido el boton PLC). El padre resuelve la key (si
 *     es "plc" renderiza el PlcPanelView comun; si es otra key,
 *     renderiza la vista del manifest del area).
 *   * ``back()`` — volver al Welcome.
 *
 * Tema: capa "shell" corporativa. Sin hex hardcoded.
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";
import ProgressIndicator from "/js/components/ProgressIndicator.js";

/**
 * Icono por defecto de cada sub-vista canonica del shell.
 * El area puede sobrescribir via ``manifest.components.navIcons``
 * (opcional, no se usa en areas actuales).
 */
const DEFAULT_ICONS = {
    landing: "🏠",
    plc: "🔌",
    def: "📊",
    disp: "⚡",
    proc: "⚙️",
    cache: "🗃️",
};

/** Capitaliza la primera letra (fallback de label cuando no hay
 *  ``viewLabels`` en el manifest). */
function capitalize(s) {
    if (!s) return "";
    return String(s).charAt(0).toUpperCase() + String(s).slice(1);
}

export default {
    name: "ShellSidebar",
    components: { ProgressIndicator },
    emits: ["navigate", "back"],
    setup(_, { emit }) {
        /**
         * Label del area activa para la cabecera. Resuelve primero
         * contra ``store.availableAreas`` (cargado por Welcome);
         * si no encuentra coincidencia, cae al store.selectedArea
         * crudo. Sin prop.
         */
        const areaLabel = computed(() => {
            const sel = store.selectedArea;
            if (!sel) return "—";
            const a = (store.availableAreas || []).find((x) => x.key === sel);
            if (a) return a.subtitle || a.label || a.key;
            return sel;
        });

        /**
         * Sub-vistas del area activa derivadas del manifest.
         * Cada item es ``{ key, label, icon }``. Si el manifest
         * no tiene ``viewLabels``, el label es la key capitalizada.
         * ``navIcons`` del manifest (si existe) sobrescribe el
         * default por key.
         */
        const navItems = computed(() => {
            const m = store.areaManifest;
            if (!m || !m.components || !m.components.views) return [];
            const labels = m.components.viewLabels || {};
            const icons = m.components.navIcons || {};
            // "plc" es del shell, no del area: se filtra para no
            // duplicar el boton comun.
            return Object.entries(m.components.views)
                .filter(([key]) => key !== "plc")
                .map(([key, _compName]) => ({
                    key,
                    label: labels[key] || capitalize(key),
                    icon: icons[key] || DEFAULT_ICONS[key] || "📄",
                }));
        });

        /** Emite ``navigate`` con la key del item (incluido "plc"). */
        function navigate(key) {
            if (!key) return;
            emit("navigate", key);
        }

        /** Emite ``back`` para volver al Welcome. */
        function back() {
            emit("back");
        }

        /**
         * Helper de class para los items de la nav + el boton PLC.
         * Item activo = currentView === key.
         */
        function itemClass(active) {
            return active
                ? "bg-shell-active border-accent-bright text-on-shell font-semibold"
                : "border-transparent text-on-shell-muted hover:bg-shell-hover hover:text-on-shell";
        }

        return {
            store,
            areaLabel,
            navItems,
            navigate,
            back,
            itemClass,
        };
    },
    template: /* html */ `
        <aside class="fixed left-0 top-0 h-screen w-72 flex-shrink-0 bg-shell text-on-shell flex flex-col overflow-hidden z-30">

            <header class="px-5 py-5 border-b border-shell-border shrink-0">
                <p class="text-[10px] uppercase tracking-widest text-on-shell-faint font-bold mb-1">Módulo</p>
                <p class="text-2xl font-extrabold text-on-shell tracking-tight truncate">{{ areaLabel }}</p>
            </header>

            <div class="flex-1 min-h-0 flex flex-col">
                <!-- Boton PLC (comun): siempre visible cuando hay area
                     activa. Resalta si store.currentView === "plc".
                     El padre enruta "plc" al PlcPanelView del shell. -->
                <div class="px-3 pt-3 shrink-0" data-testid="sidebar-plc-button-wrapper">
                    <p class="px-3 text-[10px] uppercase tracking-widest text-on-shell-faint font-bold mb-2">PLC</p>
                    <button @click="navigate('plc')"
                            data-testid="sidebar-plc-button"
                            :data-active="store.currentView === 'plc'"
                            :class="[
                                'w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors duration-150 border-l-2',
                                itemClass(store.currentView === 'plc')
                            ]">
                        <span class="text-base opacity-90" aria-hidden="true">🔌</span>
                        <span class="truncate">PLC</span>
                    </button>
                </div>

                <!-- Navegacion del area (sub-vistas, viene del manifest). -->
                <nav class="flex-1 px-3 py-3 overflow-y-auto">
                    <p class="px-3 text-[10px] uppercase tracking-widest text-on-shell-faint font-bold mb-2">Navegación</p>
                    <button v-for="item in navItems" :key="item.key"
                            @click="navigate(item.key)"
                            :data-area-key="item.key"
                            :data-active="store.currentView === item.key"
                            :class="[
                                'w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors duration-150 border-l-2',
                                itemClass(store.currentView === item.key)
                            ]">
                        <span class="text-base opacity-90" aria-hidden="true">{{ item.icon }}</span>
                        <span class="truncate">{{ item.label }}</span>
                    </button>
                </nav>

                <!-- ProgressIndicator (variant dark automatico). -->
                <ProgressIndicator dark />
            </div>

            <footer class="p-4 border-t border-shell-border shrink-0">
                <button @click="back"
                        data-testid="sidebar-back"
                        class="w-full flex items-center justify-center gap-2 px-4 py-3 text-sm font-bold text-on-shell-muted bg-shell-deep hover:text-on-shell rounded-xl transition-colors duration-150">
                    <span aria-hidden="true">←</span>
                    <span>Volver al inicio</span>
                </button>
            </footer>
        </aside>
    `,
};
