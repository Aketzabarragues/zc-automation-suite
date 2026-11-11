<script setup>
/**
 * Barra lateral del shell.
 *
 * Navy, con la cabecera del area, las vistas del shell (PLC y editor de
 * bloques), el menu del area, el faceplate de progreso al pie y el boton
 * de volver al inicio.
 */
import { computed } from "vue";
import { useAreasStore, VISTAS_SHELL } from "../stores/areas.js";
import FaceplateProgreso from "./FaceplateProgreso.vue";

const areas = useAreasStore();

/** El nombre del area, como en la cabecera. */
const nombreArea = computed(() => (areas.area ? areas.area.nombre : "—"));

/** El estilo de un item: el activo se marca con fondo y borde izquierdo. */
function claseItem(activo) {
  return activo
    ? "bg-shell-active border-accent-bright text-on-shell font-semibold"
    : "border-transparent text-on-shell-muted hover:bg-shell-hover hover:text-on-shell";
}
</script>

<template>
  <aside
    class="w-72 flex-shrink-0 bg-shell text-on-shell flex flex-col overflow-hidden"
    data-testid="sidebar"
  >
    <header class="px-5 py-4 border-b border-shell-border shrink-0">
      <p class="text-[10px] uppercase tracking-widest text-on-shell-faint font-bold mb-2">Área</p>
      <p class="text-xl font-extrabold text-on-shell tracking-tight truncate">{{ nombreArea }}</p>
    </header>

    <div class="flex-1 min-h-0 flex flex-col">
      <div class="px-3 pt-8 mb-2 shrink-0" data-testid="sidebar-plc">
        <p class="px-3 text-[10px] uppercase tracking-widest text-on-shell-faint font-bold mb-2">
          PLC
        </p>
        <button
          v-for="vista in VISTAS_SHELL"
          :key="vista.clave"
          type="button"
          :data-testid="'sidebar-' + vista.clave"
          :data-active="areas.vista === vista.clave"
          :class="[
            'w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors duration-150 border-l-2',
            vista.clave === 'block-editor' ? 'mt-1' : '',
            claseItem(areas.vista === vista.clave),
          ]"
          @click="areas.irA(vista.clave)"
        >
          <span class="text-base opacity-90" aria-hidden="true">{{ vista.icono }}</span>
          <span class="truncate">{{ vista.etiqueta }}</span>
        </button>
      </div>

      <nav
        class="flex-1 px-3 py-4 overflow-y-auto"
        aria-label="Navegación"
        data-testid="sidebar-menu"
      >
        <p class="px-3 text-[10px] uppercase tracking-widest text-on-shell-faint font-bold mb-2">
          Navegación
        </p>
        <div class="flex flex-col gap-1">
          <button
            v-for="item in areas.menu"
            :key="item.clave"
            type="button"
            :data-area-key="item.clave"
            :data-active="areas.vista === item.clave"
            :class="[
              'w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors duration-150 border-l-2',
              claseItem(areas.vista === item.clave),
            ]"
            @click="areas.irA(item.clave)"
          >
            <span class="text-base opacity-90" aria-hidden="true">{{ item.icono }}</span>
            <span class="truncate">{{ item.etiqueta }}</span>
          </button>
        </div>
      </nav>

      <FaceplateProgreso />
    </div>

    <footer class="p-4 border-t border-shell-border shrink-0">
      <button
        type="button"
        data-testid="sidebar-volver"
        class="w-full flex items-center justify-center gap-2 px-4 py-3 text-sm font-bold text-on-shell-muted bg-shell-deep hover:text-on-shell rounded-xl transition-colors duration-150"
        @click="areas.volver()"
      >
        <span aria-hidden="true">←</span>
        <span>Volver al inicio</span>
      </button>
    </footer>
  </aside>
</template>
