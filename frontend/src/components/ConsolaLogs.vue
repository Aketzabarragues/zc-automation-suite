<script setup>
/**
 * Consola de trazabilidad.
 *
 * Pie de pagina con scroll vertical sobre las lineas de log. Las mas
 * recientes van arriba. Cuando la linea trae traceback, se despliega bajo el
 * mensaje con un boton.
 */
import { ref } from "vue";
import { useLogsStore } from "../stores/logs.js";

const logs = useLogsStore();

/** Ids de las lineas con el traceback desplegado. */
const desplegados = ref(new Set());

/** Abre o cierra el traceback de una linea. */
function alternar(id) {
  const nuevo = new Set(desplegados.value);
  if (nuevo.has(id)) {
    nuevo.delete(id);
  } else {
    nuevo.add(id);
  }
  desplegados.value = nuevo;
}

/** `true` si el traceback de esa linea esta abierto. */
function estaDesplegado(id) {
  return desplegados.value.has(id);
}

/** Vacia la consola. */
function limpiar() {
  logs.limpiar();
  desplegados.value = new Set();
}
</script>

<template>
  <footer class="h-36 bg-surface-raised border-t border-line flex flex-col shrink-0">
    <header
      class="flex justify-between items-center px-4 py-1 bg-surface-sunken border-b border-line"
    >
      <h3 class="text-xs font-bold text-accent uppercase tracking-wider">
        Consola de Trazabilidad
      </h3>
      <div class="flex gap-2 items-center">
        <span class="text-xs text-ink-muted">({{ logs.mensajes.length }} msgs)</span>
        <button
          class="px-3 py-1.5 text-ink-muted font-semibold text-xs bg-surface-sunken hover:bg-surface rounded-md transition-colors duration-200 border border-line flex items-center gap-1.5 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface"
          data-testid="consola-limpiar"
          @click="limpiar"
        >
          🧹 Limpiar
        </button>
      </div>
    </header>

    <div class="flex-1 overflow-y-auto px-4 py-2 text-xs font-mono leading-snug">
      <p v-if="logs.mensajes.length === 0" class="text-ink-muted italic">Esperando eventos...</p>

      <div
        v-for="mensaje in logs.invertidos"
        :key="mensaje.id"
        :class="{
          'text-ink': mensaje.nivel === 'info' || !mensaje.nivel,
          'text-green-600 font-bold': mensaje.nivel === 'success',
          'text-amber-600 font-bold': mensaje.nivel === 'warning',
          'text-red-600 font-bold': mensaje.nivel === 'error',
        }"
        class="py-0.5"
      >
        <span class="text-ink-muted">[{{ mensaje.hora }}]</span>
        <span class="ml-2">{{ mensaje.mensaje }}</span>
        <button
          v-if="mensaje.detalle"
          class="ml-2 text-[10px] underline decoration-dotted hover:no-underline"
          data-testid="consola-detalle"
          @click="alternar(mensaje.id)"
        >
          {{ estaDesplegado(mensaje.id) ? "ocultar traceback" : "ver traceback" }}
        </button>
        <pre
          v-if="mensaje.detalle && estaDesplegado(mensaje.id)"
          class="mt-1 ml-4 p-2 rounded bg-surface-sunken text-ink text-[10px] whitespace-pre-wrap break-words"
          data-testid="consola-traceback"
        >{{ mensaje.detalle }}</pre>
      </div>
    </div>
  </footer>
</template>
