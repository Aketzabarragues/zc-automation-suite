<script setup>
/**
 * Dispositivos: la prevision de los dispositivos del PLC frente al Excel.
 *
 * Es una vista de solo lectura: la prevision la calcula el backend (exporta
 * del PLC y compara con el Excel). El boton de aplicar todavia no hace nada:
 * es la fase 4.3.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useDispositivosStore } from "../../../stores/dispositivos.js";
import { useExcelStore } from "../../../stores/excel.js";
import { usePlcStore } from "../../../stores/plc.js";
import { useTiaStore } from "../../../stores/tia.js";

const dispositivos = useDispositivosStore();
const excel = useExcelStore();
const plc = usePlcStore();
const tia = useTiaStore();

/** El tipo de dispositivo whose diff se muestra. */
const tipoActivo = ref("");

/** El texto y el color de cada estado del diff. */
const ESTADOS = {
  renombrar: { texto: "✏️ RENOMBRAR", clase: "text-orange-600" },
  agregar: { texto: "➕ AGREGAR", clase: "text-accent" },
  eliminar: { texto: "ELIMINAR", clase: "text-red-600" },
  sin_cambios: { texto: "✓ OK", clase: "text-ink-muted" },
};

/** `true` si se puede generar la prevision. */
const puedeGenerar = computed(
  () => tia.conectado && excel.cargado && Boolean(plc.seleccionado) && !dispositivos.generando,
);

/** El texto del boton de generar. */
const textoGenerar = computed(() => {
  if (dispositivos.generando) return "Generando prevision…";
  return "🔍 Generar Previsión";
});

/** Las filas del diff del tipo activo. */
const filas = computed(() => dispositivos.filasPorTipo.get(tipoActivo.value) || []);

/** El estado de una fila, con su texto y su color. */
function estadoDe(fila) {
  return ESTADOS[fila.status] || { texto: fila.status, clase: "text-ink-muted" };
}

/** El resumen de la prevision, en una linea. */
const resumenTexto = computed(() => {
  const resumen = dispositivos.resumen;
  return `${resumen.total || 0} dispositivos analizados — ${resumen.agregar || 0} a agregar · ${
    resumen.renombrados || 0
  } a renombrar · ${resumen.eliminar || 0} a eliminar · ${resumen.sin_cambios || 0} sin cambios`;
});

/** Los N_MAX que cambian: los que se pintan con la flecha. */
const nMaxVisibles = computed(() => dispositivos.nMax.filter((fila) => fila.status === "actualizar"));

/** Genera la prevision. */
async function generar() {
  await dispositivos.generar(plc.seleccionado);
}

// Al llegar una prevision nueva, se ensena el primer tipo con filas.
watch(
  () => dispositivos.tipos,
  (tipos) => {
    if (!tipos.length) {
      tipoActivo.value = "";
      return;
    }
    if (!tipos.some((tipo) => tipo.tipo === tipoActivo.value)) {
      tipoActivo.value = tipos[0].tipo;
    }
  },
  { immediate: true },
);

onMounted(() => {
  excel.cargar();
});
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col gap-4" data-testid="dispositivos">
    <!-- ── la barra de arriba ──────────────────────────────────────── -->
    <section class="bg-surface-raised border border-line rounded p-4">
      <div class="flex items-center justify-between gap-4">
        <p class="text-xs text-ink-muted" data-testid="dispositivos-resumen">
          <template v-if="dispositivos.hayPreview">{{ resumenTexto }}</template>
          <template v-else>Sin prevision generada.</template>
        </p>
        <button
          type="button"
          data-testid="dispositivos-generar"
          class="px-3 py-1.5 text-xs font-semibold text-accent bg-surface-sunken border border-line rounded-md hover:bg-accent-subtle transition-colors duration-200 flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="!puedeGenerar"
          @click="generar"
        >
          {{ textoGenerar }}
        </button>
      </div>
    </section>

    <!-- ── el error ─────────────────────────────────────────────────── -->
    <div
      v-if="dispositivos.error"
      class="bg-surface-raised border border-red-600 rounded p-3 text-xs text-red-600"
      data-testid="dispositivos-error"
    >
      ✗ {{ dispositivos.error }}
    </div>

    <!-- ── el contenido ─────────────────────────────────────────────── -->
    <section
      class="flex-1 min-h-0 flex flex-col bg-surface-raised border border-line rounded p-4"
      data-testid="dispositivos-contenido"
    >
      <template v-if="dispositivos.hayPreview">
        <!-- las tarjetas de N_MAX -->
        <div
          v-if="nMaxVisibles.length"
          class="grid grid-cols-6 gap-2 mb-4"
          data-testid="dispositivos-nmax"
        >
          <div
            v-for="fila in nMaxVisibles"
            :key="fila.name"
            class="border border-line rounded p-3"
          >
            <p class="text-[10px] uppercase text-ink-muted">{{ fila.name }}</p>
            <p class="text-lg font-semibold text-ink">
              {{ fila.actual }}
              <span class="text-ink-muted">→</span>
              <span class="text-orange-600">{{ fila.nuevo }}</span>
            </p>
          </div>
        </div>

        <!-- las pestañas por tipo -->
        <div class="flex border-b-2 border-line bg-surface-sunken overflow-x-auto">
          <button
            v-for="tipo in dispositivos.tipos"
            :key="tipo.tipo"
            type="button"
            :data-testid="'dispositivos-tipo-' + tipo.tipo"
            class="px-4 py-2 text-xs font-semibold border-r border-line whitespace-nowrap"
            :class="
              tipo.tipo === tipoActivo
                ? 'bg-surface-raised text-ink border-b-2 border-accent -mb-px'
                : 'bg-surface-sunken text-ink-muted hover:bg-surface-raised'
            "
            @click="tipoActivo = tipo.tipo"
          >
            {{ tipo.tipo.toUpperCase() }}
            <span class="ml-1 text-[10px] opacity-70">({{ tipo.total }})</span>
          </button>
        </div>

        <!-- la tabla del diff -->
        <div class="mt-3 flex-1 min-h-0 overflow-auto border border-line rounded">
          <table class="w-full text-xs" data-testid="dispositivos-tabla">
            <thead>
              <tr class="bg-surface-sunken">
                <th class="px-3 py-2 text-left text-[10px] uppercase text-ink-muted font-semibold">#</th>
                <th class="px-3 py-2 text-left text-[10px] uppercase text-ink-muted font-semibold">
                  Actual (TIA)
                </th>
                <th class="px-3 py-2 text-left text-[10px] uppercase text-ink-muted font-semibold">
                  Deseado (Excel)
                </th>
                <th class="px-3 py-2 text-left text-[10px] uppercase text-ink-muted font-semibold">
                  Estado
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="fila in filas" :key="fila.uid" class="border-b border-line">
                <td class="px-3 py-1.5 text-ink-muted">{{ fila.numero }}</td>
                <td class="px-3 py-1.5 text-ink font-mono">{{ fila.actual || "—" }}</td>
                <td
                  class="px-3 py-1.5 font-mono"
                  :class="fila.status === 'renombrar' ? 'text-orange-600' : 'text-ink'"
                >
                  {{ fila.nuevo || "—" }}
                </td>
                <td class="px-3 py-1.5" :class="estadoDe(fila).clase">
                  {{ estadoDe(fila).texto }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- sin prevision -->
      <div
        v-else
        class="flex-1 flex flex-col items-center justify-center border border-dashed border-line rounded p-10 text-center"
        data-testid="dispositivos-vacio"
      >
        <div class="text-5xl mb-3 opacity-40" aria-hidden="true">⚡</div>
        <p class="mb-2 font-semibold text-ink">Sin prevision generada.</p>
        <p class="text-xs text-ink-muted">
          Pulsa <span class="font-semibold text-accent">"🔍 Generar Previsión"</span> para ver el
          diff completo.
        </p>
      </div>

      <!-- el boton de aplicar: todavia no hace nada -->
      <button
        type="button"
        disabled
        data-testid="dispositivos-aplicar"
        class="mt-4 w-full py-2.5 rounded border border-line bg-surface-sunken text-sm font-semibold text-ink-muted cursor-not-allowed"
      >
        Pendiente (fase 4.3)
      </button>
    </section>
  </section>
</template>
