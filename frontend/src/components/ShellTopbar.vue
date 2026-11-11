<script setup>
/**
 * Barra superior del shell.
 *
 * Muestra el estado de la conexion con TIA Portal, la version de TIA, el
 * ultimo error y el boton de conectar o desconectar. El estado llega por el
 * evento `tia` del backend; el boton solo encola el trabajo.
 */
import { computed } from "vue";
import { useTiaStore } from "../stores/tia.js";

const tia = useTiaStore();

/** Texto del boton. */
const textoBoton = computed(() => (tia.conectado ? "Desconectar" : "Conectar"));

/** Estilo del boton segun lo que hace. */
const claseBoton = computed(() =>
  tia.conectado
    ? "bg-surface-sunken text-ink border border-line hover:bg-surface"
    : "bg-accent text-white hover:bg-accent-hover border border-transparent",
);

/** Pulsa el boton que corresponda al estado actual. */
function pulsar() {
  if (tia.conectado) {
    tia.desconectar();
  } else {
    tia.conectar();
  }
}
</script>

<template>
  <header
    class="min-h-14 bg-white border-b border-line flex flex-wrap items-center justify-between gap-3 px-6 py-2 shrink-0 shadow-sm"
  >
    <nav class="flex items-center gap-2 text-xs font-medium shrink-0" aria-label="Ruta">
      <span class="text-ink-muted uppercase tracking-widest">ZC Automation Suite</span>
      <span class="text-line-strong" aria-hidden="true">•</span>
      <span class="text-accent font-bold uppercase tracking-widest">Inicio</span>
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
        class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-line bg-surface-sunken"
        data-testid="topbar-estado"
      >
        <span
          class="w-2 h-2 rounded-full"
          :class="tia.conectado ? 'bg-green-600' : 'bg-red-600'"
          aria-hidden="true"
        ></span>
        <span class="font-semibold text-ink">{{ tia.etiqueta }}</span>
      </span>

      <span
        v-if="tia.version_tia"
        class="font-mono font-semibold text-accent"
        data-testid="topbar-version"
      >
        TIA {{ tia.version_tia }}
      </span>

      <span
        v-if="tia.streamCaido && !tia.demo"
        class="px-2 py-1 rounded bg-amber-100 text-amber-800 font-semibold"
        data-testid="topbar-stream"
      >
        stream caído
      </span>

      <span
        v-if="tia.ultimo_error"
        class="max-w-96 truncate text-red-600 font-semibold"
        :title="tia.ultimo_error"
        data-testid="topbar-error"
      >
        {{ tia.ultimo_error }}
      </span>

      <span
        v-if="tia.aviso"
        class="max-w-96 truncate text-amber-700"
        :title="tia.aviso"
        data-testid="topbar-aviso"
      >
        {{ tia.aviso }}
      </span>

      <button
        :class="['px-3 py-1.5 rounded-md font-semibold transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-white', claseBoton]"
        data-testid="topbar-boton"
        @click="pulsar"
      >
        {{ textoBoton }}
      </button>
    </div>
  </header>
</template>
