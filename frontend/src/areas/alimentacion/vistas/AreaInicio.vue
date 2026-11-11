<script setup>
/**
 * Inicio del area: que quiere hacer el operario.
 *
 * Las tarjetas abren las vistas del area. Las que aun no estan
 * implementadas avisan en la propia vista, con su aviso en rojo.
 */
import { computed } from "vue";
import { useAreasStore } from "../../../stores/areas.js";

const areas = useAreasStore();

/** Las tarjetas de accion del area. */
const ACCIONES = [
  {
    clave: "def",
    icono: "📊",
    titulo: "Definición programación",
    descripcion: "Carga el maestro Excel y consulta el estado del PLC.",
  },
  {
    clave: "disp",
    icono: "⚡",
    titulo: "Dispositivos",
    descripcion: "Previsualiza y aplica cambios en TIA Portal.",
  },
  {
    clave: "proc",
    icono: "⚙️",
    titulo: "Procesos",
    descripcion: "Genera procesos en TIA Portal (crear / actualizar comentarios).",
  },
];

/** El area activa, con su nombre y su icono. */
const area = computed(() => areas.area);
</script>

<template>
  <section class="flex-1 flex flex-col items-center justify-center p-8" data-testid="area-inicio">
    <div
      v-if="area"
      class="w-10 h-10 rounded-xl bg-shell flex items-center justify-center text-2xl mb-4"
      aria-hidden="true"
    >
      {{ area.icono }}
    </div>

    <h2 class="text-2xl font-bold text-ink">{{ area ? area.nombre : "Área" }}</h2>
    <p class="text-ink-muted mt-1 mb-8">¿Qué quieres hacer?</p>

    <div class="w-full max-w-2xl space-y-3">
      <div
        v-for="accion in ACCIONES"
        :key="accion.clave"
        class="flex items-center gap-4 bg-surface-raised border border-line rounded-lg p-4 shadow-sm"
      >
        <div
          class="w-10 h-10 rounded-lg bg-surface-sunken flex items-center justify-center text-xl shrink-0"
          aria-hidden="true"
        >
          {{ accion.icono }}
        </div>
        <div class="min-w-0 flex-1">
          <h3 class="text-sm font-bold text-ink">{{ accion.titulo }}</h3>
          <p class="text-xs text-ink-muted">{{ accion.descripcion }}</p>
        </div>
        <button
          class="px-3 py-1.5 text-xs font-semibold text-accent bg-surface-sunken border border-line rounded-md hover:bg-accent-subtle transition-colors duration-200 shrink-0"
          :data-testid="'area-accion-' + accion.clave"
          @click="areas.irA(accion.clave)"
        >
          Abrir →
        </button>
      </div>
    </div>
  </section>
</template>
