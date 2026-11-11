<script setup>
/**
 * Faceplate de progreso.
 *
 * Panel fijo de progreso, sin overlay ni autocierre. Se muestra solo cuando
 * hay algo que reportar (pasos declarados o un error) y se queda visible
 * hasta que el operario lo cierra.
 *
 * La fuente de verdad es el store de trabajos, que es el espejo reactivo del
 * evento `progress` del backend. Este componente no hace peticiones.
 */
import { computed } from "vue";
import { useTrabajosStore } from "../stores/trabajos.js";

const props = defineProps({
  /** `true` sobre el fondo navy del shell, `false` sobre fondo claro. */
  dark: { type: Boolean, default: true },
});

const trabajos = useTrabajosStore();

/** Icono y color de cada estado de paso. */
const ICONOS = {
  pending: { icono: "○", clase: "text-on-shell-faint" },
  running: { icono: "↻", clase: "text-accent-bright" },
  done: { icono: "✓", clase: "text-green-600" },
  error: { icono: "✗", clase: "text-red-600" },
};

const progreso = computed(() => trabajos.progreso);

/** `true` si hay algo que enseñar. */
const hayContenido = computed(() => {
  const p = progreso.value;
  if (p.active) return true;
  if (p.error) return true;
  return Array.isArray(p.stages) && p.stages.length > 0;
});

/** Modo visual del panel. */
const modo = computed(() => {
  const p = progreso.value;
  if (p.active) return "running";
  if (p.error) return "error";
  if (Array.isArray(p.stages) && p.stages.length > 0) return "success";
  return "idle";
});

/** Color de la barra. */
const claseBarra = computed(() => {
  if (modo.value === "running") return props.dark ? "bg-accent-bright" : "bg-accent";
  if (modo.value === "error") return "bg-red-600";
  if (modo.value === "success") return "bg-green-600";
  return props.dark ? "bg-shell-border" : "bg-surface-sunken";
});

/** Icono del titulo. El de `running` gira: da feedback de operacion en curso. */
const iconoTitulo = computed(() => {
  if (modo.value === "error") return "✗";
  if (modo.value === "success") return "✓";
  if (modo.value === "running") return "↻";
  return "";
});

/** Texto del titulo. */
const textoTitulo = computed(() => {
  if (modo.value === "error") return "Error";
  if (modo.value === "success") return "Completado";
  if (modo.value === "running") return "En curso";
  return "";
});

/** Subtitulo: la operacion o el error. */
const subtitulo = computed(() => {
  const p = progreso.value;
  if (modo.value === "error") return p.error || "Operación fallida";
  if (modo.value === "success") return `${p.current}/${p.total} completados`;
  if (modo.value === "running") {
    return p.label ? `${p.label} — ${p.current}/${p.total}` : `Paso ${p.current}/${p.total}`;
  }
  return "";
});

/** Icono de un paso, segun su estado. */
function iconoDe(estado) {
  return ICONOS[estado] || { icono: "?", clase: "text-on-shell-faint" };
}

/** Cierra el faceplate. El backend no guarda el progreso: se limpia aqui. */
function cerrar() {
  trabajos.limpiarProgreso();
}
</script>

<template>
  <section
    v-if="hayContenido"
    data-testid="faceplate-progreso"
    :data-mode="modo"
    :class="dark ? 'border-t border-shell-border bg-shell-deep p-3' : 'border-t border-line bg-surface-sunken p-3'"
  >
    <header class="flex justify-between items-center mb-2">
      <div class="min-w-0 flex-1">
        <div :class="dark ? 'text-xs font-bold text-on-shell' : 'text-xs font-bold text-ink'">
          <span
            v-if="iconoTitulo"
            :class="modo === 'running' ? 'inline-block animate-spin mr-1' : 'mr-1'"
            data-testid="faceplate-icono"
          >
            {{ iconoTitulo }}
          </span>
          {{ textoTitulo }}
        </div>
        <div
          :class="dark ? 'text-[10px] text-on-shell-muted truncate' : 'text-[10px] text-ink-muted truncate'"
        >
          {{ subtitulo }}
        </div>
      </div>
      <button
        class="ml-2 text-xs px-1.5 py-0.5 bg-shell-hover border border-shell-border rounded hover:bg-shell-active text-on-shell-muted hover:text-on-shell"
        title="Cerrar (limpiar el progreso)"
        data-testid="faceplate-cerrar"
        @click="cerrar"
      >
        ✕
      </button>
    </header>

    <div :class="dark ? 'h-1.5 bg-shell-border mb-2 rounded' : 'h-1.5 bg-surface mb-2 rounded'">
      <div
        class="h-full transition-all duration-300 rounded"
        :class="claseBarra"
        :style="{ width: progreso.percent + '%' }"
      ></div>
    </div>

    <ol class="text-[10px] font-mono leading-snug" data-testid="faceplate-pasos">
      <li
        v-for="(paso, indice) in progreso.stages"
        :key="paso.id"
        :class="['flex justify-between items-baseline py-0.5', paso.status === 'running' ? 'bg-shell-hover rounded px-1 -mx-1' : '']"
      >
        <span class="flex items-baseline gap-1 min-w-0 flex-1">
          <span
            :class="['w-3 text-center', iconoDe(paso.status).clase, paso.status === 'running' ? 'inline-block animate-spin' : '']"
            :data-testid="'faceplate-paso-icono-' + paso.id"
          >
            {{ iconoDe(paso.status).icono }}
          </span>
          <span class="text-on-shell-faint w-4 text-right">{{ indice + 1 }}.</span>
          <span
            class="truncate"
            :class="paso.status === 'pending' ? 'text-on-shell-faint' : 'text-on-shell'"
          >
            {{ paso.label }}
          </span>
          <span v-if="paso.detail" class="text-on-shell-faint italic text-[9px] truncate ml-1">
            — {{ paso.detail }}
          </span>
        </span>
      </li>
    </ol>
  </section>
</template>
