<script setup>
/**
 * Vista de inicio.
 *
 * While there are no areas yet, this is what the central column shows: the
 * state of the app and what the operator has to do next.
 */
import { useTiaStore } from "../stores/tia.js";

const tia = useTiaStore();
</script>

<template>
  <div class="flex-1 flex items-center justify-center">
    <div
      class="w-full max-w-xl bg-surface-raised border border-line rounded-lg p-8 shadow-sm"
      data-testid="vista-inicio"
    >
      <h2 class="text-xl font-bold text-ink">ZC Automation Suite</h2>
      <p class="mt-2 text-sm text-ink-muted leading-relaxed">
        Automatización de proyectos de Siemens TIA Portal. Conéctate a TIA Portal para empezar a
        trabajar sobre el proyecto abierto.
      </p>

      <dl class="mt-6 grid grid-cols-2 gap-4 text-sm">
        <div>
          <dt class="text-xs uppercase tracking-wider text-ink-muted">Conexión</dt>
          <dd class="font-semibold text-ink" data-testid="vista-estado">
            {{ tia.etiqueta }}
          </dd>
        </div>
        <div>
          <dt class="text-xs uppercase tracking-wider text-ink-muted">TIA Portal</dt>
          <dd class="font-semibold text-ink">{{ tia.version_tia || "—" }}</dd>
        </div>
      </dl>

      <p
        v-if="tia.demo"
        class="mt-6 p-3 rounded bg-amber-100 text-amber-900 text-xs leading-relaxed"
      >
        Modo demo: no hay backend detrás. Los eventos que ves están simulados.
      </p>
    </div>
  </div>
</template>
