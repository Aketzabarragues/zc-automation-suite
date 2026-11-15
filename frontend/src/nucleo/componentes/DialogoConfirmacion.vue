<script setup>
/**
 * Dialogo de confirmacion de una accion que modifica el PLC.
 *
 * Lo comparten las vistas de dispositivos, entidades y procesos: mismo
 * markup, mismo comportamiento. Escape lo cierra solo mientras este
 * abierto; hacer click en el fondo cancela. Emite `confirmar` y
 * `cancelar`; el estado `abierto` lo manda el padre.
 *
 * Los testids llevan el prefijo que pasa cada vista, para que cada spec
 * siga apuntando a su dialogo.
 */
import { onBeforeUnmount, onMounted } from "vue";

const props = defineProps({
  /** `true` mientras el dialogo esta abierto. */
  abierto: Boolean,
  /** El texto de la confirmacion. */
  texto: String,
  /** Prefijo de los testids: `entidades`, `dispositivos`, `procesos`. */
  prefijo: String,
});

const emit = defineEmits(["confirmar", "cancelar"]);

function onTecla(evento) {
  if (!props.abierto) return;
  if (evento.key !== "Escape" && evento.key !== "Esc" && evento.keyCode !== 27) {
    return;
  }
  emit("cancelar");
}

onMounted(() => {
  window.addEventListener("keydown", onTecla);
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onTecla);
});
</script>

<template>
  <div
    v-if="abierto"
    class="fixed inset-0 z-50 flex items-center justify-center bg-shell-deep/50 p-4"
    :data-testid="`${prefijo}-confirmar-fondo`"
    @click.self="emit('cancelar')"
  >
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Confirmar cambios en TIA Portal"
      :data-testid="`${prefijo}-confirmar-dialogo`"
      class="w-full max-w-md bg-surface-raised border border-line rounded-lg shadow-lg p-5"
    >
      <div
        class="font-mono text-xs text-ink bg-surface-sunken border border-line rounded p-3 mb-4 whitespace-pre-wrap"
        :data-testid="`${prefijo}-confirmar-texto`"
      >
        {{ texto }}
      </div>
      <div class="flex justify-end gap-2">
        <button
          type="button"
          :data-testid="`${prefijo}-confirmar-no`"
          class="px-3 py-1.5 text-xs font-semibold text-ink bg-surface-sunken hover:bg-line rounded-md border border-line transition-colors duration-200"
          @click="emit('cancelar')"
        >
          Cancelar
        </button>
        <button
          type="button"
          :data-testid="`${prefijo}-confirmar-si`"
          class="px-3 py-1.5 text-xs font-semibold text-ink-inverse bg-accent hover:bg-accent-hover rounded-md border border-line transition-colors duration-200"
          @click="emit('confirmar')"
        >
          Sí, aplicar
        </button>
      </div>
    </div>
  </div>
</template>
