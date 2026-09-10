// ============================================================================
// ShellSidebar.js — Sidebar cross-cutting del shell (HMI pasivo).
//
//  Clonado del legacy y adaptado:
//    - `import { store } from "/js/store.js"` → `usePlc()`
//    - `store.currentView`                   → `plc.currentView`
//    - ProgressIndicator (dark): ya no se le pasa el store, ahora
//      lee del FB activo via el composable.
//
//  Estructura (de arriba a abajo):
//    1. Cabecera: bloque navy con caption "Modulo" + label del area.
//    2. Zona media: nav (flex-1, scrolls) + ProgressIndicator dark.
//    3. Footer: boton "← Volver al inicio" PINADO al fondo.
//
//  Tema: capa "Industrial Claro" con tokens `bg-shell*` para la
//  cabecera del sidebar. Solo tokens semanticos.
//
//  IMPORTANTE Vue 3 sin build step: el template solo lee variables
//  planas del `setup()`. Acceso a `plc.*` se hace via `computed`.
// ============================================================================

import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { usePlc } from "/js/composables/usePlc.js";
import ProgressIndicator from "/js/components/ProgressIndicator.js";

export default {
    name: "ShellSidebar",
    components: { ProgressIndicator },
    props: {
        /** `{ key, label, icon }` del area activa. */
        area: { type: Object, required: true },
        /**
         * `Array<{ key, icon, label }>` entradas de navegacion del area.
         * Tipicamente derivado del manifest.
         */
        navItems: { type: Array, required: true },
    },
    emits: ["navigate", "back"],
    setup(props, { emit }) {
        const plc = usePlc();

        /**
         * Etiqueta del area activa, derivada del prop `area`.
         * Fallback neutro si el area no trae label.
         */
        const areaLabel = computed(() => {
            if (!props.area) return "—";
            if (props.area.subtitle) return props.area.subtitle;
            return props.area.label || props.area.key || "—";
        });

        function navigate(key) {
            if (!key) return;
            emit("navigate", key);
        }

        function back() {
            emit("back");
        }

        return {
            areaLabel,
            navigate,
            back,
        };
    },
    template: /* html */ `
        <aside
            class="fixed left-0 top-0 h-screen w-72 flex-shrink-0 bg-shell text-on-shell flex flex-col overflow-hidden z-30"
            data-testid="shell-sidebar">

            <!-- 1. Cabecera -->
            <header class="px-5 py-5 border-b border-shell-border shrink-0">
                <p class="text-[10px] uppercase tracking-widest text-on-shell-faint font-bold mb-1">
                    Modulo
                </p>
                <p class="text-2xl font-extrabold text-on-shell tracking-tight truncate">
                    {{ areaLabel }}
                </p>
            </header>

            <!-- 2. Zona media: nav (flex-1) + ProgressIndicator -->
            <div class="flex-1 min-h-0 flex flex-col">
                <!-- 2a. Navegacion entre vistas del area -->
                <nav class="flex-1 px-3 py-3 overflow-y-auto" aria-label="Navegacion del area">
                    <p class="px-3 text-[10px] uppercase tracking-widest text-on-shell-faint font-bold mb-2">
                        Navegacion
                    </p>
                    <button
                        v-for="item in navItems"
                        :key="item.key"
                        @click="navigate(item.key)"
                        :data-nav-key="item.key"
                        :class="[
                            'w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors duration-150 border-l-2',
                            navItems.length && navItems.find(n => n.key === item.key)
                                ? 'border-transparent text-on-shell-muted hover:bg-shell-hover hover:text-on-shell'
                                : 'border-transparent text-on-shell-muted hover:bg-shell-hover hover:text-on-shell'
                        ]">
                        <span class="text-base opacity-90" aria-hidden="true">{{ item.icon }}</span>
                        <span class="truncate">{{ item.label }}</span>
                    </button>
                </nav>

                <!-- 2b. ProgressIndicator (variant dark) -->
                <ProgressIndicator dark />
            </div>

            <!-- 3. Footer: "← Volver al inicio" PINADO al fondo -->
            <footer class="p-4 border-t border-shell-border shrink-0">
                <button
                    @click="back"
                    data-testid="sidebar-back"
                    class="w-full flex items-center justify-center gap-2 px-4 py-3 text-sm font-bold text-on-shell-muted bg-shell-deep hover:text-on-shell rounded-xl transition-colors duration-150">
                    <span aria-hidden="true">←</span>
                    <span>Volver al inicio</span>
                </button>
            </footer>
        </aside>
    `,
};
