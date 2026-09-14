/**
 * Componente ShellSidebar — chrome corporativo reusable (v2.1).
 *
 * Sidebar genérico cross-cutting sobre fondo navy con cabecera
 * "Módulo · <Área>", navegación entre sub-vistas del área,
 * ProgressIndicator dark y botón "← Volver al inicio" PINADO
 * al fondo. En la v2 se le retiró la selección PLC (que migró
 * al ``ShellTopbar``) y el ``plcSelector`` prop. En la v2.1 se
 * ha garantizado que el aside ocupa SIEMPRE el alto del
 * viewport (``h-full``) y que el botón Volver está siempre
 * visible al fondo (patrón bulletproof: nav + ProgressIndicator
 * envueltos en contenedor ``flex-1 min-h-0``; el footer vive
 * como hijo directo del aside, con ``shrink-0`` para no
 * comprimirse).
 *
 * Estructura (de arriba a abajo):
 *   1. Cabecera (shrink-0): bloque navy con caption "Módulo" +
 *      label del área activa, tipografía ``text-2xl
 *      font-extrabold tracking-tight`` para dialogar con la
 *      topbar clara que tiene justo al lado.
 *   2. Zona media (flex-1 min-h-0): contenedor que agrupa la
 *      nav (flex-1, scrolls si hay muchos items) y el
 *      ProgressIndicator (v-if, ocupa su tamaño natural cuando
 *      hay operación en curso). El contenedor absorbe el
 *      espacio sobrante para que el footer quede pegado al
 *      fondo.
 *   3. Footer (shrink-0): caja ``bg-shell-deep rounded-xl`` con
 *      el botón "← Volver al inicio" centrado. Replica el
 *      patrón del ejemplo de referencia
 *      (``_source/Rediseno.html``): caja oscura sobre fondo
 *      navy, padding generoso, texto bold.
 *
 * Props:
 *   * ``area``     : ``{ key, label, icon }`` — área activa. El
 *                    ``label`` se muestra en la cabecera como
 *                    "título" del shell.
 *   * ``navItems`` : ``Array<{ key, icon, label }>`` — entradas
 *                    de la navegación del área.
 *
 * Emits:
 *   * ``navigate(key: string)`` — el operario ha pulsado un
 *     item de la nav. El padre (wrapper del área) decide a qué
 *     sub-vista navegar.
 *   * ``back()`` — el operario ha pulsado "← Volver al
 *     inicio". El padre normalmente llama a ``goToWelcome``.
 *
 * Tema: capa "shell" corporativa (tokens ``bg-shell*``,
 * ``text-on-shell*``, ``border-shell-border``,
 * ``accent-bright``). Cero hex hardcoded.
 *
 * IMPORTANTE sobre templates Vue: el compilador en runtime de
 * ``vue.esm-browser.prod.js`` NO acepta string literals multi-línea
 * dentro de arrays de ``:class``. Cada literal va en una sola
 * línea. Salto de línea entre elementos del array OK.
 */
import { computed } from "/js/vendor/vue.esm-browser.prod.js";
import { store } from "/js/store.js";
import ProgressIndicator from "/js/components/ProgressIndicator.js";

export default {
    name: "ShellSidebar",
    components: { ProgressIndicator },
    props: {
        area: { type: Object, required: true },
        navItems: { type: Array, required: true },
    },
    emits: ["navigate", "back"],
    setup(props, { emit }) {
        /**
         * Etiqueta del área activa, derivada del prop ``area``.
         * Fallback neutro si el área no trae label. Se usa como
         * "título" del shell (cabecera del sidebar).
         *
         * Si el área trae un campo ``subtitle`` (forma corta,
         * p. ej. ``"Alimentación"`` para el área cuyo label
         * completo es ``"Área de alimentación"``), se prefiere
         * ese para evitar redundancia con el caption "Área" que
         * ya muestra la cabecera del sidebar.
         */
        const areaLabel = computed(() => {
            if (!props.area) return "—";
            if (props.area.subtitle) return props.area.subtitle;
            return props.area.label || props.area.key || "—";
        });

        /** Emite ``navigate`` con la key del item. */
        function navigate(key) {
            if (!key) return;
            emit("navigate", key);
        }

        /** Emite ``back`` para volver al Welcome. */
        function back() {
            emit("back");
        }

        return {
            store,
            areaLabel,
            navigate,
            back,
        };
    },
    template: /* html */ `
        <aside class="fixed left-0 top-0 h-screen w-72 flex-shrink-0 bg-shell text-on-shell flex flex-col overflow-hidden z-30">

            <!-- 1. Cabecera: bloque navy con "Módulo" + área.
                 Sin card blanco, sin logo, sin emoji: la unidad
                 navy es la identidad del shell. Cualquier blanco
                 rompería la coherencia con el resto de la SPA.
                 Tipografía grande (text-2xl extrabold tracking
                 -tight) para que dialogue con la topbar clara.
                 shrink-0 garantiza que el header nunca se
                 comprime aunque el espacio sea escaso. -->
            <header class="px-5 py-5 border-b border-shell-border shrink-0">
                <p class="text-[10px] uppercase tracking-widest text-on-shell-faint font-bold mb-1">Área</p>
                <p class="text-2xl font-extrabold text-on-shell tracking-tight truncate">{{ areaLabel }}</p>
            </header>

            <!-- 2. Zona media (nav + ProgressIndicator) en
                 contenedor flex-1: absorbe todo el espacio
                 sobrante para que el footer quede PINADO al
                 fondo del aside aunque la nav tenga poco
                 contenido o el progress esté v-if=false. -->
            <div class="flex-1 min-h-0 flex flex-col">
                <!-- 2a. Navegación entre vistas del área
                     (flex-1 dentro de la zona media, scrolls). -->
                <nav class="flex-1 px-3 py-3 overflow-y-auto">
                    <p class="px-3 text-[10px] uppercase tracking-widest text-on-shell-faint font-bold mb-2">Navegación</p>
                    <button v-for="item in navItems" :key="item.key"
                            @click="navigate(item.key)"
                            :data-area-key="item.key"
                            :class="[
                                'w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors duration-150 border-l-2',
                                store.currentView === item.key
                                    ? 'bg-shell-active border-accent-bright text-on-shell font-semibold'
                                    : 'border-transparent text-on-shell-muted hover:bg-shell-hover hover:text-on-shell'
                            ]">
                        <span class="text-base opacity-90" aria-hidden="true">{{ item.icon }}</span>
                        <span class="truncate">{{ item.label }}</span>
                    </button>
                </nav>

                <!-- 2b. ProgressIndicator (variant dark automático).
                     v-if: si no hay nada que reportar, no se
                     renderiza y el nav absorbe el espacio extra. -->
                <ProgressIndicator dark />
            </div>

            <!-- 3. Footer con "← Volver al inicio". Acción
                 secundaria, PINADA al fondo del aside. Caja
                 oscura (bg-shell-deep) sobre fondo navy, mismo
                 lenguaje visual que el ejemplo de referencia
                 (caja "bg-black/20" sobre navy). shrink-0
                 garantiza que el botón nunca se comprime. -->
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
