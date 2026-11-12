<script setup>
/**
 * Shell de la SPA.
 *
 * Dos niveles: la pantalla de inicio (selector de area) y el interior del
 * area (barra lateral, barra superior, contenido y consola).
 */
import { computed } from "vue";
import BannerConfig from "./nucleo/componentes/BannerConfig.vue";
import Bienvenida from "./nucleo/componentes/Bienvenida.vue";
import ConsolaLogs from "./nucleo/componentes/ConsolaLogs.vue";
import ShellSidebar from "./nucleo/componentes/ShellSidebar.vue";
import ShellTopbar from "./nucleo/componentes/ShellTopbar.vue";
import EditorBloques from "./nucleo/vistas/EditorBloques.vue";
import VistaPlc from "./nucleo/vistas/Plc.vue";
import { useAreasStore } from "./nucleo/stores/areas.js";

const areas = useAreasStore();

/** El item de menu de la vista activa, para el aviso de vista pendiente. */
const itemActivo = computed(() =>
  areas.menu.find((item) => item.clave === areas.vista),
);
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-surface text-ink">
    <BannerConfig />

    <div class="flex flex-1 min-h-0 overflow-hidden">
      <template v-if="!areas.area">
        <Bienvenida />
      </template>

      <template v-else>
        <ShellSidebar />

        <div class="flex flex-1 flex-col min-w-0">
          <ShellTopbar />

          <main class="flex-1 min-h-0 overflow-y-auto p-5 flex flex-col">
            <VistaPlc v-if="areas.vista === 'plc'" />
            <EditorBloques v-else-if="areas.vista === 'block-editor'" />
            <component :is="areas.componenteVista" v-else-if="areas.componenteVista" />

            <div
              v-else
              class="flex-1 flex items-center justify-center bg-surface-raised border border-dashed border-line rounded p-10 text-center text-ink-muted"
              data-testid="vista-pendiente"
            >
              <div>
                <div class="text-5xl mb-3 opacity-40">{{ itemActivo ? itemActivo.icono : "📄" }}</div>
                <p class="mb-2 font-semibold text-ink">
                  {{ itemActivo ? itemActivo.etiqueta : "Vista" }}
                </p>
                <p class="text-xs">Esta vista todavía no está implementada.</p>
              </div>
            </div>
          </main>

          <ConsolaLogs />
        </div>
      </template>
    </div>
  </div>
</template>
