<script setup>
/**
 * Barra superior del shell.
 *
 * Migas del area y de la vista, y la pastilla del PLC seleccionado. No hay
 * boton de conectar aqui: la conexion se hace en la vista PLC.
 */
import { computed } from "vue";
import { useAreasStore } from "../stores/areas.js";
import { usePlcStore } from "../stores/plc.js";
import { useTiaStore } from "../stores/tia.js";

const areas = useAreasStore();
const plc = usePlcStore();
const tia = useTiaStore();

/** El area activa, en mayusculas, para las migas. */
const areaMigas = computed(() => (areas.area ? areas.area.nombre.toUpperCase() : "—"));

/** La vista activa, en mayusculas, para las migas. */
const vistaMigas = computed(() => areas.etiquetaVista.toUpperCase());
</script>

<template>
  <header
    class="min-h-14 bg-white border-b border-line flex flex-wrap items-center justify-between gap-3 px-6 py-2 shrink-0 shadow-sm"
  >
    <nav class="flex items-center gap-2 text-xs font-medium shrink-0" aria-label="Ruta">
      <span class="text-ink-muted uppercase tracking-widest">{{ areaMigas }}</span>
      <span class="text-line-strong" aria-hidden="true">•</span>
      <span class="text-accent font-bold uppercase tracking-widest">{{ vistaMigas }}</span>
    </nav>

    <div class="inline-flex items-center justify-end gap-3 text-xs flex-wrap min-w-0">
      <span
        v-if="tia.demo"
        class="px-2 py-1 rounded bg-amber-100 text-amber-800 font-bold uppercase tracking-wider"
        data-testid="topbar-demo"
      >
        Demo
      </span>

      <span
        class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-line bg-surface-sunken"
        data-testid="topbar-plc"
      >
        <span class="text-ink-muted">PLC:</span>
        <span class="font-mono font-semibold text-accent">{{ plc.seleccionado || "—" }}</span>
      </span>
    </div>
  </header>
</template>
